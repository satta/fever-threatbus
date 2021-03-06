#!/usr/bin/env python3

import argparse
import asyncio
import atexit
from typing import Callable, List
from dynaconf import Dynaconf, Validator
from dynaconf.base import Settings
from dynaconf.utils.boxing import DynaBox
import logging
import signal
from stix2 import parse
import sys
from threatbus.logger import setup as setup_logging_threatbus
from threatbus import stix2_helpers
import zmq
from . import mgmt_pb2, mgmt_pb2_grpc
import grpc
from google.protobuf import empty_pb2

logger_name = "fever-threatbus"
logger = logging.getLogger(logger_name)
# List of all running async tasks of the bridge.
async_tasks = []
# The p2p topic sent back by Threat Bus upon successful subscription.
p2p_topic = None
# Boolean flag indicating that the user has issued a SIGNAL (e.g., SIGTERM).
user_exit = False
# gRPC channel
channel = None
# gRPC stub
stub = None


### --------------------------- Application helpers ---------------------------


def setup_logging_with_config(config: DynaBox):
    """
    Sets up the global logger as configured in the `config` object.
    @param config The user-defined logging configuration
    """
    global logger
    logger = setup_logging_threatbus(config, logger_name)


def validate_config(config: Settings):
    """
    Validates the given Dynaconf object. Throws if the config is invalid.
    """
    validators = [
        Validator("logging.console", is_type_of=bool, required=True, eq=True)
        | Validator("logging.file", is_type_of=bool, required=True, eq=True),
        Validator(
            "logging.console_verbosity",
            is_in=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            required=True,
            when=Validator("logging.console", eq=True),
        ),
        Validator(
            "logging.file_verbosity",
            is_in=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            required=True,
            when=Validator("logging.file", eq=True),
        ),
        Validator(
            "logging.filename", required=True, when=Validator("logging.file", eq=True)
        ),
        Validator("threatbus", required=True),
        Validator("socket", required=True),
        Validator("object_paths", len_min=1, required=True),
    ]
    config.validators.register(*validators)
    config.validators.validate()


async def cancel_async_tasks():
    """
    Cancels all async tasks.
    """
    global async_tasks
    for task in async_tasks:
        if task is not asyncio.current_task():
            task.cancel()
            del task
    async_tasks = []
    return await asyncio.gather(*async_tasks)


async def stop_signal():
    """
    Implements Python's asyncio eventloop signal handler
    https://docs.python.org/3/library/asyncio-eventloop.html
    Cancels all running tasks and exits the app.
    """
    global user_exit
    user_exit = True
    await cancel_async_tasks()


### --------------- ZeroMQ communication / management functions ---------------


def send_manage_message(endpoint: str, action: dict, timeout: int = 5):
    """
    Sends a 'management' message, following the threatbus-zmq protocol to
    either subscribe or unsubscribe this application to/from Threat Bus.
    @param endpoint A host:port string to connect to via ZeroMQ
    @param action The message to send as JSON
    @param timeout The period after which the connection attempt is aborted
    """
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.LINGER, 0)
    socket.connect(f"tcp://{endpoint}")
    socket.send_json(action)
    poller = zmq.Poller()
    poller.register(socket, zmq.POLLIN)

    reply = None
    if poller.poll(timeout * 1000):
        reply = socket.recv_json()
    socket.close()
    context.term()
    return reply


def reply_is_success(reply: dict):
    """
    Predicate to check if `reply` is a dict and contains the key-value pair
    "status" = "success"
    @param reply A python dict
    @return True if the dict contains "status" = "success"
    """
    return (
        reply
        and type(reply) is dict
        and reply.get("status", None)
        and reply["status"] == "success"
    )


def subscribe(endpoint: str, topic: str, snapshot: int, timeout: int = 5):
    """
    Subscribes this app to Threat Bus for the given topic. Requests an optional
    snapshot of historical indicators.
    @param endpoint The ZMQ management endpoint of Threat Bus ('host:port')
    @param topic The topic to subscribe to
    @param snapshot An integer value to request n days of historical IoC items
    @param timeout The period after which the connection attempt is aborted
    """
    global logger
    logger.info(f"Subscribing to topic '{topic}'...")
    action = {"action": "subscribe", "topic": topic, "snapshot": snapshot}
    return send_manage_message(endpoint, action, timeout)


