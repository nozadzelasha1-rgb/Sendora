import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_connector import get_session
from app.funcs.zone import Zone
from app.routers.dependencies import FORBIDDEN_DETAIL, get_current_user, require_roles
from app.schema.user import UserRead
from app.schema.zone import ZoneCreate, ZoneRead, ZoneUpdate
from app.utils.constant import ZONE_ADMIN_ROLE_IDS
from app.utils.exception import (
    InvalidZoneReferenceError,
    NoDataError,
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
        "Admin roles get every zone. Any other role gets only the zone assigned "
        "to it. Returns 404 when no zone is available."
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
        zones = await Zone(session).list_visible(
            current_user.role, current_user.zone_id
        )
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
