import datetime
import secrets
import string

from azul_bedrock import datastore, exceptions_bedrock
from azul_bedrock.exception_enums import ExceptionCodeEnum
from azul_bedrock.models_auth import CredentialFormat, Credentials, UserInfo
from azul_bedrock.models_restapi import pat as azm_pat
from azul_bedrock.settings import get_opensearch as get_os_settings
from azul_security import admin, security
from fastapi import APIRouter, Depends, Request
from opensearchpy import exceptions as opensearchpy_exceptions
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN

from azul_restapi_server.security import pat_core

PASSWORD_ALPHABET = string.ascii_letters + string.digits
MAX_PATS_PER_REQUEST = 10000

router = APIRouter()

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
        "pat": {"type": "keyword"},
        "owner_username": {"type": "keyword"},
        "roles": {"type": "keyword"},
        "creation_date": {"type": "date"},
        "last_used_date": {"type": "date"},
    },
}


def generate_pat(pat_length: int = 64) -> str:
    """Generate a new Personal Access Token (PAT)."""
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _i in range(pat_length))


def _get_opensearch_session():
    """Get an Opensearch session."""
    return datastore.credentials_to_es(
        Credentials(
            unique=get_os_settings().opensearch_azul_security_username,
            format=CredentialFormat.basic,
            username=get_os_settings().opensearch_azul_security_username,
            password=get_os_settings().opensearch_azul_security_password,
        )
    )


def _create_azul_security_index():
    """Create the system level azul_security index."""
    index_name = get_os_settings().opensearch_azul_security_index
    template = {
        "settings": _template_settings,
        "mappings": _index_mapping,
        "index_patterns": [index_name],
    }
    try:
        # Create the Opensearch index
        session = _get_opensearch_session()
        session.indices.put_template(name=index_name, body=template, ignore=404)
        session.indices.put_mapping(index=index_name, body=template["mappings"], ignore=404)
        # session.indices.delete(index=index_name) # TODO - remove delete
        if not session.indices.exists(index=index_name):
            session.indices.create(index=index_name)
    except Exception as e:
        raise exceptions_bedrock.BaseAzulException(internal=ExceptionCodeEnum.TODO, parameters={"message": str(e)})


# TODO - this needs to move
_create_azul_security_index()


def get_user_creds(request: Request) -> UserInfo:
    try:
        user_info = request.state.user_info
        user_info_parsed = UserInfo.model_validate(user_info)
        return user_info_parsed
    except AttributeError as e:
        raise exceptions_bedrock.BaseAzulException(internal=ExceptionCodeEnum.TODO, parameters={"message": str(e)})


def _verify_user_is_admin(creds: UserInfo):
    """Verify a user is an admin and if they aren't raise a forbidden error."""
    if not admin.is_user_admin(creds):
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_403_FORBIDDEN,
            internal=ExceptionCodeEnum.RestapiAllowedPATAction,
            ref=f"user '{creds.username}' not superuser",
            parameters={"username": creds.username},
        )


