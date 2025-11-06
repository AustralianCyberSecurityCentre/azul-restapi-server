"""Provides common functionality for handling OIDC auth."""

import logging
from threading import RLock
from typing import Dict

import cachetools
import httpx
from azul_bedrock.models_auth import Credentials, UserInfo
from fastapi import HTTPException
from jose import exceptions as jwt_exceptions
from jose import jwt
from starlette.status import HTTP_401_UNAUTHORIZED

from azul_restapi_server import settings

logger = logging.getLogger(__name__)
# retry getting auth
client = httpx.Client(
    mounts={
        "https://": httpx.HTTPTransport(retries=3),
        "http://": httpx.HTTPTransport(retries=3),
    },
    timeout=5.0,
)


def claims_to_user(claims: dict) -> UserInfo:
    """Map oauth claims to object.

    Map standard OIDC claims, as well as custom claims specified in the ENV,
    into a User object for use within the server
    """
    if claims.get("azpacr", "0") != "0":
        # azpacr is a string, but is only ever set to 0, 1, or 2
        # non-zero indicates the request was from a confidential or daemon application
        # "preferred_username" key will not be present, therefore set username to application-id from `azp` field
        username = claims["azp"]
    else:
        # azpacr == 0 indicates the request was made by a public client (e.g. Azul web app)
        # or not using azure oidc
        username = claims[settings.oidc.username_key]
    unique_id = claims.get("sub", None)
    if not unique_id:
        raise Exception("Unable to determine a valid unique identifier for user.")
    return UserInfo(
        username=username,
        org=claims.get("org", "unknown"),
        email=claims.get("email", ""),
        roles=[g.lstrip("/") for g in claims.get(settings.oidc.roles_key, [])],
        decoded=claims,
        unique_id=unique_id,
    )


@cachetools.cached(
    cache=cachetools.TTLCache(maxsize=1, ttl=settings.oidc.cache_ttl), key=lambda d: d["jwks_uri"], lock=RLock()
)
def _get_jwks(openid_config: Dict):
    """Get the public keys used by IdP for signing."""
    resp = client.get(openid_config["jwks_uri"])
    try:
        keys = resp.json()
    except ValueError as e:
        raise Exception("unable to retrieve signing keys from IdP") from e
    return keys


@cachetools.cached(cache=cachetools.TTLCache(maxsize=1, ttl=settings.oidc.cache_ttl), lock=RLock())
def discover_auth_server(discovery_url: str) -> Dict:
    """Get auth details from well-known config."""
    resp = client.get(discovery_url)
    try:
        json = resp.json()
    except ValueError as e:
        raise Exception("unable to discover IdP auth server details") from e
    return json


def validate(token: str, audience: str) -> UserInfo:
    """Check that the supplied token is currently valid."""
    oidc_config = discover_auth_server(settings.oidc.discovery_url)
    keys = _get_jwks(oidc_config)

    try:
        claims = jwt.decode(
            token,
            keys,
            audience=audience,
            algorithms=oidc_config["id_token_signing_alg_values_supported"],
            issuer=oidc_config["issuer"],
            # We use the ID Token, not Auth token, so don't verify Auth Token.
            options={"verify_at_hash": False},
        )
        if claims.get("sub", None) is None:
            raise jwt_exceptions.JWTClaimsError("JWT does not have a subject and is therefore invalid.")
    except (jwt_exceptions.ExpiredSignatureError, jwt_exceptions.JWTError, jwt_exceptions.JWTClaimsError) as e:
        logger.error(f"Not authenticated, bad jwt for ({audience}): {str(e)}")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Not authenticated, bad jwt",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_info = claims_to_user(claims)
    user_info.credentials = Credentials(unique=user_info.unique_id, format="oauth", token=token)
    return user_info
