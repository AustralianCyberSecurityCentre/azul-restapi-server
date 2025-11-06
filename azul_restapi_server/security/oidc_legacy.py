"""OIDC flow authentication.

This uses legacy method of swagger authentication.
"""

from azul_bedrock.models_auth import UserInfo
from fastapi import Depends, Request
from fastapi.security import OAuth2AuthorizationCodeBearer

from azul_restapi_server import settings

from . import oidc_shared

# triggers http request on import - bad - makes testing hard
_discovered_config = oidc_shared.discover_auth_server(settings.oidc.discovery_url)
_authorization_code_flow = OAuth2AuthorizationCodeBearer(
    tokenUrl=_discovered_config["token_endpoint"],
    authorizationUrl=_discovered_config["authorization_endpoint"],
    refreshUrl=_discovered_config["token_endpoint"],
    scopes={k: "" for k in settings.oidc.scopes.split(" ")},
    auto_error=True,
)


def validate_token(request: Request, token: str = Depends(_authorization_code_flow)) -> UserInfo:
    """Validate the input token.

    The dependency here only parses the token out of the http request.
    It describes to swagger how oauth2 is needed. We do the oidc parsing ourselves.
    It does not perform validation.
    """
    request.state.user_info = oidc_shared.validate(token.split(" ")[-1], settings.oidc.client_id)
    return request.state.user_info
