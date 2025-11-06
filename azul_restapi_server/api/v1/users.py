"""User based API routes."""

import copy

from azul_bedrock.exceptions import BaseError
from azul_bedrock.models_auth import UserInfo
from fastapi import APIRouter, Request

router = APIRouter()


@router.get(
    "/v0/users/me",
    response_model=UserInfo,
    responses={500: {"model": BaseError, "description": "Something went wrong"}},
)
async def read_users_me(request: Request):
    """Return parsed info for for current user."""
    user_info: UserInfo = copy.deepcopy(request.state.user_info)
    # do not send back user credentials
    user_info.credentials = None

    return user_info
