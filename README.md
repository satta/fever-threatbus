FEVER Threat Bus connector
==========================

The FEVER-Threat Bus connector acts as bridge between Threat Bus and FEVER,
updating FEVER's internal Bloom filter matcher with all compatible indicators
that are distributed via Threat Bus.

## Quick Start

You can configure the app via a YAML configuration file. See
`config.yaml.example` for an example config file. Rename the example to
`config.yaml` before starting.

Alternatively, configure the app via environment variables, similarly to Threat
Bus, or pass a path to configuration file via `-c /path/to/config.yaml`.

Install `fever-threatbus` in a virtualenv and start:

```sh
python -m venv venv
source venv/bin/activate
make dev-mode
fever-threatbus
```

In the configuration file, you mainly need to configure the `socket` option in
the config file, specifying the path to FEVER's control socket (default
`/tmp/fever-mgmt.sock`). It is also possible to configure what indicator
[object paths](https://docs.oasis-open.org/cti/stix/v2.1/cs02/stix-v2.1-cs02.html#_r80k3nm8z2we)
are to be included into the Bloom filter. For example, the following
(default) settings of

```yaml
...
threatbus: localhost:13370
snapshot: 30

# Socket for the FEVER gRPC connection
socket: /tmp/fever-mgmt.sock
# STIX Object Paths to include in Bloom filter additions
object_paths:
  - domain-name:value
  - url:value
```

would cause patterns like

- `[domain-name:value = 'evil.com']`
- `[url:value = 'http://example.com/foo']`

to be matched via FEVER's Bloom filter.