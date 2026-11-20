import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import ColumnElement, Row, Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.orders import (
    OrderDB,
    OrderOperationDB,
    OrderParcelDB,
    OrderPaymentDB,
    OrderRecipientDB,
    OrderScheduleDB,
    OrderSenderDB,
    OrderStatusHistoryDB,
)
from app.db_entities.users.user import UserDB
from app.schema.order import (
    OperationUpsert,
    OrderCreate,
    OrderUpdate,
    StatusChangeCreate,
)
from app.schema.user import UserRead
from app.utils.constant import (
    ORDER_ADMIN_ROLE_IDS,
    ORDER_STATUS_CANCELLED_ID,
    ORDER_STATUS_CREATED_ID,
)
from app.utils.exception import (
    InvalidOrderReferenceError,
    OrderConflictError,
    OrderForbiddenError,
    OrderNotFoundError,
)
from app.utils.tracking import generate_tracking_number

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
_SQLSTATE_UNIQUE_VIOLATION = "23505"
_TRACKING_CONSTRAINT_MARKER = "tracking_number"
_TRACKING_ATTEMPTS = 3
_CANCEL_COMMENT = "Cancelled"

_T = TypeVar("_T")


class _TrackingNumberConflictError(Exception):
    """Internal: the generated tracking number is taken; the caller retries."""


@dataclass(frozen=True)
class OrderFilter:
    """Optional list filters; None means the filter is not applied."""

    status: int | None = None
    zone_id: uuid.UUID | None = None
    partner_id: uuid.UUID | None = None
    courier_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


@dataclass(frozen=True)
class OrderDetail:
    """One order with all its blocks and status history."""

    order: OrderDB
    sender: OrderSenderDB | None
    recipient: OrderRecipientDB | None
    parcel: OrderParcelDB | None
    schedule: OrderScheduleDB | None
    payment: OrderPaymentDB | None
    operation: OrderOperationDB | None
    history: Sequence[OrderStatusHistoryDB]


