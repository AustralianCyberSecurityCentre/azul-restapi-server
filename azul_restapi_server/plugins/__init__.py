"""Plugin loader for additional routes.

Load all API plugins in the correct package namespace.

API plugins are expected to use an entry point of `azul-restapi.plugins`.
Plugin modules should expose a variable of type `fastapi.APIRouter`

Example Entry point for plugins:

    entry_points={
        'azul_restapi.plugin': [
            'base_route = my_plugin.api:router',
        ],
    }
"""

import importlib.metadata

from azul_bedrock.exceptions_bedrock import BaseError
from fastapi import APIRouter, Depends

from azul_restapi_server import settings
from azul_restapi_server.settings import retrohunt
from azul_restapi_server.security import validate_token


def get_router():
    """Search the configured entry points and load the defined routers."""
    plugins = sorted(
        [(ep.name, ep.load()) for ep in importlib.metadata.entry_points().select(group="azul_restapi.plugin")],
        key=lambda x: x[0],
    )
    router = APIRouter()
    for name, plugin in plugins:
        # don't install retrohunt if it is disabled
        if name == "retrohunt" and not retrohunt.enabled:
            print("Skipping retrohunt plugin")
            continue
        if name == "pat" and not settings.restapi.is_pat_enabled:
            print("Skipped loading plugin pat, because pat isn't enabled.")
            continue
        print(f"loaded plugin: {name}")
        router.include_router(
            plugin,
            tags=[name],
            responses={
                404: {"description": "Not found"},
                500: {"model": BaseError, "description": "Something went wrong"},
            },
            # require all users of an api to have a valid token
            dependencies=[Depends(validate_token)],
        )
    return router
