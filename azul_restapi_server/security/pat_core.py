"""Code to store and validate PAT tokens in opensearch."""

import base64
import datetime
from threading import RLock

import cachetools
from azul_bedrock import datastore, exceptions_bedrock
from azul_bedrock.exception_enums import ExceptionCodeEnum
from azul_bedrock.models_auth import CredentialFormat, Credentials, UserInfo
from azul_bedrock.models_restapi import pat as azm_pat
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_500_INTERNAL_SERVER_ERROR

from azul_restapi_server import settings
from azul_restapi_server.api.v1.pat_api import _get_opensearch_session, get_os_settings

PAT_CACHE_SIZE = 100


import jwt
from azul_metastore.encoders import base_encoder

# This pre-shared secret matches the provided docker-compose Opensearch cluster for local testing.
_SECRET = "secret.secret.secret.secret.secret.secret."


def _gen_opensearch_jwt(roles: list[str], user: str):
    """Generate a tests jwt token using a preshared secret."""
    roles.append(base_encoder.S_ANY)
    return jwt.encode(
        {
            "roles": roles,
            "sub": user,
            "iss": "https://localhost",
            "iat": datetime.datetime.now() - datetime.timedelta(hours=1, minutes=2),
            "nbf": datetime.datetime.now() - datetime.timedelta(hours=1, minutes=2),
            "exp": datetime.datetime.now() + datetime.timedelta(hours=1, minutes=2),
        },
        _SECRET,
        algorithm="HS256",
    )


def create_userinfo_for_pat(pat_metadata: azm_pat.PATView) -> UserInfo:
    """Create a JWT from the provided PAT metadata."""
    creds = Credentials(
        format=CredentialFormat.jwt,
        unique=pat_metadata.id,
        token=_gen_opensearch_jwt(pat_metadata.roles, pat_metadata.pat_name),
    )

    return UserInfo(
        username=pat_metadata.pat_name,
        org="unknown",
        roles=pat_metadata.roles,
        email=pat_metadata.owner_username,
        credentials=creds,
        decoded={"name": pat_metadata.pat_name, "roles": pat_metadata.roles, "type": "pat"},
        unique_id=pat_metadata.id,
    )


@cachetools.cached(cache=cachetools.TTLCache(maxsize=PAT_CACHE_SIZE, ttl=settings.oidc.pat_cache_ttl), lock=RLock())
def validate_pat(token: str) -> UserInfo:
    """Validate a PAT token and provide the associated user info."""
    decoded_bytes = base64.b64decode(token)
    decoded_str = decoded_bytes.decode()
    pat_name, pat_value = decoded_str.split(":", maxsplit=1)

    os_session = _get_opensearch_session()
    response = os_session.search(
        index=get_os_settings().opensearch_azul_security_index,
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"pat_name": pat_name}},
                        {"term": {"pat": pat_value}},
                    ]
                }
            },
        },
    )
    if response.get("hits", {}).get("total", {}).get("value", 0) != 1:
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_401_UNAUTHORIZED,
            internal=ExceptionCodeEnum.TODO,
            parameters={"message": "The provided PAT is invalid or expired."},
        )

    try:
        hit_value = response.get("hits").get("hits")[0]
        id = hit_value.get("_id")
        source = hit_value.get("_source", {})
        source["id"] = id
        pat_metadata = azm_pat.PATView.model_validate(source)
    except Exception:
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            internal=ExceptionCodeEnum.TODO,
            parameters={"message": "PAT was authorised but is missing expected data in the databased."},
        ) from None

    return create_userinfo_for_pat(pat_metadata)
