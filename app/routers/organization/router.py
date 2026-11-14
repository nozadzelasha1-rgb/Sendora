import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_connector import get_session
from app.funcs.organization import (
    InvalidOrganizationTypeError,
    Organization,
    OrganizationNotFoundError,
)
from app.routers.dependencies import FORBIDDEN_DETAIL, require_roles
from app.schema.organization import (
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)
from app.utils.constant import ADMIN_OPERATOR_ROLE_ID, SUPER_ADMIN_ROLE_ID

ORGANIZATION_ALLOWED_ROLE_IDS = (SUPER_ADMIN_ROLE_ID, ADMIN_OPERATOR_ROLE_ID)

router = APIRouter(
    prefix="/organizations",
    tags=["Organization"],
    dependencies=[Depends(require_roles(ORGANIZATION_ALLOWED_ROLE_IDS))],
    responses={status.HTTP_403_FORBIDDEN: {"description": FORBIDDEN_DETAIL}},
)

_NOT_FOUND_DETAIL = "Organization not found"
_UNKNOWN_TYPE_DETAIL = "Unknown organization type"
_UNAUTHORIZED_RESPONSE = {
    "description": "Invalid or expired authentication credentials"
}
_NOT_FOUND_RESPONSE = {"description": _NOT_FOUND_DETAIL}


@router.post(
    "",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
    description=(
        "Create an organization. Requires a Bearer access token of an allowed role."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error or unknown organization type"
        },
    },
)
async def create_organization(
    data: OrganizationCreate,
    session: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    try:
        organization = await Organization(session).create(data)
    except InvalidOrganizationTypeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_UNKNOWN_TYPE_DETAIL,
        )
    return OrganizationRead.model_validate(organization)


@router.get(
    "",
    response_model=list[OrganizationRead],
    status_code=status.HTTP_200_OK,
    summary="List organizations",
    description=(
        "Return a page of organizations ordered by name. Only active "
        "organizations are returned unless active=false is passed."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def list_organizations(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    active: bool = True,
    session: AsyncSession = Depends(get_session),
) -> list[OrganizationRead]:
    organizations = await Organization(session).list(limit, offset, active)
    return [OrganizationRead.model_validate(item) for item in organizations]


@router.get(
    "/{organization_id}",
    response_model=OrganizationRead,
    status_code=status.HTTP_200_OK,
    summary="Get an organization",
    description="Return the organization by id, including inactive ones.",
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def get_organization(
    organization_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    try:
        organization = await Organization(session).get(organization_id)
    except OrganizationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_DETAIL,
        )
    return OrganizationRead.model_validate(organization)


@router.patch(
    "/{organization_id}",
    response_model=OrganizationRead,
    status_code=status.HTTP_200_OK,
    summary="Update an organization",
    description=(
        "Partially update the organization: only the sent fields change. "
        "Send active=true to reactivate a deleted organization."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Validation error or unknown organization type"
        },
    },
)
async def update_organization(
    organization_id: uuid.UUID,
    data: OrganizationUpdate,
    session: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    try:
        organization = await Organization(session).update(organization_id, data)
    except OrganizationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_DETAIL,
        )
    except InvalidOrganizationTypeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_UNKNOWN_TYPE_DETAIL,
        )
    return OrganizationRead.model_validate(organization)


@router.delete(
    "/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an organization",
    description=(
        "Soft-delete the organization (sets active=false). Repeating the "
        "request for an existing organization still returns 204."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def delete_organization(
    organization_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await Organization(session).delete(organization_id)
    except OrganizationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_NOT_FOUND_DETAIL,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
