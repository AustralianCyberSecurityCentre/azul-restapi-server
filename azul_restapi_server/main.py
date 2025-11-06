"""REST API Server App.

Main setup of the FastAPI server app and basic routes.
"""

import asyncio
import importlib.resources
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

from azul_bedrock.exceptions import ApiException, DispatcherApiException
from fastapi import FastAPI, Request
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles
from starlette_exporter import PrometheusMiddleware, handle_metrics

from azul_restapi_server import settings

from . import __version__, plugins, static
from .logging import RestAPILogger
from .middleware.logging import AuditMiddleware

root_path = settings.restapi.root_path.rstrip("/")
api_prefix = settings.restapi.prefix.rstrip("/").lstrip("/")

# patch asyncio to limit threads in kubernetes to not use cpu_count() which is inaccurate
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    pass
else:
    print(f"limiting asyncio workers to {settings.restapi.asyncio_workers}")
    loop.set_default_executor(ThreadPoolExecutor(max_workers=settings.restapi.asyncio_workers))


# Optional settings to pass into App setup
optional_settings = {}
get_ui_optional_settings = {}
if settings.restapi.security == "oidc":
    optional_settings["swagger_ui_init_oauth"] = {
        "clientId": settings.oidc.client_id,
        "scopes": settings.oidc.scopes,
        "usePkceWithAuthorizationCodeGrant": True,
    }
    get_ui_optional_settings["init_oauth"] = optional_settings["swagger_ui_init_oauth"]
if settings.oidc.swagger_redirect_url:
    optional_settings["swagger_ui_oauth2_redirect_url"] = settings.oidc.swagger_redirect_url

app = FastAPI(
    title="Azul",
    version=str(__version__),
    openapi_url=f"/{api_prefix}/openapi.json",
    root_path=root_path,
    docs_url=None,
    redoc_url=None,
    **optional_settings,
)
app.mount(
    f"/{api_prefix}/static",
    StaticFiles(directory=str(importlib.resources.files(static))),
)

# This needs to go first in order to access unencoded bodies
app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors.allow_origins,
    allow_credentials=settings.cors.allow_credentials,
    allow_methods=settings.cors.allow_methods,
    allow_headers=settings.cors.allow_headers,
)
app.add_middleware(
    PrometheusMiddleware,
    app_name="azul",
    prefix="azulapi",
    group_paths=True,
    # capture higher end of response times in histogram
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        2.5,
        5.0,
        7.5,
        10.0,
        30.0,
        60.0,
        120.0,
        float("inf"),
    ),
)

_logger = RestAPILogger()
app.logger = _logger.logger
app.audit_logger = _logger.audit_logger


try:
    from opensearchpy import exceptions as elexc
except ImportError:
    elexc = None
    print("Not handling opensearch exceptions.")
else:
    # has to be installed into the app
    @app.exception_handler(elexc.AuthenticationException)
    async def os_authc_exception_handler(request: Request, exc: elexc.AuthenticationException):
        """Capture elasticsearch authc exceptions."""
        traceback.print_exc()
        return JSONResponse(status_code=401, content=dict(detail="Opensearch authentication failed"))

    @app.exception_handler(elexc.AuthorizationException)
    async def os_authz_exception_handler(request: Request, exc: elexc.AuthenticationException):
        """Capture elasticsearch authz exceptions."""
        traceback.print_exc()
        return JSONResponse(status_code=403, content=dict(detail="Opensearch authorization failed"))


def base_api_exception_handler(request, exc: ApiException | DispatcherApiException):
    """Capture generic restapi errors and print details."""
    # print traceback for bad codes only
    # 2xx success
    # 4xx client error
    if not (200 <= exc.status_code <= 299) and not (400 <= exc.status_code <= 499):
        app.logger.error(repr(exc))
        print(exc.detail, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    content = {
        "ref": exc.detail.get("ref", "no ref supplied"),
        "message": exc.detail.get("external", "no message supplied"),
    }
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(DispatcherApiException)
async def dispatcher_api_exception_handler(request, exc: DispatcherApiException):
    """Capture generic restapi errors and print details."""
    return base_api_exception_handler(request, exc)


@app.exception_handler(ApiException)
async def api_exception_handler(request, exc: ApiException):
    """Capture generic restapi errors and print details."""
    return base_api_exception_handler(request, exc)


@app.get("/", include_in_schema=False)
@app.get("/docs", include_in_schema=False)
async def read_root(req: Request):
    """Redirect to docs."""
    root = req.scope.get("root_path")
    return RedirectResponse(f"{root}/{api_prefix}")


# provide offline access to swagger doc and redoc instead of via a cdn
# customise favicon
@app.get(f"/{api_prefix}", include_in_schema=False)
async def custom_swagger_ui_html(req: Request) -> HTMLResponse:
    """Show the API documentation via Swagger."""
    root = req.scope.get("root_path")
    return get_swagger_ui_html(
        openapi_url=f"{root}{app.openapi_url}",
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url=f"{root}/{api_prefix}/static/swagger-ui-bundle.js",
        swagger_css_url=f"{root}/{api_prefix}/static/swagger-ui.css",
        swagger_favicon_url=f"{root}/{api_prefix}/static/azul-ico.r.32.png",
        **get_ui_optional_settings,
    )


if app.swagger_ui_oauth2_redirect_url:

    @app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
    async def swagger_ui_redirect(req: Request) -> HTMLResponse:
        """Enable oauth2 support in swagger doc."""
        return get_swagger_ui_oauth2_redirect_html()


@app.get(f"/{api_prefix}/redoc", include_in_schema=False)
async def redoc_html(req: Request) -> HTMLResponse:
    """Show the API documentation via ReDoc."""
    root = req.scope.get("root_path")

    return get_redoc_html(
        openapi_url=f"{root}{app.openapi_url}",
        title=app.title + " - ReDoc",
        redoc_js_url=f"{root}/{api_prefix}/static/redoc.standalone.js",
        redoc_favicon_url=f"{root}/{api_prefix}/static/azul-ico.r.32.png",
        with_google_fonts=False,
    )


# metrics is only available at the root path (not api_prefix) - for prometheus
app.add_route("/metrics", handle_metrics)

# add extra routes after the doc routes, so they can't accidentally override
app.include_router(plugins.get_router(), prefix=f"/{api_prefix}")