def unsubscribe(endpoint: str, topic: str, timeout: int = 5):
    """
    Unsubscribes this app from Threat Bus for the given topic.
    @param endpoint The ZMQ management endpoint of Threat Bus
    @param topic The topic to unsubscribe from
    @param timeout The period after which the connection attempt is aborted
    """
    global logger
    logger.info(f"Unsubscribing from topic '{topic}' ...")
    action = {"action": "unsubscribe", "topic": topic}
    reply = send_manage_message(endpoint, action, timeout)
    if not reply_is_success(reply):
        logger.warning("Unsubscription failed")
        return
    logger.info("Unsubscription successful")


async def heartbeat(endpoint: str, p2p_topic: str, interval: int = 5):
    """
    Sends heartbeats to Threat Bus periodically to check if the given p2p_topic
    is still valid at the Threat Bus host. Cancels all async tasks of this app
    when the heartbeat fails and stops the heartbeat.
    @param endpoint The ZMQ management endpoint of Threat Bus
    @param p2p_topic The topic string to include in the heartbeat
    @param timeout The period after which the connection attempt is aborted
    """
    global logger
    action = {"action": "heartbeat", "topic": p2p_topic}
    while True:
        reply = send_manage_message(endpoint, action, interval)
        if not reply_is_success(reply):
            logger.error("Subscription with Threat Bus host became invalid")
            return await cancel_async_tasks()
        await asyncio.sleep(interval)


### --------------------------- The actual app logic ---------------------------


def get_reconnector(socket: str):
    global channel, stub, logger

    async def establish_stream():
        global channel, stub, logger
        logger.info(f"Connecting to {socket}")
        channel = grpc.aio.insecure_channel(f"unix://{socket}")
        await channel.channel_ready()
        stub = mgmt_pb2_grpc.MgmtServiceStub(channel)
        blfinfo = await stub.BloomInfo(empty_pb2.Empty())
        logger.info(
            f"Connected to FEVER, has BLF with {blfinfo.elements} items and capacity {blfinfo.capacity}"
        )

    return establish_stream


async def start(zmq_endpoint: str, snapshot: int, socket: str, opaths: List[str]):
    """
    Starts the app.
    @param zmq_endpoint The ZMQ management endpoint of Threat Bus ('host:port')
    @param snapshot An integer value to request n days of historical IoC items
    """
    global logger, async_tasks, p2p_topic
    # needs to be created inside the same eventloop where it is used
    logger.debug(f"Calling Threat Bus management endpoint {zmq_endpoint}")
    reply = subscribe(zmq_endpoint, "stix2/indicator", snapshot)
    if not reply_is_success(reply):
        logger.error("Subscription failed")
        return
    pub_port = reply.get("pub_port", None)
    sub_port = reply.get("sub_port", None)
    topic = reply.get("topic", None)
    if not pub_port or not sub_port or not topic:
        logger.error("Subscription failed")
        return
    zmq_host = zmq_endpoint.split(":")[0]
    pub_endpoint = f"{zmq_host}:{pub_port}"
    sub_endpoint = f"{zmq_host}:{sub_port}"

    logger.info(f"Subscription successful. New p2p_topic: {topic}")
    if p2p_topic:
        # The 'start' function is called as result of a restart
        # Unsubscribe the old topic as soon as we get a working connection
        logger.info("Cleaning up old p2p_topic subscription ...")
        unsubscribe(zmq_endpoint, p2p_topic)
        atexit.unregister(unsubscribe)
    p2p_topic = topic
    atexit.register(unsubscribe, zmq_endpoint, topic)

    # Start a heartbeat task so we notice when the Threat Bus host goes away
    async_tasks.append(
        asyncio.create_task(heartbeat(zmq_endpoint, p2p_topic, interval=5))
    )

    # Start a receive task to retrieve real-time updates from Threat Bus
    indicator_queue = asyncio.Queue()
    async_tasks.append(
        asyncio.create_task(receive(pub_endpoint, p2p_topic, indicator_queue))
    )

    # Create a reconnector closure wrapping the socket address
    reconn = get_reconnector(socket)

    # Do initial connect
    await reconn()

    # Start async task to process incoming indicators
    async_tasks.append(
        asyncio.create_task(add_indicator(indicator_queue, reconn, opaths))
    )

    # Run logic tasks
    loop = asyncio.get_event_loop()
    for s in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(s, lambda: asyncio.create_task(stop_signal()))
    return await asyncio.gather(*async_tasks)


