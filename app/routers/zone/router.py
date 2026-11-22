import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_connector import get_session
from app.funcs.zone import Zone
from app.routers.dependencies import FORBIDDEN_DETAIL, get_current_user, require_roles
from app.schema.user import UserRead
from app.schema.zone import (
    ZoneCreate,
    ZoneMemberCreate,
    ZoneMemberRead,
    ZoneRead,
    ZoneUpdate,
)
from app.utils.constant import ZONE_ADMIN_ROLE_IDS
from app.utils.exception import (
    InvalidZoneReferenceError,
    MembershipAlreadyExistsError,
    MembershipNotFoundError,
    NoDataError,
    UserNotFoundError,
    ZoneNotFoundError,
)

_ADMIN_ONLY = [Depends(require_roles(ZONE_ADMIN_ROLE_IDS))]

router = APIRouter(
    prefix="/zones",
    tags=["Zone"],
)

_NOT_FOUND_DETAIL = "Zone not found"
_UNKNOWN_REFERENCE_DETAIL = "Unknown status, assignment rule or manager"
_NO_DATA_DETAIL = "No zones available"
_UNAUTHORIZED_RESPONSE = {
    "description": "Invalid or expired authentication credentials"
}
_FORBIDDEN_RESPONSE = {"description": FORBIDDEN_DETAIL}
_NOT_FOUND_RESPONSE = {"description": _NOT_FOUND_DETAIL}
_USER_NOT_FOUND_DETAIL = "User not found"
_NOT_A_MEMBER_DETAIL = "User is not a member of the zone"
_ALREADY_MEMBER_DETAIL = "User is already a member of the zone"


@router.post(
    "",
    response_model=ZoneRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a zone",
    description="Create a zone. Requires a Bearer token of an admin role.",
    dependencies=_ADMIN_ONLY,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error or unknown status, rule or manager"
        },
    },
)
async def create_zone(
    data: ZoneCreate,
    session: AsyncSession = Depends(get_session),
) -> ZoneRead:
    try:
        zone = await Zone(session).create(data)
    except InvalidZoneReferenceError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_UNKNOWN_REFERENCE_DETAIL,
        )
    return ZoneRead.model_validate(zone)


@router.get(
    "",
    response_model=list[ZoneRead],
    status_code=status.HTTP_200_OK,
    summary="List zones visible to the user",
    description=(
        "Admin roles get every zone. Any other role gets only the zones it is a "
        "member of. Returns 404 when no zone is available."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_404_NOT_FOUND: {"description": _NO_DATA_DETAIL},
    },
)
async def list_zones(
    current_user: UserRead = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ZoneRead]:
    try:
        zones = await Zone(session).list_visible(current_user.role, current_user.id)
    except NoDataError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NO_DATA_DETAIL,
        )
    return [ZoneRead.model_validate(zone) for zone in zones]


@router.get(
    "/{zone_id}",
    response_model=ZoneRead,
    status_code=status.HTTP_200_OK,
    summary="Get a zone",
    description="Return a zone by id. Requires a Bearer token of an admin role.",
    dependencies=_ADMIN_ONLY,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def get_zone(
    zone_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ZoneRead:
    try:
        zone = await Zone(session).get(zone_id)
    except ZoneNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_DETAIL,
        )
    return ZoneRead.model_validate(zone)


@router.patch(
    "/{zone_id}",
    response_model=ZoneRead,
    status_code=status.HTTP_200_OK,
    summary="Update a zone",
    description=(
        "Partially update the zone: only the sent fields change. "
        "Requires a Bearer token of an admin role."
    ),
    dependencies=_ADMIN_ONLY,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error or unknown status, rule or manager"
        },
    },
)
async def update_zone(
    zone_id: uuid.UUID,
    data: ZoneUpdate,
    session: AsyncSession = Depends(get_session),
) -> ZoneRead:
    try:
        zone = await Zone(session).update(zone_id, data)
    except ZoneNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_DETAIL,
        )
    except InvalidZoneReferenceError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_UNKNOWN_REFERENCE_DETAIL,
        )
    return ZoneRead.model_validate(zone)


@router.post(
    "/{zone_id}/users",
    response_model=ZoneMemberRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a user to a zone",
    description="Make an active user a member of the zone. Requires an admin role.",
    dependencies=_ADMIN_ONLY,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: {
            "description": f"{_NOT_FOUND_DETAIL} or {_USER_NOT_FOUND_DETAIL}"
        },
        status.HTTP_409_CONFLICT: {"description": _ALREADY_MEMBER_DETAIL},
    },
)
async def add_zone_user(
    zone_id: uuid.UUID,
    data: ZoneMemberCreate,
    session: AsyncSession = Depends(get_session),
) -> ZoneMemberRead:
    try:
        await Zone(session).add_user(zone_id, data.user_id)
    except ZoneNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_DETAIL,
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_USER_NOT_FOUND_DETAIL,
        )
    except MembershipAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_ALREADY_MEMBER_DETAIL,
        )
    return ZoneMemberRead(zone_id=zone_id, user_id=data.user_id)


@router.delete(
    "/{zone_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a user from a zone",
    dependencies=_ADMIN_ONLY,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: {"description": _NOT_A_MEMBER_DETAIL},
    },
)
async def remove_zone_user(
    zone_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await Zone(session).remove_user(zone_id, user_id)
    except MembershipNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_A_MEMBER_DETAIL,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
