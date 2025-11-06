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
entry_points={
    'azul_restapi.plugin': [
        'extraroute = my_plugin.v1.extraroute:router',
    ],
}
```

### API Versioning

API versioning is achieved by running multiple restapi-servers in parallel behind a reverse proxy/kubernetes ingress
each configured with different plugin versions in the requirements.txt.

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