async def receive(pub_endpoint: str, topic: str, indicator_queue: asyncio.Queue):
    """
    Starts a zmq subscriber on the given endpoint and listens for new messages
    that are published on the given topic (zmq prefix matching). Depending on
    the topic suffix, Indicators are enqueued to the indicator_queue.
    @param pub_endpoint A host:port string to connect to via zmq
    @param topic The topic prefix to subscribe to intelligence items
    @param indicator_queue The queue to put arriving IoCs into
    """
    global logger
    socket = zmq.Context().socket(zmq.SUB)
    socket.connect(f"tcp://{pub_endpoint}")
    socket.setsockopt(zmq.SUBSCRIBE, topic.encode())
    poller = zmq.Poller()
    poller.register(socket, zmq.POLLIN)
    logger.info(f"Receiving via ZMQ on topic {pub_endpoint}/{topic}")
    while True:
        socks = dict(poller.poll(timeout=100))  # Smaller timeouts increase CPU load
        if socket in socks and socks[socket] == zmq.POLLIN:
            try:
                topic, msg = socket.recv().decode().split(" ", 1)
            except Exception as e:
                logger.error(f"Error decoding message: {e}")
                continue
            # The topic is suffixed with the message type. Use it for filtering
            if not topic.endswith("indicator"):
                logger.debug(f"Skipping unsupported message: {msg}")
                continue
            # Put the message into the queue for incoming intel items, so they
            # can be processed asynchronously
            await indicator_queue.put(msg)
        else:
            await asyncio.sleep(0.01)  # Free event loop for other tasks


async def add_indicator(
    indicator_queue: asyncio.Queue, reconn: Callable[[], None], opaths: List[str]
):
    """
    Adds a received indicator to the Bloom filter.
    @param indicator_queue The queue to put arriving IoCs into
    """
    global stub
    while True:
        msg = await indicator_queue.get()
        indicator = parse(msg, allow_custom=True)
        if "x_threatbus_update" in indicator and indicator["x_threatbus_update"] == REMOVE:
            logger.warning(f"Indicator delivery indicates REMOVE, skipping")
            continue
        logger.debug(f"Got indicator from Threat Bus: {indicator}")
        if not stix2_helpers.is_point_equality_ioc(indicator.pattern):
            logger.warning(f"Pattern {indicator.pattern} is not a point IoC, skipping")
            continue
        pair = stix2_helpers.split_object_path_and_value(indicator.pattern)
        if not pair or len(pair) != 2:
            logger.warning(f"Invalid indicator pattern {indicator.pattern}, skipping")
            continue
        if pair[0] not in opaths:
            logger.warning(f"Object path {pair[0]} not configured, skipping")
            continue
        while True:
            try:
                result = await stub.BloomAdd(
                    iter([mgmt_pb2.MgmtBloomAddRequest(ioc=pair[1])])
                )
                logger.debug(f"Added {result.added} item(s)")
            except grpc.RpcError:
                logging.exception("error during BloomAdd request")
                await reconn()
            else:
                break
        indicator_queue.task_done()


def main():
    settings_files = ["config.yaml", "config.yml"]
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", help="path to a configuration file")
    args = parser.parse_args()
    if args.config:
        if not args.config.endswith("yaml") and not args.config.endswith("yml"):
            sys.exit("Please provide a `yaml` or `yml` configuration file.")
        settings_files = [args.config]

    config = Dynaconf(
        settings_files=settings_files,
        load_dotenv=True,
        envvar_prefix="FEVER_THREATBUS",
    )

    try:
        validate_config(config)
    except Exception as e:
        sys.exit(ValueError(f"Invalid config: {e}"))

    setup_logging_with_config(config.logging)

    while True:
        try:
            asyncio.run(
                start(
                    config.threatbus,
                    config.snapshot,
                    config.socket,
                    config.object_paths,
                )
            )
        except (KeyboardInterrupt, SystemExit):
            return
        except asyncio.CancelledError:
            if user_exit:
                # Tasks were cancelled because the user stopped the app.
                return
            logger.info("Restarting FEVER-ThreatBus app ...")


if __name__ == "__main__":
    main()