@router.post(
    "/v0/authenticate/pat",
    response_model=azm_pat.PATIssue,
    responses={
        500: {
            "model": exceptions_bedrock.BaseError,
            "description": "Something went wrong",
        }
    },
)
async def create_pat(request_pat: azm_pat.PATRequest, creds: UserInfo = Depends(get_user_creds)):
    """Create a PAT for a user and store it in Opensearch."""
    _verify_user_is_admin(creds)
    # Verify the provided roles are valid for the current user to assign.
    allowed_roles = [r for r in creds.roles if r not in admin.get_settings().admin_roles]
    user_allowed_roles_string = ",".join(allowed_roles)

    # Verify user has access to provided roles (done first to avoid enumeration)
    for role in request_pat.roles:
        if role not in creds.roles:
            raise exceptions_bedrock.ApiException(
                status_code=HTTP_400_BAD_REQUEST,
                internal=ExceptionCodeEnum.TODO,
                parameters={
                    "message": f"You do not have the provided role '{role}' (it may not exist)."
                    + f" You can only give the PAT roles you have access to these are [{user_allowed_roles_string}]"
                },
            )

    # Verify PAT doesn't get admin roles
    if admin.is_admin_roles(request_pat.roles):
        admin_roles = ",".join([r for r in creds.roles if r in admin.get_settings().admin_roles])
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_400_BAD_REQUEST,
            internal=ExceptionCodeEnum.TODO,
            parameters={
                "message": f"Cannot provide a PAT with the administrator roles [{admin_roles}]."
                + f" You can only give the PAT roles you have access to these are [{user_allowed_roles_string}]"
            },
        )
    # Verify PAT has minimum required access
    # admin.get_settings().minimum_required_access
    # _required_access
    # sec.minimum_required_access

    # Generate PAT
    opensearch_access = _get_opensearch_session()
    generated_pat = generate_pat()

    # TODO - return pat and base64 with username PAT (bearer).
    resp = azm_pat.PATIssue(
        id=f"{request_pat.name}.{creds.username}",
        pat=generated_pat,
        pat_name=request_pat.name,
        roles=request_pat.roles,
        owner_username=creds.username,
        creation_date=datetime.datetime.now(tz=datetime.UTC),
        last_used_date=datetime.datetime.now(tz=datetime.UTC),
    )

    pat_user_info = pat_core.create_userinfo_for_pat(resp)
    opensearch_account_info = datastore.get_user_account(datastore.credentials_to_access(pat_user_info.credentials))
    sec = security.Security()
    found_groups = set(sec.safe_to_unsafe(opensearch_account_info.get("roles", []), drop_mismatch=True))
    missing_labels = sec.minimum_required_access.difference(found_groups)
    if len(missing_labels) > 0:
        missing_labels = ",".join(missing_labels)
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_400_BAD_REQUEST,
            internal=ExceptionCodeEnum.TODO,
            parameters={
                "message": f"Provided roles don't encompass the minimum required access missing [{missing_labels}]."
            },
        )

    body = {
        "pat_name": resp.pat_name,
        "pat": resp.pat,  # TODO encrypt password before storage!
        "roles": request_pat.roles,
        "owner_username": resp.owner_username,
        "creation_date": resp.creation_date,
        "last_used_date": resp.last_used_date,
    }
    if opensearch_access.exists(index=get_os_settings().opensearch_azul_security_index, id=resp.id):
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_400_BAD_REQUEST,
            internal=ExceptionCodeEnum.TODO,
            parameters={"message": f"PAT with id {resp.id} already exists in Opensearch."},
        )

    try:
        indexed_doc = opensearch_access.index(
            index=get_os_settings().opensearch_azul_security_index,
            body=body,
            id=resp.id,
            refresh=True,
        )
    except Exception as e:
        raise exceptions_bedrock.ApiException(
            status_code=500,
            internal=ExceptionCodeEnum.TODO,
            parameters={"message": f"Failed to create PAT with inner exception {str(e)}."},
        )
    if resp.id != indexed_doc.get("_id"):
        raise exceptions_bedrock.ApiException(
            status_code=500,
            internal=ExceptionCodeEnum.TODO,
            parameters={
                "message": f"The creation of the PAT did not result in the expected id, actual id {indexed_doc.get('_id')} != {resp.id} (expected)"
            },
        )

    return resp


@router.get(
    "/v0/authenticate/pat/list",
    response_model=azm_pat.ListOfPAT,
    responses={
        500: {
            "model": exceptions_bedrock.BaseError,
            "description": "Something went wrong",
        }
    },
)
async def list_pats(creds: UserInfo = Depends(get_user_creds)):
    """List the PATs currently stored in Azul."""
    _verify_user_is_admin(creds)
    os_session = _get_opensearch_session()
    current_pats = os_session.search(
        index=get_os_settings().opensearch_azul_security_index,
        body={
            "query": {"match_all": {}},
            "_source": {"excludes": "pat"},
            "size": MAX_PATS_PER_REQUEST,
        },
    )
    current_pats_selected: list[dict] = current_pats.get("hits", {}).get("hits", [])
    results: list[azm_pat.PATView] = []

    for p in current_pats_selected:
        id = p.get("_id")
        source = p.get("_source", {})
        source["id"] = id
        results.append(azm_pat.PATView.model_validate(source))
    warnings = ""
    if len(results) > MAX_PATS_PER_REQUEST:
        warnings = (
            f"There are over {MAX_PATS_PER_REQUEST} not all PATs have been returned please cleanup some old PATs."
        )
    return azm_pat.ListOfPAT(pats=results, warnings=warnings)


@router.delete(
    "/v0/authenticate/pat",
    response_model=azm_pat.PATDeleteResponse,
)
async def delete_pat(id: str, creds: UserInfo = Depends(get_user_creds)):
    """Delete a PAT from Azul."""
    _verify_user_is_admin(creds)
    opensearch_access = _get_opensearch_session()
    try:
        opensearch_access.delete(index=get_os_settings().opensearch_azul_security_index, id=id)
    except opensearchpy_exceptions.NotFoundError:
        return azm_pat.PATDeleteResponse(result=azm_pat.PATDeleteEnum.not_found)
    except Exception as e:
        raise exceptions_bedrock.ApiException(
            status_code=500,
            internal=ExceptionCodeEnum.TODO,
            parameters={"message": f"unexpected error {str(e)} occurred."},
        )

    return azm_pat.PATDeleteResponse(result=azm_pat.PATDeleteEnum.success)
