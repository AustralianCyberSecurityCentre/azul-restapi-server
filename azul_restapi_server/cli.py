"""CLI entry to run the server."""

from functools import partial

import click
import uvicorn

from azul_restapi_server import settings

# always show default
click.option = partial(click.option, show_default=True)


@click.command()
@click.option("--host", default=settings.restapi.host)
@click.option("--port", default=settings.restapi.port)
@click.option("--workers", default=settings.restapi.workers)
@click.option("--reload/--no-reload", default=settings.restapi.reload)
def run(host, port, workers, reload):
    """Start the Azul API server."""
    headers: list[str, str] = []
    for header_label, header_val in settings.restapi.headers.items():
        headers.append((header_label.strip(), header_val.strip()))

    # access log is disabled, as we are using our own middleware to log access
    uvicorn.run(
        "azul_restapi_server.main:app",
        forwarded_allow_ips="*",
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        access_log=False,
        headers=headers,
    )


if __name__ == "__main__":
    run()
