"""OIDC flow authentication."""

from azul_bedrock.models_auth import UserInfo
from fastapi import Depends, Request
from fastapi.security import OpenIdConnect

from azul_restapi_server import settings

from . import oidc_shared

_authorization_code_flow = OpenIdConnect(
    openIdConnectUrl=settings.oidc.discovery_url,
    auto_error=True,
)


def validate_token(request: Request, token: str = Depends(_authorization_code_flow)) -> UserInfo:
    """Validate the input token.

    The dependency here only parses the token out of the http request.
    It describes to swagger how oidc is needed.
    It does not perform validation.
    """
    request.state.user_info = oidc_shared.validate(token.split(" ")[-1], settings.oidc.client_id)
    return request.state.user_info
