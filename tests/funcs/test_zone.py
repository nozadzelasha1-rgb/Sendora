import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.users.user import UserDB
from app.db_entities.zones import ZoneDB, ZoneUserDB
from app.funcs.user import User
from app.funcs.zone import Zone
from app.schema.user import UserCreate
from app.schema.zone import ZoneCreate, ZoneUpdate
from app.utils.constant import ADMIN_OPERATOR_ROLE_ID, SUPER_ADMIN_ROLE_ID
from app.utils.exception import (
    InvalidZoneReferenceError,
    MembershipAlreadyExistsError,
    MembershipNotFoundError,
    NoDataError,
    UserNotFoundError,
    ZoneNotFoundError,
)
from tests.seed import TEST_ROLE_ID

UNKNOWN_REFERENCE = 987654
ORDINARY_ROLE = TEST_ROLE_ID


async def _make(
    session: AsyncSession, name: str = "Central", **extra: object
) -> ZoneDB:
    payload: dict[str, object] = {
        "name": name,
        "city": "Tbilisi",
        "status": TEST_ROLE_ID,
        **extra,
    }
    return await Zone(session).create(ZoneCreate.model_validate(payload))


# --- create ---------------------------------------------------------------------


async def test_create_persists_zone(session: AsyncSession) -> None:
    zone = await _make(
        session, boundary={"type": "Polygon"}, assignment_rule=TEST_ROLE_ID
    )

    assert isinstance(zone.id, uuid.UUID)
    assert zone.name == "Central"
    assert zone.city == "Tbilisi"
    assert zone.boundary == {"type": "Polygon"}
    assert zone.assignment_rule == TEST_ROLE_ID
    assert zone.status == TEST_ROLE_ID


async def test_create_unknown_status_raises(session: AsyncSession) -> None:
    with pytest.raises(InvalidZoneReferenceError):
        await Zone(session).create(
            ZoneCreate(name="Central", city="Tbilisi", status=UNKNOWN_REFERENCE)
        )


async def test_session_usable_after_failed_create(session: AsyncSession) -> None:
    with pytest.raises(InvalidZoneReferenceError):
        await Zone(session).create(
            ZoneCreate(name="Central", city="Tbilisi", status=UNKNOWN_REFERENCE)
        )

    zone = await _make(session, name="After failure")

    assert zone.name == "After failure"


# --- get ------------------------------------------------------------------------


async def test_get_returns_zone(session: AsyncSession) -> None:
    created = await _make(session)

    fetched = await Zone(session).get(created.id)

    assert fetched.id == created.id


async def test_get_missing_raises(session: AsyncSession) -> None:
    with pytest.raises(ZoneNotFoundError):
        await Zone(session).get(uuid.uuid4())


# --- update ---------------------------------------------------------------------


async def test_update_changes_only_sent_fields(session: AsyncSession) -> None:
    zone = await _make(session)

    updated = await Zone(session).update(zone.id, ZoneUpdate(name="Renamed"))

    assert updated.name == "Renamed"
    assert updated.city == "Tbilisi"
    assert updated.status == TEST_ROLE_ID


async def test_update_unknown_status_raises(session: AsyncSession) -> None:
    zone = await _make(session)

    with pytest.raises(InvalidZoneReferenceError):
        await Zone(session).update(zone.id, ZoneUpdate(status=UNKNOWN_REFERENCE))


async def test_update_missing_raises(session: AsyncSession) -> None:
    with pytest.raises(ZoneNotFoundError):
        await Zone(session).update(uuid.uuid4(), ZoneUpdate(name="Renamed"))


# --- membership and list_visible -------------------------------------------------


async def _user(session: AsyncSession) -> UserDB:
    return await User(session).create(
        UserCreate(
            name=f"zone-{uuid.uuid4().hex[:8]}",
            password="password-123",
            role=ORDINARY_ROLE,
        )
    )


