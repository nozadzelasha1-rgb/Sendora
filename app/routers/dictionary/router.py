from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_connector import get_session
from app.funcs.dictionary import Dictionary
from app.routers.dependencies import FORBIDDEN_DETAIL, get_current_user, require_roles
from app.schema.dictionary import (
    DictionaryItemCreate,
    DictionaryItemRead,
    DictionaryItemUpdate,
    DictionarySpecRead,
)
from app.utils.constant import DICTIONARY_ADMIN_ROLE_IDS
from app.utils.exception import (
    DictionaryItemInUseError,
    DictionaryItemNotFoundError,
    DictionarySpecNotFoundError,
)

_AUTHENTICATED = [Depends(get_current_user)]
_ADMIN_ONLY = [Depends(require_roles(DICTIONARY_ADMIN_ROLE_IDS))]

router = APIRouter(
    prefix="/dictionaries",
    tags=["Dictionary"],
)

_SPEC_NOT_FOUND_DETAIL = "Dictionary spec not found"
_ITEM_NOT_FOUND_DETAIL = "Dictionary item not found"
_UNAUTHORIZED_RESPONSE = {
    "description": "Invalid or expired authentication credentials"
}
_FORBIDDEN_RESPONSE = {"description": FORBIDDEN_DETAIL}
_SPEC_NOT_FOUND_RESPONSE = {"description": _SPEC_NOT_FOUND_DETAIL}
_ITEM_NOT_FOUND_RESPONSE = {"description": _ITEM_NOT_FOUND_DETAIL}
_IN_USE_RESPONSE = {
    "description": "The item is referenced by other records or is protected"
}


@router.get(
    "",
    response_model=list[DictionarySpecRead],
    status_code=status.HTTP_200_OK,
    summary="List dictionary specs",
    description="Return every dictionary spec. Any authenticated user may read.",
    dependencies=_AUTHENTICATED,
    responses={status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE},
)
async def list_specs(
    session: AsyncSession = Depends(get_session),
) -> list[DictionarySpecRead]:
    specs = await Dictionary(session).list_specs()
    return [DictionarySpecRead.model_validate(spec) for spec in specs]


@router.get(
    "/{spec_id}",
    response_model=list[DictionaryItemRead],
    status_code=status.HTTP_200_OK,
    summary="List the items of a dictionary spec",
    description="Return the items of one spec ordered by id. Any authenticated user may read.",
    dependencies=_AUTHENTICATED,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_404_NOT_FOUND: _SPEC_NOT_FOUND_RESPONSE,
    },
)
async def list_items(
    spec_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[DictionaryItemRead]:
    try:
        items = await Dictionary(session).list_items(spec_id)
    except DictionarySpecNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_SPEC_NOT_FOUND_DETAIL
        )
    return [DictionaryItemRead.model_validate(item) for item in items]


@router.get(
    "/{spec_id}/{item_id}",
    response_model=DictionaryItemRead,
    status_code=status.HTTP_200_OK,
    summary="Get a dictionary item",
    description="Return one item of a spec. Any authenticated user may read.",
    dependencies=_AUTHENTICATED,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_404_NOT_FOUND: _ITEM_NOT_FOUND_RESPONSE,
    },
)
async def get_item(
    spec_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_session),
) -> DictionaryItemRead:
    try:
        item = await Dictionary(session).get_item(spec_id, item_id)
    except DictionarySpecNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_SPEC_NOT_FOUND_DETAIL
        )
    except DictionaryItemNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_ITEM_NOT_FOUND_DETAIL
        )
    return DictionaryItemRead.model_validate(item)


@router.post(
    "/{spec_id}",
    response_model=DictionaryItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an item to a dictionary spec",
    description="Add an item to a spec. Requires a Bearer token of an admin role.",
    dependencies=_ADMIN_ONLY,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: _SPEC_NOT_FOUND_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def create_item(
    spec_id: int,
    data: DictionaryItemCreate,
    session: AsyncSession = Depends(get_session),
) -> DictionaryItemRead:
    try:
        item = await Dictionary(session).create_item(spec_id, data)
    except DictionarySpecNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_SPEC_NOT_FOUND_DETAIL
        )
    return DictionaryItemRead.model_validate(item)


@router.patch(
    "/{spec_id}/{item_id}",
    response_model=DictionaryItemRead,
    status_code=status.HTTP_200_OK,
    summary="Update a dictionary item",
    description=(
        "Partially update an item: only the sent fields change. "
        "Requires a Bearer token of an admin role."
    ),
    dependencies=_ADMIN_ONLY,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: _ITEM_NOT_FOUND_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Validation error"},
    },
)
async def update_item(
    spec_id: int,
    item_id: int,
    data: DictionaryItemUpdate,
    session: AsyncSession = Depends(get_session),
) -> DictionaryItemRead:
    try:
        item = await Dictionary(session).update_item(spec_id, item_id, data)
    except DictionarySpecNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_SPEC_NOT_FOUND_DETAIL
        )
    except DictionaryItemNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_ITEM_NOT_FOUND_DETAIL
        )
    return DictionaryItemRead.model_validate(item)


@router.delete(
    "/{spec_id}/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dictionary item",
    description=(
        "Delete an item. Items still used by other records and protected items "
        "return 409. Requires a Bearer token of an admin role."
    ),
    dependencies=_ADMIN_ONLY,
    responses={
        status.HTTP_401_UNAUTHORIZED: _UNAUTHORIZED_RESPONSE,
        status.HTTP_403_FORBIDDEN: _FORBIDDEN_RESPONSE,
        status.HTTP_404_NOT_FOUND: _ITEM_NOT_FOUND_RESPONSE,
        status.HTTP_409_CONFLICT: _IN_USE_RESPONSE,
    },
)
async def delete_item(
    spec_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await Dictionary(session).delete_item(spec_id, item_id)
    except DictionarySpecNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_SPEC_NOT_FOUND_DETAIL
        )
    except DictionaryItemNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_ITEM_NOT_FOUND_DETAIL
        )
    except DictionaryItemInUseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
