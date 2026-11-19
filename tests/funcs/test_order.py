import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.orders import OrderDB, OrderOperationDB
from app.db_entities.users.user import UserDB
from app.funcs.order import Order, OrderDetail, OrderFilter
from app.schema.order import (
    OperationUpsert,
    OrderCreate,
    OrderUpdate,
    StatusChangeCreate,
)
from app.schema.user import UserRead
from app.utils.constant import (
    ADMIN_OPERATOR_ROLE_ID,
    ORDER_STATUS_CANCELLED_ID,
    ORDER_STATUS_CREATED_ID,
    SUPER_ADMIN_ROLE_ID,
)
from app.utils.exception import (
    InvalidOrderReferenceError,
    OrderForbiddenError,
    OrderNotFoundError,
)
from tests.seed import TEST_ORG_ID, TEST_ROLE_ID

OTHER_ORG_ID = uuid.UUID("00000000-0000-4000-8000-00000000a002")
ORDINARY_ROLE = TEST_ROLE_ID


async def _make_org(session: AsyncSession, org_id: uuid.UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO dbo.organizations (id, name, type) "
            "VALUES (:id, 'other_org', :type_id) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": org_id, "type_id": TEST_ROLE_ID},
    )


async def _user(
    session: AsyncSession,
    *,
    role: int = ORDINARY_ROLE,
    organization_id: uuid.UUID = TEST_ORG_ID,
    phone: str | None = None,
) -> UserRead:
    user = UserDB(
        id=uuid.uuid4(),
        name=f"user-{uuid.uuid4().hex[:8]}",
        role=role,
        organization_id=organization_id,
        active=True,
        phone=phone,
    )
    session.add(user)
    await session.flush()
    return UserRead.model_validate(user, from_attributes=True)


def _payload(**overrides: Any) -> OrderCreate:
    data: dict[str, Any] = {
        "service_type": TEST_ROLE_ID,
        "sender": {
            "sender_company": "Shop",
            "sender_contact": "Anna",
            "sender_phone": "+79990000001",
        },
        "recipient": {
            "recipient_name": "Boris",
            "recipient_phone": "+79990000002",
            "delivery_address": "Rustaveli 1",
            "city": "Tbilisi",
        },
        "parcel": {"parcel_type": TEST_ROLE_ID},
        "payment": {
            "delivery_payer": TEST_ROLE_ID,
            "delivery_fee_gel": "10.00",
            "currency": TEST_ROLE_ID,
        },
        **overrides,
    }
    return OrderCreate.model_validate(data)


async def _create(
    session: AsyncSession, user: UserRead, **overrides: Any
) -> OrderDetail:
    return await Order(session).create(_payload(**overrides), user)


# --- create ---------------------------------------------------------------------


async def test_create_writes_all_blocks_and_first_status(session: AsyncSession) -> None:
    user = await _user(session)
    detail = await _create(session, user, external_order_id="ext-1")

    assert detail.order.status == ORDER_STATUS_CREATED_ID
    assert detail.order.partner_id == TEST_ORG_ID
    assert detail.order.tracking_number.startswith("SND")
    assert detail.sender is not None
    assert detail.recipient is not None
    assert detail.parcel is not None
    assert detail.schedule is not None
    assert detail.payment is not None
    assert len(detail.history) == 1
    assert detail.history[0].status == ORDER_STATUS_CREATED_ID


async def test_create_links_recipient_to_user_with_same_phone(
    session: AsyncSession,
) -> None:
    recipient = await _user(session, phone="+79990000002")
    sender = await _user(session)
    detail = await _create(session, sender)

    assert detail.recipient is not None
    assert detail.recipient.user_id == recipient.id


async def test_create_non_admin_with_foreign_partner_raises(
    session: AsyncSession,
) -> None:
    user = await _user(session)
    await _make_org(session, OTHER_ORG_ID)
    with pytest.raises(OrderForbiddenError):
        await _create(session, user, partner_id=OTHER_ORG_ID)


async def test_create_admin_requires_partner_id(session: AsyncSession) -> None:
    admin = await _user(session, role=SUPER_ADMIN_ROLE_ID)
    with pytest.raises(InvalidOrderReferenceError):
        await _create(session, admin)


async def test_create_unknown_reference_raises_and_persists_nothing(
    session: AsyncSession,
) -> None:
    user = await _user(session)
    unknown_service = 987654
    with pytest.raises(InvalidOrderReferenceError):
        await _create(
            session, user, external_order_id="rolled-back", service_type=unknown_service
        )
    result = await session.execute(
        text("SELECT count(*) FROM dbo.orders WHERE external_order_id = 'rolled-back'")
    )
    assert result.scalar_one() == 0


