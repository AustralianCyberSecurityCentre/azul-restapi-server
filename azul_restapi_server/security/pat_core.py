"""Code to store and validate PAT tokens in opensearch."""

import base64
import datetime
from threading import RLock

import cachetools
import jwt
from azul_bedrock import datastore, exceptions_bedrock
from azul_bedrock.exception_enums import ExceptionCodeEnum
from azul_bedrock.models_auth import CredentialFormat, Credentials, UserInfo
from azul_bedrock.models_restapi import pat as azm_pat
from azul_bedrock.settings import get_opensearch as get_os_settings
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_500_INTERNAL_SERVER_ERROR

from azul_restapi_server import settings

PAT_CACHE_SIZE = 100
S_ANY = "s-any"


def _gen_opensearch_jwt(roles: list[str], user: str):
    """Generate a tests jwt token using a preshared secret."""
    roles.append(S_ANY)
    return jwt.encode(
        {
            "roles": roles,
            "sub": user,
            "iss": "https://localhost",
            "iat": datetime.datetime.now() - datetime.timedelta(hours=1, minutes=2),
            "nbf": datetime.datetime.now() - datetime.timedelta(hours=1, minutes=2),
            "exp": datetime.datetime.now() + datetime.timedelta(minutes=2, seconds=settings.oidc.pat_cache_ttl),
        },
        get_os_settings().jwt_signing_secret,
        algorithm="HS256",
    )


def create_userinfo_for_pat(pat_metadata: azm_pat.PATView) -> UserInfo:
    """Create a JWT from the provided PAT metadata."""
    pat_username = f"{pat_metadata.pat_name}_{pat_metadata.owner_username}"
    creds = Credentials(
        format=CredentialFormat.jwt,
        unique=pat_metadata.id,
        token=_gen_opensearch_jwt(pat_metadata.roles, pat_username),
    )

    return UserInfo(
        username=pat_username,
        org="unknown",
        roles=pat_metadata.roles,
        email=pat_metadata.owner_username,
        credentials=creds,
        decoded={"name": pat_username, "roles": pat_metadata.roles, "type": "pat"},
        unique_id=pat_metadata.id,
    )


def hash_pat(pat: str) -> str:
    """Hash a PAT with the recommended hasher for secure storage."""
    # Recommended hasher at time of writing
    password_hasher = PasswordHash(hashers=(Argon2Hasher(),))
    return password_hasher.hash(pat)


def validate_password_hash(pat: str, hashed_pat: str) -> bool:
    """Verify the provided password matches the PAT."""
    password_hasher = PasswordHash(hashers=(Argon2Hasher(),))
    return password_hasher.verify(pat, hashed_pat)


@cachetools.cached(cache=cachetools.TTLCache(maxsize=PAT_CACHE_SIZE, ttl=settings.oidc.pat_cache_ttl), lock=RLock())
def validate_pat(token: str) -> UserInfo:
    """Validate a PAT token and provide the associated user info."""
    try:
        decoded_bytes = base64.b64decode(token)
        decoded_str = decoded_bytes.decode()
        pat_id, pat_value = decoded_str.split(":", maxsplit=1)
    except Exception:
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_401_UNAUTHORIZED,
            internal=ExceptionCodeEnum.RestapiPatInvalidFormat,
        ) from None

    os_session = get_opensearch_pat_admin_session()
    response = os_session.get(index=get_os_settings().opensearch_azul_security_index, id=pat_id, ignore=[404])
    if not response.get("found", False):
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_401_UNAUTHORIZED,
            internal=ExceptionCodeEnum.RestapiPatExpiredOrInvalidPAT,
        )
    try:
        id = response.get("_id")
        source = response.get("_source", {})
        source["id"] = id
        source["ready_api_key"] = ""
        pat_issue = azm_pat.PATIssue.model_validate(source)
        pat_view = azm_pat.PATView.model_validate(source)
    except Exception as e:
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            internal=ExceptionCodeEnum.RestapiValidPATSerialisationFailure,
        ) from e
    if validate_password_hash(pat_value, pat_issue.pat):
        os_session.update(
            index=get_os_settings().opensearch_azul_security_index,
            id=pat_id,
            body={"doc": {"last_used_date": datetime.datetime.now(tz=datetime.UTC)}},
        )

        return create_userinfo_for_pat(pat_view)

    raise exceptions_bedrock.ApiException(
        status_code=HTTP_401_UNAUTHORIZED,
        internal=ExceptionCodeEnum.RestapiPatExpiredOrInvalidPAT,
    )


_template_settings = {
    "index.mapping.total_fields.limit": 2000,
    "number_of_shards": 1,
    "number_of_replicas": 2,
    "refresh_interval": "30s",
    "analysis": {
        "analyzer": {
            "path": {"tokenizer": "hierarchy"},
            "path_reversed": {"tokenizer": "hierarchy_reversed"},
            "pathw": {"tokenizer": "hierarchyw"},
            "pathw_reversed": {"tokenizer": "hierarchyw_reversed"},
            "alphanumeric": {"tokenizer": "alphanumeric"},
        },
        "tokenizer": {
            "hierarchy": {"type": "path_hierarchy", "delimiter": "/"},
            "hierarchy_reversed": {
                "type": "path_hierarchy",
                "delimiter": "/",
                "reverse": "true",
            },
            "hierarchyw": {"type": "path_hierarchy", "delimiter": "\\"},
            "hierarchyw_reversed": {
                "type": "path_hierarchy",
                "delimiter": "\\",
                "reverse": "true",
            },
            "alphanumeric": {
                "type": "char_group",
                "tokenize_on_chars": ["whitespace", "punctuation", "symbol"],
            },
        },
    },
}

_index_mapping = {
    "dynamic": "strict",
    "properties": {
        "pat_name": {"type": "keyword"},
        "description": {"type": "keyword"},
        "pat": {"type": "keyword"},
        "owner_username": {"type": "keyword"},
        "roles": {"type": "keyword"},
        "creation_date": {"type": "date"},
        "last_used_date": {"type": "date"},
    },
}


def get_opensearch_pat_admin_session():
    """Get an Opensearch session."""
    return datastore.credentials_to_es(
        Credentials(
            unique=get_os_settings().opensearch_azul_security_username,
            format=CredentialFormat.basic,
            username=get_os_settings().opensearch_azul_security_username,
            password=get_os_settings().opensearch_azul_security_password,
        )
    )


def create_azul_security_index():
    """Create the system level azul_security index."""
    index_name = get_os_settings().opensearch_azul_security_index
    template = {
        "settings": _template_settings,
        "mappings": _index_mapping,
        "index_patterns": [index_name],
    }
    try:
        # Create the Opensearch index if it doesn't exist
        session = get_opensearch_pat_admin_session()
        if not session.indices.exists(index=index_name):
            session.indices.put_template(name=index_name, body=template, ignore=404)
            session.indices.put_mapping(index=index_name, body=template["mappings"], ignore=404)
            session.indices.create(index=index_name)
    except Exception as e:
        raise exceptions_bedrock.BaseAzulException(
            internal=ExceptionCodeEnum.RestapiFailedToCreateSecurityIndex, parameters={"inner_exception": str(e)}
        ) from e
