"""Perform no authentication.

This is insecure.
"""

from azul_bedrock.models_auth import Credentials, UserInfo
from fastapi import Depends, Request

from . import oidc_shared


def validate_token(request: Request, token: str = Depends(lambda: None)) -> UserInfo:
    """Ignore input and return static token."""
    request.state.user_info = oidc_shared.claims_to_user(
        {
            "exp": -1,
            "token_type": "Bearer",  # nosec B105
            "preferred_username": "anony-moose",
            "org": "testing",
            "roles": ["validated"],
            "sub": "anony-moose",
        }
    )
    request.state.user_info.credentials = Credentials(format="none", unique="anony-moose")
    return request.state.user_info
