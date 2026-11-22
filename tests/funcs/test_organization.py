import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.organizations import OrganizationDB, OrganizationUserDB
from app.db_entities.users.user import UserDB
from app.funcs.organization import Organization
from app.funcs.user import User
from app.schema.organization import OrganizationCreate, OrganizationUpdate
from app.schema.user import UserCreate
from app.utils.exception import (
    InvalidOrganizationTypeError,
    MembershipAlreadyExistsError,
    MembershipNotFoundError,
    OrganizationNotFoundError,
    UserNotFoundError,
)
from tests.seed import TEST_ROLE_ID

UNKNOWN_TYPE = 987654


async def _make(
    session: AsyncSession,
    name: str = "Acme",
    **extra: object,
) -> OrganizationDB:
    payload: dict[str, object] = {"name": name, "type": TEST_ROLE_ID, **extra}
    return await Organization(session).create(
        OrganizationCreate.model_validate(payload)
    )


# --- create ---------------------------------------------------------------------


async def test_create_persists_organization(session: AsyncSession) -> None:
    org = await _make(session, delivery_fee_gel="4.50")

    assert isinstance(org.id, uuid.UUID)
    assert org.name == "Acme"
    assert org.type == TEST_ROLE_ID
    assert org.delivery_fee_gel == Decimal("4.50")
    assert org.active is True


async def test_create_unknown_type_raises(session: AsyncSession) -> None:
    with pytest.raises(InvalidOrganizationTypeError):
        await Organization(session).create(
            OrganizationCreate(name="Acme", type=UNKNOWN_TYPE)
        )


async def test_session_usable_after_failed_create(session: AsyncSession) -> None:
    with pytest.raises(InvalidOrganizationTypeError):
        await Organization(session).create(
            OrganizationCreate(name="Acme", type=UNKNOWN_TYPE)
        )

    org = await _make(session, name="After failure")

    assert org.name == "After failure"


# --- get ------------------------------------------------------------------------


async def test_get_returns_organization(session: AsyncSession) -> None:
    org = await _make(session)

    found = await Organization(session).get(org.id)

    assert found.id == org.id


async def test_get_missing_raises(session: AsyncSession) -> None:
    with pytest.raises(OrganizationNotFoundError):
        await Organization(session).get(uuid.uuid4())


async def test_get_returns_inactive_organization(session: AsyncSession) -> None:
    org = await _make(session)
    await Organization(session).delete(org.id)

    found = await Organization(session).get(org.id)

    assert found.active is False


# --- list -----------------------------------------------------------------------


async def test_list_orders_by_name_then_id(session: AsyncSession) -> None:
    funcs = Organization(session)
    b = await _make(session, name="zz-list-b")
    a = await _make(session, name="zz-list-a")
    c = await _make(session, name="zz-list-c")

    items = await funcs.list(limit=100, offset=0)

    ours = [o.id for o in items if o.name.startswith("zz-list-")]
    assert ours == [a.id, b.id, c.id]


async def test_list_limit_and_offset(session: AsyncSession) -> None:
    funcs = Organization(session)
    # Names sort after every pre-existing row that starts with a lower letter.
    for suffix in ("a", "b", "c"):
        await _make(session, name=f"zzzz-page-{suffix}")

    all_items = await funcs.list(limit=100, offset=0)
    index = next(i for i, o in enumerate(all_items) if o.name == "zzzz-page-a")

    page = await funcs.list(limit=2, offset=index)
    assert [o.name for o in page] == ["zzzz-page-a", "zzzz-page-b"]

    page = await funcs.list(limit=2, offset=index + 1)
    assert [o.name for o in page] == ["zzzz-page-b", "zzzz-page-c"]


async def test_list_active_filter(session: AsyncSession) -> None:
    funcs = Organization(session)
    kept = await _make(session, name="zz-active-kept")
    removed = await _make(session, name="zz-active-removed")
    await funcs.delete(removed.id)

    active_ids = {o.id for o in await funcs.list(limit=100, offset=0, active=True)}
    inactive_ids = {o.id for o in await funcs.list(limit=100, offset=0, active=False)}

    assert kept.id in active_ids
    assert removed.id not in active_ids
    assert removed.id in inactive_ids
    assert kept.id not in inactive_ids


# --- update ---------------------------------------------------------------------


async def test_update_changes_only_sent_fields(session: AsyncSession) -> None:
    org = await _make(session, delivery_fee_gel="4.50")

    updated = await Organization(session).update(
        org.id, OrganizationUpdate(name="Renamed")
    )

    assert updated.name == "Renamed"
    assert updated.delivery_fee_gel == Decimal("4.50")
    assert updated.type == TEST_ROLE_ID
    assert updated.active is True


