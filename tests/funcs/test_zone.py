import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.zones import ZoneDB
from app.funcs.zone import Zone
from app.schema.zone import ZoneCreate, ZoneUpdate
from app.utils.constant import ADMIN_OPERATOR_ROLE_ID, SUPER_ADMIN_ROLE_ID
from app.utils.exception import (
    InvalidZoneReferenceError,
    NoDataError,
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


# --- list_visible ---------------------------------------------------------------


@pytest.mark.parametrize("admin_role", [SUPER_ADMIN_ROLE_ID, ADMIN_OPERATOR_ROLE_ID])
async def test_admin_role_sees_all_zones(
    session: AsyncSession, admin_role: int
) -> None:
    first = await _make(session, name="First")
    second = await _make(session, name="Second")

    zones = await Zone(session).list_visible(admin_role, None)

    assert {zone.id for zone in zones} == {first.id, second.id}


async def test_ordinary_role_sees_only_own_zone(session: AsyncSession) -> None:
    own = await _make(session, name="Own")
    await _make(session, name="Other")

    zones = await Zone(session).list_visible(ORDINARY_ROLE, own.id)

    assert [zone.id for zone in zones] == [own.id]


async def test_ordinary_role_without_zone_raises_no_data(session: AsyncSession) -> None:
    await _make(session)

    with pytest.raises(NoDataError):
        await Zone(session).list_visible(ORDINARY_ROLE, None)


async def test_ordinary_role_with_missing_zone_raises_no_data(
    session: AsyncSession,
) -> None:
    await _make(session)

    with pytest.raises(NoDataError):
        await Zone(session).list_visible(ORDINARY_ROLE, uuid.uuid4())


async def test_admin_with_no_zones_raises_no_data(session: AsyncSession) -> None:
    with pytest.raises(NoDataError):
        await Zone(session).list_visible(SUPER_ADMIN_ROLE_ID, None)
