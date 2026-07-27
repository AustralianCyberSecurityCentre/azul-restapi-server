"""API for PAT creation and deletion."""

import base64
import datetime
import secrets
import string

from azul_bedrock import datastore, exceptions_bedrock
from azul_bedrock.exception_enums import ExceptionCodeEnum
from azul_bedrock.models_auth import UserInfo
from azul_bedrock.models_restapi import pat as azm_pat
from azul_bedrock.settings import get_opensearch as get_os_settings
from azul_security import admin, security
from fastapi import APIRouter, Depends, Request
from opensearchpy import exceptions as opensearchpy_exceptions
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN

from azul_restapi_server.security import pat_core

MAX_PATS_PER_REQUEST = 10000
PASSWORD_ALPHABET = string.ascii_letters + string.digits


def generate_pat(pat_length: int = 64) -> str:
    """Generate a new Personal Access Token (PAT)."""
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _i in range(pat_length))


router = APIRouter()


def get_user_creds(request: Request) -> UserInfo:
    """Get user credentials for API call."""
    try:
        user_info = request.state.user_info
        user_info_parsed = UserInfo.model_validate(user_info)
        return user_info_parsed
    except AttributeError as e:
        raise exceptions_bedrock.BaseAzulException(
            internal=ExceptionCodeEnum.RestapiFailedToGetUserCredentials,
            parameters={
                "inner_exception": str(e),
            },
        ) from e


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
    """Create a PAT for a user and store it in Opensearch.

    To use the PAT put the ready_api_key in a header {"X-API-Key": <ready-api-key>}
    The ready api key is a base64 encoding of the "pat_id:pat_value"
    e.g: base64.b64encode(<pat-id>:<pat>)
    """
    _verify_user_is_admin(creds)
    # Verify the provided roles are valid for the current user to assign.
    allowed_roles = [r for r in creds.roles if r not in admin.get_settings().admin_roles]
    user_allowed_roles_string = ",".join(allowed_roles)

    # Verify user has access to provided roles (done first to avoid enumeration)
    for role in request_pat.roles:
        if role not in creds.roles:
            raise exceptions_bedrock.ApiException(
                status_code=HTTP_400_BAD_REQUEST,
                internal=ExceptionCodeEnum.RestapiCreatePatUserDoesntHaveRolesToAssignToPAT,
                parameters={"role": role, "user_allowed_roles_string": user_allowed_roles_string},
            )

    # Verify PAT doesn't get admin roles
    if admin.is_admin_roles(request_pat.roles):
        admin_roles = ",".join([r for r in creds.roles if r in admin.get_settings().admin_roles])
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_400_BAD_REQUEST,
            internal=ExceptionCodeEnum.RestapiCreatePatCantGetAdminResults,
            parameters={"admin_roles": admin_roles, "user_allowed_roles_string": user_allowed_roles_string},
        )
    # Generate PAT
    generated_pat = generate_pat()

    resp = azm_pat.PATIssue(
        id=generate_pat(20),  # using a mini-pat as a random temporary id before opensearch issues one.
        pat=generated_pat,
        ready_api_key="",
        pat_name=request_pat.name,
        description=request_pat.description,
        roles=request_pat.roles,
        owner_username=creds.username,
        creation_date=datetime.datetime.now(tz=datetime.UTC),
        last_used_date=datetime.datetime.now(tz=datetime.UTC),
    )

    # Verify the PAT has the minimum required access for Opensearch.
    pat_user_info = pat_core.create_userinfo_for_pat(resp)
    if pat_user_info.credentials is None:
        raise TypeError("Expected pat_user_info.credentials to be Credentials, got None")
    opensearch_account_info = datastore.get_user_account(datastore.credentials_to_access(pat_user_info.credentials))
    sec = security.Security()
    found_groups = set(sec.safe_to_unsafe(opensearch_account_info.get("roles", []), drop_mismatch=True))
    missing_labels = sec.minimum_required_access.difference(found_groups)
    if len(missing_labels) > 0:
        missing_labels = ",".join(missing_labels)
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_400_BAD_REQUEST,
            internal=ExceptionCodeEnum.RestapiCreatePatDoesntHaveMinimumRequiredAccess,
            parameters={"missing_labels": missing_labels},
        )

    opensearch_access = pat_core.get_opensearch_pat_admin_session()
    # check if user already has a pat with the provided name
    already_exists_response = opensearch_access.search(
        index=get_os_settings().opensearch_azul_security_index,
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"pat_name": resp.pat_name}},
                        {"term": {"owner_username": resp.owner_username}},
                    ]
                }
            },
        },
    )
    if already_exists_response.get("hits", {}).get("total", {}).get("value", 1) != 0:
        raise exceptions_bedrock.ApiException(
            status_code=HTTP_400_BAD_REQUEST,
            internal=ExceptionCodeEnum.RestapiCreatePatAlreadyExists,
            parameters={"pat_name": resp.pat_name},
        )

    body = {
        # no id, allow opensearch to generate it.
        "pat_name": resp.pat_name,
        "description": resp.description,
        "pat": pat_core.hash_pat(resp.pat),
        "roles": request_pat.roles,
        "owner_username": resp.owner_username,
        "creation_date": resp.creation_date,
        "last_used_date": resp.last_used_date,
    }

    try:
        indexed_doc = opensearch_access.index(
            index=get_os_settings().opensearch_azul_security_index,
            body=body,
            refresh=True,
        )
    except Exception as e:
        raise exceptions_bedrock.ApiException(
            status_code=500,
            internal=ExceptionCodeEnum.RestapiCreatePatFailedToStorePAT,
            parameters={"inner_exception": str(e)},
        ) from e

    if not indexed_doc.get("_id"):
        raise exceptions_bedrock.ApiException(
            status_code=500,
            internal=ExceptionCodeEnum.RestapiCreatePatCreatedPATMissingId,
        )
    resp.id = indexed_doc.get("_id")
    ready_api_key = base64.b64encode(f"{resp.id}:{generated_pat}".encode())
    resp.ready_api_key = ready_api_key.decode()
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
    os_session = pat_core.get_opensearch_pat_admin_session()
    current_pats = os_session.search(
        index=get_os_settings().opensearch_azul_security_index,
        body={
            "query": {"match_all": {}},
            "_source": {"excludes": "pat"},
            "size": MAX_PATS_PER_REQUEST,
        },
        ignore=[404],
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
    opensearch_access = pat_core.get_opensearch_pat_admin_session()
    try:
        opensearch_access.delete(index=get_os_settings().opensearch_azul_security_index, id=id)
    except opensearchpy_exceptions.NotFoundError:
        return azm_pat.PATDeleteResponse(result=azm_pat.PATDeleteEnum.not_found)
    except Exception as e:
        raise exceptions_bedrock.ApiException(
            status_code=500,
            internal=ExceptionCodeEnum.RestapiDeletePATUnexpected,
            parameters={"inner_exception": str(e)},
        ) from e

    return azm_pat.PATDeleteResponse(result=azm_pat.PATDeleteEnum.success)
