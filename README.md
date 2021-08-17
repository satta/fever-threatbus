FEVER Threat Bus connector
==========================

The FEVER-Threat Bus connector acts as bridge between Threat Bus and FEVER,
updating FEVER's internal Bloom filter matcher with all compatible indicators
that are distributedd via Threat Bus.

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
`/tmp/fever-mgmt.sock`).