def _translate(exc: IntegrityError) -> Exception | None:
    """Map a database integrity error to a domain error; None when it is not mapped."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == _SQLSTATE_FOREIGN_KEY_VIOLATION:
        return InvalidOrderReferenceError("Unknown order reference")
    if sqlstate == _SQLSTATE_UNIQUE_VIOLATION:
        if _TRACKING_CONSTRAINT_MARKER in str(exc.orig):
            return _TrackingNumberConflictError()
        return OrderConflictError("Order with this external_order_id already exists")
    return None


class Order:
    """Business logic for orders. Visibility and write rules live here, not in routers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- roles and visibility ---------------------------------------------------

    @staticmethod
    def is_admin(user: UserRead) -> bool:
        return user.role in ORDER_ADMIN_ROLE_IDS

    @staticmethod
    def is_manager(detail: OrderDetail, user: UserRead) -> bool:
        return detail.operation is not None and detail.operation.manager_id == user.id

    @staticmethod
    def is_courier(detail: OrderDetail, user: UserRead) -> bool:
        return detail.order.courier_id == user.id

    @classmethod
    def is_privileged(cls, detail: OrderDetail, user: UserRead) -> bool:
        """True for admins and the order's manager: they see the internal operation fields."""
        return cls.is_admin(user) or cls.is_manager(detail, user)

    @staticmethod
    def _visible_to(user: UserRead) -> ColumnElement[bool]:
        """Non-admin visibility: own organization as sender, assigned manager, courier or recipient."""
        return or_(
            OrderDB.partner_id == user.organization_id,
            OrderOperationDB.manager_id == user.id,
            OrderDB.courier_id == user.id,
            OrderRecipientDB.user_id == user.id,
        )

    # --- reads ------------------------------------------------------------------

    async def get(self, order_id: int, user: UserRead) -> OrderDetail:
        """Return the full order in one query for all blocks, plus one for the history."""
        query = (
            select(
                OrderDB,
                OrderSenderDB,
                OrderRecipientDB,
                OrderParcelDB,
                OrderScheduleDB,
                OrderPaymentDB,
                OrderOperationDB,
            )
            .select_from(OrderDB)
            .outerjoin(OrderSenderDB, OrderSenderDB.order_id == OrderDB.id)
            .outerjoin(OrderRecipientDB, OrderRecipientDB.order_id == OrderDB.id)
            .outerjoin(OrderParcelDB, OrderParcelDB.order_id == OrderDB.id)
            .outerjoin(OrderScheduleDB, OrderScheduleDB.order_id == OrderDB.id)
            .outerjoin(OrderPaymentDB, OrderPaymentDB.order_id == OrderDB.id)
            .outerjoin(OrderOperationDB, OrderOperationDB.order_id == OrderDB.id)
            .where(OrderDB.id == order_id)
        )
        if not self.is_admin(user):
            query = query.where(self._visible_to(user))
        row = (await self.session.execute(query)).one_or_none()
        if row is None:
            raise OrderNotFoundError("Order not found")
        order, sender, recipient, parcel, schedule, payment, operation = row
        history = await self._history(order_id)
        return OrderDetail(
            order=order,
            sender=sender,
            recipient=recipient,
            parcel=parcel,
            schedule=schedule,
            payment=payment,
            operation=operation,
            history=history,
        )

    async def _history(self, order_id: int) -> Sequence[OrderStatusHistoryDB]:
        result = await self.session.execute(
            select(OrderStatusHistoryDB)
            .where(OrderStatusHistoryDB.order_id == order_id)
            .order_by(OrderStatusHistoryDB.created_at, OrderStatusHistoryDB.id)
        )
        return result.scalars().all()

    def _filtered(self, user: UserRead, flt: OrderFilter) -> Select[tuple[OrderDB]]:
        """Light query for lists: orders table plus the two 1:1 joins the visibility needs."""
        query = (
            select(OrderDB)
            .outerjoin(OrderOperationDB, OrderOperationDB.order_id == OrderDB.id)
            .outerjoin(OrderRecipientDB, OrderRecipientDB.order_id == OrderDB.id)
        )
        conditions: list[ColumnElement[bool]] = []
        if not self.is_admin(user):
            conditions.append(self._visible_to(user))
        if flt.status is not None:
            conditions.append(OrderDB.status == flt.status)
        if flt.zone_id is not None:
            conditions.append(OrderDB.zone_id == flt.zone_id)
        if flt.partner_id is not None:
            conditions.append(OrderDB.partner_id == flt.partner_id)
        if flt.courier_id is not None:
            conditions.append(OrderDB.courier_id == flt.courier_id)
        if flt.manager_id is not None:
            conditions.append(OrderOperationDB.manager_id == flt.manager_id)
        if flt.created_from is not None:
            conditions.append(OrderDB.created_at >= flt.created_from)
        if flt.created_to is not None:
            conditions.append(OrderDB.created_at <= flt.created_to)
        if conditions:
            query = query.where(and_(*conditions))
        return query

    async def list(
        self,
        user: UserRead,
        limit: int,
        offset: int,
        flt: OrderFilter,
    ) -> tuple[Sequence[Row[Any]], int]:
        """Return one page of (order, manager_id, total) rows and the total count.

        The total comes from a window count in the same query. When the page is
        empty, a separate count is run so the total stays correct.
        """
        base = self._filtered(user, flt)
        page_query = (
            base.add_columns(
                OrderOperationDB.manager_id, func.count().over().label("total")
            )
            .order_by(OrderDB.created_at.desc(), OrderDB.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.session.execute(page_query)).all()
        if rows:
            return rows, int(rows[0].total)
        count_query = select(func.count()).select_from(
            base.with_only_columns(OrderDB.id).subquery()
        )
        total = (await self.session.execute(count_query)).scalar_one()
        return rows, int(total)

    # --- writes -----------------------------------------------------------------

    async def _run(self, action: Callable[[], Awaitable[_T]]) -> _T:
        """Run the writes of one action and commit them together, mapping DB errors."""
        try:
            result = await action()
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            mapped = _translate(exc)
            if mapped is None:
                raise
            raise mapped from exc
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        return result

    async def _user_id_by_phone(self, phone: str) -> uuid.UUID | None:
        """Return the active user with exactly this phone, if one exists (phone is unique)."""
        result = await self.session.execute(
            select(UserDB.id).where(UserDB.phone == phone, UserDB.active.is_(True))
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _resolve_partner(data: OrderCreate, user: UserRead) -> uuid.UUID:
        if Order.is_admin(user):
            if data.partner_id is None:
                raise InvalidOrderReferenceError("partner_id is required for admins")
            return data.partner_id
        if data.partner_id is not None and data.partner_id != user.organization_id:
            raise OrderForbiddenError(
                "Orders can only be created for your organization"
            )
        return user.organization_id

    async def _insert_order(
        self,
        data: OrderCreate,
        user: UserRead,
        partner_id: uuid.UUID,
        recipient_user_id: uuid.UUID | None,
    ) -> int:
        order = OrderDB(
            tracking_number=generate_tracking_number(),
            external_order_id=data.external_order_id,
            partner_id=partner_id,
            service_type=data.service_type,
            zone_id=data.zone_id,
            status=ORDER_STATUS_CREATED_ID,
        )
        self.session.add(order)
        await self.session.flush()
        order_id = order.id
        self.session.add_all(
            [
                OrderSenderDB(order_id=order_id, **data.sender.model_dump()),
                OrderRecipientDB(
                    order_id=order_id,
                    **data.recipient.model_dump(exclude={"user_id"}),
                    user_id=recipient_user_id,
                ),
                OrderParcelDB(order_id=order_id, **data.parcel.model_dump()),
                OrderScheduleDB(order_id=order_id, **data.schedule.model_dump()),
                OrderPaymentDB(order_id=order_id, **data.payment.model_dump()),
                OrderStatusHistoryDB(
                    order_id=order_id,
                    status=ORDER_STATUS_CREATED_ID,
                    changed_by=user.id,
                ),
            ]
        )
        return order_id

    async def create(self, data: OrderCreate, user: UserRead) -> OrderDetail:
        """Create the order and all its blocks in one transaction.

        The tracking number is generated by the server and retried on collision.
        """
        partner_id = self._resolve_partner(data, user)
        recipient_user_id = data.recipient.user_id
        if recipient_user_id is None:
            recipient_user_id = await self._user_id_by_phone(
                data.recipient.recipient_phone
            )
        for _ in range(_TRACKING_ATTEMPTS):
            try:
                order_id = await self._run(
                    lambda: self._insert_order(
                        data, user, partner_id, recipient_user_id
                    )
                )
            except _TrackingNumberConflictError:
                continue
            return await self.get(order_id, user)
        raise OrderConflictError("Could not allocate a tracking number, please retry")

    async def update(
        self, order_id: int, data: OrderUpdate, user: UserRead
    ) -> OrderDetail:
        """Apply the sent fields. Admins and the order's manager may change anything; the
        sender organization may change it only while the order is still created."""
        detail = await self.get(order_id, user)
        privileged = self.is_admin(user) or self.is_manager(detail, user)
        if not privileged:
            sender_can_edit = (
                detail.order.partner_id == user.organization_id
                and detail.order.status == ORDER_STATUS_CREATED_ID
            )
            if not sender_can_edit:
                raise OrderForbiddenError("Order cannot be changed by this user")

        changes = {name: getattr(data, name) for name in data.model_fields_set}
        if "courier_id" in changes and not privileged:
            raise OrderForbiddenError(
                "Only admins and the manager can assign a courier"
            )

        async def _apply() -> None:
            order = detail.order
            for name in ("service_type", "zone_id", "courier_id", "tracking_url"):
                if name in changes:
                    setattr(order, name, changes[name])
            block_models = {
                "sender": OrderSenderDB,
                "recipient": OrderRecipientDB,
                "parcel": OrderParcelDB,
                "schedule": OrderScheduleDB,
                "payment": OrderPaymentDB,
            }
            for name, model_cls in block_models.items():
                if name not in changes:
                    continue
                values = changes[name].model_dump()
                if name == "recipient":
                    values["user_id"] = changes[
                        name
                    ].user_id or await self._user_id_by_phone(
                        changes[name].recipient_phone
                    )
                block = getattr(detail, name)
                if block is None:
                    block = model_cls(order_id=order_id)
                    self.session.add(block)
                for key, value in values.items():
                    setattr(block, key, value)
            order.updated_at = datetime.now(UTC)

        await self._run(_apply)
        return await self.get(order_id, user)

    async def upsert_operation(
        self, order_id: int, data: OperationUpsert, user: UserRead
    ) -> OrderOperationDB:
        """Set the sent operation fields. Admins may change anything; a manager may not reassign."""
        detail = await self.get(order_id, user)
        if not self.is_admin(user):
            if not self.is_manager(detail, user):
                raise OrderForbiddenError("Operation cannot be changed by this user")
            if "manager_id" in data.model_fields_set and data.manager_id != user.id:
                raise OrderForbiddenError("Only admins can reassign the manager")

        operation = detail.operation or OrderOperationDB(order_id=order_id)

        async def _apply() -> None:
            if detail.operation is None:
                self.session.add(operation)
            for field in data.model_fields_set:
                setattr(operation, field, getattr(data, field))

        await self._run(_apply)
        return operation

    async def add_status(
        self, order_id: int, data: StatusChangeCreate, user: UserRead
    ) -> OrderStatusHistoryDB:
        """Append a status history row and set the order's status in one transaction."""
        detail = await self.get(order_id, user)
        if not (
            self.is_admin(user)
            or self.is_manager(detail, user)
            or self.is_courier(detail, user)
        ):
            raise OrderForbiddenError("Status cannot be changed by this user")

        history = OrderStatusHistoryDB(
            order_id=order_id,
            status=data.status,
            exception_reason=data.exception_reason,
            next_action=data.next_action,
            comment=data.comment,
            changed_by=user.id,
        )

        async def _apply() -> None:
            detail.order.status = data.status
            detail.order.updated_at = datetime.now(UTC)
            self.session.add(history)

        await self._run(_apply)
        return history

    async def cancel(self, order_id: int, user: UserRead) -> None:
        """Soft-cancel an order (admins only). Cancelling a cancelled order changes nothing."""
        detail = await self.get(order_id, user)
        if not self.is_admin(user):
            raise OrderForbiddenError("Only admins can cancel orders")
        if detail.order.status == ORDER_STATUS_CANCELLED_ID:
            return
        history = OrderStatusHistoryDB(
            order_id=order_id,
            status=ORDER_STATUS_CANCELLED_ID,
            comment=_CANCEL_COMMENT,
            changed_by=user.id,
        )

        async def _apply() -> None:
            detail.order.status = ORDER_STATUS_CANCELLED_ID
            detail.order.updated_at = datetime.now(UTC)
            self.session.add(history)

        await self._run(_apply)