async def test_update_can_clear_nullable_field(session: AsyncSession) -> None:
    org = await _make(session, delivery_fee_gel="4.50")

    updated = await Organization(session).update(
        org.id, OrganizationUpdate.model_validate({"delivery_fee_gel": None})
    )

    assert updated.delivery_fee_gel is None


async def test_update_can_reactivate(session: AsyncSession) -> None:
    funcs = Organization(session)
    org = await _make(session)
    await funcs.delete(org.id)

    updated = await funcs.update(org.id, OrganizationUpdate(active=True))

    assert updated.active is True


async def test_update_unknown_type_raises(session: AsyncSession) -> None:
    org = await _make(session)

    with pytest.raises(InvalidOrganizationTypeError):
        await Organization(session).update(
            org.id, OrganizationUpdate(type=UNKNOWN_TYPE)
        )


async def test_update_missing_raises(session: AsyncSession) -> None:
    with pytest.raises(OrganizationNotFoundError):
        await Organization(session).update(
            uuid.uuid4(), OrganizationUpdate(name="Nobody")
        )


# --- delete ---------------------------------------------------------------------


async def test_delete_is_soft(session: AsyncSession) -> None:
    funcs = Organization(session)
    org_id = (await _make(session)).id

    await funcs.delete(org_id)

    session.expire_all()
    row = await session.get(OrganizationDB, org_id)
    assert row is not None
    assert row.active is False


async def test_delete_twice_is_a_noop(session: AsyncSession) -> None:
    funcs = Organization(session)
    org = await _make(session)

    await funcs.delete(org.id)
    await funcs.delete(org.id)

    assert (await funcs.get(org.id)).active is False


async def test_delete_missing_raises(session: AsyncSession) -> None:
    with pytest.raises(OrganizationNotFoundError):
        await Organization(session).delete(uuid.uuid4())


# --- membership -----------------------------------------------------------------


async def _user(session: AsyncSession) -> UserDB:
    return await User(session).create(
        UserCreate(
            name=f"member-{uuid.uuid4().hex[:8]}",
            password="password-123",
            role=TEST_ROLE_ID,
        )
    )


async def _membership_count(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    result = await session.execute(
        select(OrganizationUserDB).where(
            OrganizationUserDB.organization_id == org_id,
            OrganizationUserDB.user_id == user_id,
        )
    )
    return len(result.scalars().all())


async def test_add_user_creates_membership(session: AsyncSession) -> None:
    org = await _make(session)
    user = await _user(session)

    await Organization(session).add_user(org.id, user.id)

    assert await _membership_count(session, org.id, user.id) == 1


async def test_add_user_twice_raises_already_exists(session: AsyncSession) -> None:
    org = await _make(session)
    user = await _user(session)
    await Organization(session).add_user(org.id, user.id)

    with pytest.raises(MembershipAlreadyExistsError):
        await Organization(session).add_user(org.id, user.id)


async def test_add_user_to_missing_organization_raises(session: AsyncSession) -> None:
    user = await _user(session)

    with pytest.raises(OrganizationNotFoundError):
        await Organization(session).add_user(uuid.uuid4(), user.id)


async def test_add_missing_user_raises(session: AsyncSession) -> None:
    org = await _make(session)

    with pytest.raises(UserNotFoundError):
        await Organization(session).add_user(org.id, uuid.uuid4())


async def test_add_inactive_user_raises(session: AsyncSession) -> None:
    org = await _make(session)
    user = await _user(session)
    user.active = False
    await session.flush()

    with pytest.raises(UserNotFoundError):
        await Organization(session).add_user(org.id, user.id)


async def test_remove_user_deletes_membership(session: AsyncSession) -> None:
    org = await _make(session)
    user = await _user(session)
    await Organization(session).add_user(org.id, user.id)

    await Organization(session).remove_user(org.id, user.id)

    assert await _membership_count(session, org.id, user.id) == 0


async def test_remove_user_that_is_not_member_raises(session: AsyncSession) -> None:
    org = await _make(session)
    user = await _user(session)

    with pytest.raises(MembershipNotFoundError):
        await Organization(session).remove_user(org.id, user.id)


async def test_deleting_user_removes_memberships(session: AsyncSession) -> None:
    org = await _make(session)
    user = await _user(session)
    await Organization(session).add_user(org.id, user.id)

    await User(session).delete(user.id)

    assert await _membership_count(session, org.id, user.id) == 0