async def _join(session: AsyncSession, zone_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await Zone(session).add_user(zone_id, user_id)


@pytest.mark.parametrize("admin_role", [SUPER_ADMIN_ROLE_ID, ADMIN_OPERATOR_ROLE_ID])
async def test_admin_role_sees_all_zones(
    session: AsyncSession, admin_role: int
) -> None:
    first = await _make(session, name="First")
    second = await _make(session, name="Second")

    zones = await Zone(session).list_visible(admin_role, uuid.uuid4())

    assert {zone.id for zone in zones} == {first.id, second.id}


async def test_ordinary_role_sees_only_member_zones(session: AsyncSession) -> None:
    own = await _make(session, name="Own")
    await _make(session, name="Other")
    user = await _user(session)
    await _join(session, own.id, user.id)

    zones = await Zone(session).list_visible(ORDINARY_ROLE, user.id)

    assert [zone.id for zone in zones] == [own.id]


async def test_ordinary_role_in_several_zones_sees_all_of_them(
    session: AsyncSession,
) -> None:
    first = await _make(session, name="First")
    second = await _make(session, name="Second")
    await _make(session, name="Other")
    user = await _user(session)
    await _join(session, first.id, user.id)
    await _join(session, second.id, user.id)

    zones = await Zone(session).list_visible(ORDINARY_ROLE, user.id)

    assert {zone.id for zone in zones} == {first.id, second.id}


async def test_ordinary_role_without_membership_raises_no_data(
    session: AsyncSession,
) -> None:
    await _make(session)
    user = await _user(session)

    with pytest.raises(NoDataError):
        await Zone(session).list_visible(ORDINARY_ROLE, user.id)


async def test_admin_with_no_zones_raises_no_data(session: AsyncSession) -> None:
    with pytest.raises(NoDataError):
        await Zone(session).list_visible(SUPER_ADMIN_ROLE_ID, uuid.uuid4())


async def test_add_user_creates_membership(session: AsyncSession) -> None:
    zone = await _make(session)
    user = await _user(session)

    await Zone(session).add_user(zone.id, user.id)

    result = await session.execute(
        select(ZoneUserDB).where(
            ZoneUserDB.zone_id == zone.id, ZoneUserDB.user_id == user.id
        )
    )
    assert result.scalar_one() is not None


async def test_add_user_twice_raises_already_exists(session: AsyncSession) -> None:
    zone = await _make(session)
    user = await _user(session)
    await Zone(session).add_user(zone.id, user.id)

    with pytest.raises(MembershipAlreadyExistsError):
        await Zone(session).add_user(zone.id, user.id)


async def test_add_user_to_missing_zone_raises(session: AsyncSession) -> None:
    user = await _user(session)

    with pytest.raises(ZoneNotFoundError):
        await Zone(session).add_user(uuid.uuid4(), user.id)


async def test_add_missing_or_inactive_user_raises(session: AsyncSession) -> None:
    zone = await _make(session)
    with pytest.raises(UserNotFoundError):
        await Zone(session).add_user(zone.id, uuid.uuid4())

    user = await _user(session)
    user.active = False
    await session.flush()
    with pytest.raises(UserNotFoundError):
        await Zone(session).add_user(zone.id, user.id)


async def test_remove_user_deletes_membership(session: AsyncSession) -> None:
    zone = await _make(session)
    user = await _user(session)
    await Zone(session).add_user(zone.id, user.id)

    await Zone(session).remove_user(zone.id, user.id)

    result = await session.execute(
        select(ZoneUserDB).where(
            ZoneUserDB.zone_id == zone.id, ZoneUserDB.user_id == user.id
        )
    )
    assert result.scalars().all() == []


async def test_remove_user_that_is_not_member_raises(session: AsyncSession) -> None:
    zone = await _make(session)
    user = await _user(session)

    with pytest.raises(MembershipNotFoundError):
        await Zone(session).remove_user(zone.id, user.id)


async def test_deleting_user_removes_zone_memberships(session: AsyncSession) -> None:
    zone = await _make(session)
    user = await _user(session)
    await Zone(session).add_user(zone.id, user.id)

    await User(session).delete(user.id)

    result = await session.execute(
        select(ZoneUserDB).where(ZoneUserDB.user_id == user.id)
    )
    assert result.scalars().all() == []
