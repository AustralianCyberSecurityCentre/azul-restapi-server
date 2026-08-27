"""OIDC with PAT flow authentication."""

from typing import Optional

from azul_bedrock import exceptions_bedrock
from azul_bedrock.exception_enums import ExceptionCodeEnum
from azul_bedrock.models_auth import UserInfo
from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, OpenIdConnect
from starlette.status import HTTP_401_UNAUTHORIZED

from azul_restapi_server import settings
from azul_restapi_server.security import pat_core

from . import oidc_shared

_openidconnect_code_flow = OpenIdConnect(
    openIdConnectUrl=settings.oidc.discovery_url,
    auto_error=False,
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def validate_token(
    request: Request,
    oauth_bearer: Optional[str] = Depends(_openidconnect_code_flow),
    api_key: Optional[str] = Depends(_api_key_header),
) -> UserInfo:
    """Validate the input token.

    The dependency here only parses the token out of the http request.
    It describes to swagger how oidc is needed.
    It does not perform validation.

    There is also optional API key validation.
    """
    if oauth_bearer:
        token_values = oauth_bearer.split(" ")
        request.state.user_info = oidc_shared.validate(token_values[-1], settings.oidc.client_id)
        # TODO remove
        print(
            f"USER {request.state.user_info.username} with api_access: {request.state.user_info.api_access}",
        )
        return request.state.user_info

    if api_key:
        request.state.user_info = pat_core.validate_pat(api_key)
        return request.state.user_info

    # If no API key or oauth token user isn't authenticated.
    raise exceptions_bedrock.ApiException(
        status_code=HTTP_401_UNAUTHORIZED,
        internal=ExceptionCodeEnum.RestapiOidcNoAuthProvided,
    )
