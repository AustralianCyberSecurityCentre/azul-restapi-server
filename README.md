# Azul Restapi Server

Public Azul RESTful API server.

## Introduction

This project is the base server and is responsible for bringing all components together and organising them under a
single api version. All routes are enabled via installable plugins. The set of plugins can be customised by editing
the enabled_plugins.txt file. These can be installed directly using pip -r and is used by the included Dockerfile.

API plugins are developed as separate projects and are expected to expose an entry point of `azul_restapi.plugin`.
Plugin modules should expose a variable of type `fastapi.APIRouter` at this entry point.

Example Entry point for plugins:

```python
entry_points = {
    "azul_restapi.plugin": [
        "extraroute = my_plugin.v1.extraroute:router",
    ],
}
```

## Quickstart

### Install

Install the server:

```bash
pip install azul-restapi-server
```

Install default plugins:

```bash
pip install azul-metastore
```

### Run

To start a server, simply run:

```bash
azul-restapi-server
```

For more performance with a custom configuration use the following command.

```bash
gunicorn -k uvicorn.workers.UvicornWorker -c "$GUNICORN_CONF" azul_restapi_server.main:app
```

### Running a local server for manual testing

To help with your development, it may be beneficial to run the server and interactively play around with it.

To start the server for playing around with your development changes:

```bash
azul-restapi-server --reload
```

To start the server for development exposed on your interface using a custom CA:

```bash
SSL_CERT_FILE=/path/to/ca-bundle.crt azul-restapi-server --host <IP> --reload
```

## Dependency management

Dependencies are managed in the pyproject.toml and debian.txt file.

Version pinning is achieved using the `uv.lock` file.
Because the `uv.lock` file is configured to use a private UV registry, external developers using UV will need to delete the existing `uv.lock` file and update the project configuration to point to the publicly available PyPI registry instead.

To add new dependencies it's recommended to use uv with the command `uv add <new-package>`
    or for a dev package `uv add --dev <new-dev-package>`

The tool used for linting and managing styling is `ruff` and it is configured via `pyproject.toml`

The debian.txt file manages the debian dependencies that need to be installed on development systems and docker images.

Sometimes the debian.txt file is insufficient and in this case the Dockerfile may need to be modified directly to
install complex dependencies.