# --- reads and visibility ----------------------------------------------------------


async def test_sender_organization_sees_its_order(session: AsyncSession) -> None:
    user = await _user(session)
    detail = await _create(session, user)
    same_org = await _user(session)
    fetched = await Order(session).get(detail.order.id, same_org)
    assert fetched.order.id == detail.order.id


async def test_unrelated_user_gets_not_found(session: AsyncSession) -> None:
    detail = await _create(session, await _user(session))
    await _make_org(session, OTHER_ORG_ID)
    stranger = await _user(session, organization_id=OTHER_ORG_ID)
    with pytest.raises(OrderNotFoundError):
        await Order(session).get(detail.order.id, stranger)


async def test_recipient_manager_and_courier_see_the_order(
    session: AsyncSession,
) -> None:
    recipient = await _user(session, phone="+79990000002")
    detail = await _create(session, await _user(session))
    manager = await _user(session)
    courier = await _user(session)
    await Order(session).upsert_operation(
        detail.order.id,
        OperationUpsert(manager_id=manager.id),
        await _user(session, role=SUPER_ADMIN_ROLE_ID),
    )
    detail.order.courier_id = courier.id
    await session.commit()

    for viewer in (recipient, manager, courier):
        fetched = await Order(session).get(detail.order.id, viewer)
        assert fetched.order.id == detail.order.id


async def test_admin_sees_every_order(session: AsyncSession) -> None:
    await _create(session, await _user(session))
    await _create(session, await _user(session))
    admin = await _user(session, role=ADMIN_OPERATOR_ROLE_ID)
    rows, total = await Order(session).list(admin, 50, 0, OrderFilter())
    assert total >= 2
    assert len(rows) == total


async def test_list_for_sender_is_limited_to_own_organization(
    session: AsyncSession,
) -> None:
    await _make_org(session, OTHER_ORG_ID)
    own = await _user(session)
    await _create(session, own)
    await _create(session, own)
    await _create(session, await _user(session, organization_id=OTHER_ORG_ID))
    rows, total = await Order(session).list(own, 50, 0, OrderFilter())
    assert total == 2
    assert all(row[0].partner_id == TEST_ORG_ID for row in rows)


async def test_list_pagination_and_empty_page_total(session: AsyncSession) -> None:
    user = await _user(session)
    for _ in range(3):
        await _create(session, user)
    service = Order(session)
    page, total = await service.list(user, 2, 0, OrderFilter())
    assert len(page) == 2
    assert total >= 3
    empty, empty_total = await service.list(user, 2, 1000, OrderFilter())
    assert empty == []
    assert empty_total == total


async def test_list_filters_by_manager(session: AsyncSession) -> None:
    admin = await _user(session, role=SUPER_ADMIN_ROLE_ID)
    manager = await _user(session)
    user = await _user(session)
    assigned = await _create(session, user)
    await _create(session, user)
    await Order(session).upsert_operation(
        assigned.order.id, OperationUpsert(manager_id=manager.id), admin
    )
    rows, total = await Order(session).list(
        admin, 50, 0, OrderFilter(manager_id=manager.id)
    )
    assert total == 1
    assert rows[0][0].id == assigned.order.id


# --- update ----------------------------------------------------------------------


async def test_sender_can_update_while_created(session: AsyncSession) -> None:
    user = await _user(session)
    detail = await _create(session, user)
    updated = await Order(session).update(
        detail.order.id, OrderUpdate(tracking_url="https://example.test/t"), user
    )
    assert updated.order.tracking_url == "https://example.test/t"


async def test_sender_cannot_update_after_status_changed(session: AsyncSession) -> None:
    user = await _user(session)
    detail = await _create(session, user)
    admin = await _user(session, role=SUPER_ADMIN_ROLE_ID)
    await Order(session).add_status(
        detail.order.id, StatusChangeCreate(status=ORDER_STATUS_CANCELLED_ID), admin
    )
    with pytest.raises(OrderForbiddenError):
        await Order(session).update(
            detail.order.id, OrderUpdate(tracking_url="https://example.test/x"), user
        )


async def test_update_recipient_block_relinks_by_phone_when_user_id_missing(
    session: AsyncSession,
) -> None:
    new_recipient = await _user(session, phone="+79990000099")
    user = await _user(session)
    detail = await _create(session, user)
    recipient_block: dict[str, Any] = {
        "recipient_name": "Clara",
        "recipient_phone": "+79990000099",
        "delivery_address": "Pekini 5",
        "city": "Tbilisi",
    }
    updated = await Order(session).update(
        detail.order.id,
        OrderUpdate.model_validate({"recipient": recipient_block}),
        user,
    )
    assert updated.recipient is not None
    assert updated.recipient.user_id == new_recipient.id


