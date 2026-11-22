from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.funcs.dictionary import Dictionary
from app.schema.dictionary import DictionaryItemCreate, DictionaryItemUpdate
from app.utils.constant import SUPER_ADMIN_ROLE_ID
from app.utils.exception import (
    DictionaryItemInUseError,
    DictionaryItemNotFoundError,
    DictionarySpecNotFoundError,
)
from tests.seed import TEST_ROLE_ID, TEST_SPEC_ID

OTHER_SPEC_ID = 9002
UNKNOWN_SPEC_ID = 999_999


@pytest_asyncio.fixture(autouse=True)
async def _advance_dictionary_sequence(
    session: AsyncSession,
) -> AsyncGenerator[None, None]:
    """Seed rows use explicit ids; move the identity past them so new rows do not collide."""
    await session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('dbo.dictionary', 'id'), 1000, true)"
        )
    )
    yield


async def _add_spec(session: AsyncSession, spec_id: int) -> None:
    await session.execute(
        text(
            "INSERT INTO dbo.dictionary_spec (id, name) OVERRIDING SYSTEM VALUE "
            "VALUES (:id, 'other_spec') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": spec_id},
    )
    await session.flush()


def _create(
    name: str = "New item", description: str | None = None
) -> DictionaryItemCreate:
    return DictionaryItemCreate(name=name, description=description)


async def test_list_specs_contains_seeded_spec(session: AsyncSession) -> None:
    specs = await Dictionary(session).list_specs()

    ids = [spec.id for spec in specs]
    assert TEST_SPEC_ID in ids
    assert ids == sorted(ids)


async def test_list_items_returns_items_of_the_spec(session: AsyncSession) -> None:
    items = await Dictionary(session).list_items(TEST_SPEC_ID)

    assert TEST_ROLE_ID in {item.id for item in items}
    assert all(item.spec_id == TEST_SPEC_ID for item in items)


async def test_list_items_of_unknown_spec_raises(session: AsyncSession) -> None:
    with pytest.raises(DictionarySpecNotFoundError):
        await Dictionary(session).list_items(UNKNOWN_SPEC_ID)


async def test_get_item_from_another_spec_raises_not_found(
    session: AsyncSession,
) -> None:
    await _add_spec(session, OTHER_SPEC_ID)

    with pytest.raises(DictionaryItemNotFoundError):
        await Dictionary(session).get_item(OTHER_SPEC_ID, TEST_ROLE_ID)


async def test_create_item_strips_name_and_drops_blank_description(
    session: AsyncSession,
) -> None:
    item = await Dictionary(session).create_item(
        TEST_SPEC_ID, _create(name="  Fresh  ", description="   ")
    )

    assert item.id is not None
    assert item.spec_id == TEST_SPEC_ID
    assert item.name == "Fresh"
    assert item.description is None


async def test_create_item_in_unknown_spec_raises(session: AsyncSession) -> None:
    with pytest.raises(DictionarySpecNotFoundError):
        await Dictionary(session).create_item(UNKNOWN_SPEC_ID, _create())


async def test_update_item_changes_only_sent_fields(session: AsyncSession) -> None:
    funcs = Dictionary(session)
    item = await funcs.create_item(TEST_SPEC_ID, _create(description="keep me"))

    updated = await funcs.update_item(
        TEST_SPEC_ID, item.id, DictionaryItemUpdate(name="Renamed")
    )

    assert updated.name == "Renamed"
    assert updated.description == "keep me"


async def test_update_missing_item_raises(session: AsyncSession) -> None:
    with pytest.raises(DictionaryItemNotFoundError):
        await Dictionary(session).update_item(
            TEST_SPEC_ID, UNKNOWN_SPEC_ID, DictionaryItemUpdate(name="x")
        )


async def test_delete_unused_item_removes_it(session: AsyncSession) -> None:
    funcs = Dictionary(session)
    item = await funcs.create_item(TEST_SPEC_ID, _create())

    await funcs.delete_item(TEST_SPEC_ID, item.id)

    with pytest.raises(DictionaryItemNotFoundError):
        await funcs.get_item(TEST_SPEC_ID, item.id)


async def test_delete_item_referenced_by_other_records_raises(
    session: AsyncSession,
) -> None:
    # The seeded organization points at TEST_ROLE_ID through its type column.
    with pytest.raises(DictionaryItemInUseError):
        await Dictionary(session).delete_item(TEST_SPEC_ID, TEST_ROLE_ID)


async def test_delete_protected_item_raises(session: AsyncSession) -> None:
    with pytest.raises(DictionaryItemInUseError):
        await Dictionary(session).delete_item(TEST_SPEC_ID, SUPER_ADMIN_ROLE_ID)


async def test_delete_missing_item_raises(session: AsyncSession) -> None:
    with pytest.raises(DictionaryItemNotFoundError):
        await Dictionary(session).delete_item(TEST_SPEC_ID, UNKNOWN_SPEC_ID)