async def test_update_missing_order_raises(session: AsyncSession) -> None:
    user = await _user(session, role=SUPER_ADMIN_ROLE_ID)
    with pytest.raises(OrderNotFoundError):
        await Order(session).update(
            999_999_999, OrderUpdate(tracking_url="https://example.test/none"), user
        )


# --- operation -------------------------------------------------------------------


async def test_non_manager_cannot_set_operation(session: AsyncSession) -> None:
    user = await _user(session)
    detail = await _create(session, user)
    with pytest.raises(OrderForbiddenError):
        await Order(session).upsert_operation(
            detail.order.id, OperationUpsert(route_id="R1"), user
        )


async def test_manager_cannot_reassign_order(session: AsyncSession) -> None:
    admin = await _user(session, role=SUPER_ADMIN_ROLE_ID)
    manager = await _user(session)
    other = await _user(session)
    detail = await _create(session, await _user(session))
    await Order(session).upsert_operation(
        detail.order.id, OperationUpsert(manager_id=manager.id), admin
    )
    with pytest.raises(OrderForbiddenError):
        await Order(session).upsert_operation(
            detail.order.id, OperationUpsert(manager_id=other.id), manager
        )


async def test_manager_updates_operation_fields(session: AsyncSession) -> None:
    admin = await _user(session, role=SUPER_ADMIN_ROLE_ID)
    manager = await _user(session)
    detail = await _create(session, await _user(session))
    await Order(session).upsert_operation(
        detail.order.id, OperationUpsert(manager_id=manager.id), admin
    )
    operation = await Order(session).upsert_operation(
        detail.order.id, OperationUpsert(route_id="R7"), manager
    )
    assert operation.route_id == "R7"
    assert operation.manager_id == manager.id


# --- status and cancel -----------------------------------------------------------


async def test_courier_adds_status_and_order_status_changes(
    session: AsyncSession,
) -> None:
    courier = await _user(session)
    detail = await _create(session, await _user(session))
    detail.order.courier_id = courier.id
    await session.commit()

    history = await Order(session).add_status(
        detail.order.id,
        StatusChangeCreate(status=TEST_ROLE_ID, comment="on the way"),
        courier,
    )
    assert history.changed_by == courier.id
    refreshed = await Order(session).get(detail.order.id, courier)
    assert refreshed.order.status == TEST_ROLE_ID


async def test_sender_cannot_add_status(session: AsyncSession) -> None:
    user = await _user(session)
    detail = await _create(session, user)
    with pytest.raises(OrderForbiddenError):
        await Order(session).add_status(
            detail.order.id, StatusChangeCreate(status=TEST_ROLE_ID), user
        )


async def test_cancel_is_soft_and_idempotent(session: AsyncSession) -> None:
    admin = await _user(session, role=SUPER_ADMIN_ROLE_ID)
    detail = await _create(session, await _user(session))
    service = Order(session)
    await service.cancel(detail.order.id, admin)
    await service.cancel(detail.order.id, admin)
    refreshed = await service.get(detail.order.id, admin)
    assert refreshed.order.status == ORDER_STATUS_CANCELLED_ID
    cancelled_rows = [
        h for h in refreshed.history if h.status == ORDER_STATUS_CANCELLED_ID
    ]
    assert len(cancelled_rows) == 1


async def test_sender_cannot_assign_courier(session: AsyncSession) -> None:
    user = await _user(session)
    detail = await _create(session, user)
    courier = await _user(session)
    with pytest.raises(OrderForbiddenError):
        await Order(session).update(
            detail.order.id, OrderUpdate(courier_id=courier.id), user
        )


async def test_cancel_by_non_admin_raises(session: AsyncSession) -> None:
    user = await _user(session)
    detail = await _create(session, user)
    with pytest.raises(OrderForbiddenError):
        await Order(session).cancel(detail.order.id, user)


# --- models sanity ---------------------------------------------------------------


async def test_operation_model_is_loaded_for_detail(session: AsyncSession) -> None:
    admin = await _user(session, role=SUPER_ADMIN_ROLE_ID)
    detail = await _create(session, await _user(session))
    await Order(session).upsert_operation(
        detail.order.id, OperationUpsert(carrier_id="C1"), admin
    )
    refreshed = await Order(session).get(detail.order.id, admin)
    assert isinstance(refreshed.operation, OrderOperationDB)
    assert isinstance(refreshed.order, OrderDB)
    assert refreshed.operation.carrier_id == "C1"
