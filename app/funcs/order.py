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
from app.db_entities.organizations import OrganizationUserDB
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
    OrganizationChoiceRequiredError,
)
from app.utils.tracking import generate_tracking_number

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
_SQLSTATE_UNIQUE_VIOLATION = "23505"
_CHOOSE_ORGANIZATION_MESSAGE = "Choose the organization the order is created for"
_NOT_A_MEMBER_MESSAGE = "User is not a member of any organization"
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
    organization_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
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
    if sqlstate == _SQLSTATE_UNIQUE_VIOLATION and (
        _TRACKING_CONSTRAINT_MARKER in str(exc.orig)
    ):
        return _TrackingNumberConflictError()
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
    def _organizations_of(user_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
        """Subquery with the ids of the organizations the user is a member of."""
        return select(OrganizationUserDB.organization_id).where(
            OrganizationUserDB.user_id == user_id
        )

    @staticmethod
    def _visible_to(user: UserRead) -> ColumnElement[bool]:
        """Non-admin visibility: orders of the user's organizations, plus assigned manager or courier."""
        return or_(
            OrderDB.organization_id.in_(Order._organizations_of(user.id)),
            OrderOperationDB.manager_id == user.id,
            OrderDB.courier_id == user.id,
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
        query = select(OrderDB).outerjoin(
            OrderOperationDB, OrderOperationDB.order_id == OrderDB.id
        )
        conditions: list[ColumnElement[bool]] = []
        if not self.is_admin(user):
            conditions.append(self._visible_to(user))
        if flt.status is not None:
            conditions.append(OrderDB.status == flt.status)
        if flt.zone_id is not None:
            conditions.append(OrderDB.zone_id == flt.zone_id)
        if flt.organization_id is not None:
            conditions.append(OrderDB.organization_id == flt.organization_id)
        if flt.user_id is not None:
            conditions.append(
                OrderDB.organization_id.in_(self._organizations_of(flt.user_id))
            )
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

        Non-admins may filter only by their own user_id; admins may use any user_id.

        The total comes from a window count in the same query. When the page is
        empty, a separate count is run so the total stays correct.
        """
        if (
            flt.user_id is not None
            and not self.is_admin(user)
            and flt.user_id != user.id
        ):
            raise OrderForbiddenError(
                "Users can only filter orders by their own user_id"
            )
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

    async def _member_organization_ids(self, user_id: uuid.UUID) -> Sequence[uuid.UUID]:
        result = await self.session.execute(
            select(OrganizationUserDB.organization_id).where(
                OrganizationUserDB.user_id == user_id
            )
        )
        return list(result.scalars().all())

    async def _resolve_organization(
        self, data: OrderCreate, user: UserRead
    ) -> uuid.UUID:
        """Pick the organization that owns the new order.

        Admins must always name one. Other users must belong to at least one
        organization; a user of several organizations must name one of them.
        Raise OrganizationChoiceRequiredError when the choice is missing and
        OrderForbiddenError when the user has no organization or names a foreign one.
        """
        if self.is_admin(user):
            if data.organization_id is None:
                raise OrganizationChoiceRequiredError(_CHOOSE_ORGANIZATION_MESSAGE)
            return data.organization_id
        member_of = await self._member_organization_ids(user.id)
        if not member_of:
            raise OrderForbiddenError(_NOT_A_MEMBER_MESSAGE)
        if data.organization_id is not None:
            if data.organization_id not in member_of:
                raise OrderForbiddenError(
                    "Orders can only be created for your organizations"
                )
            return data.organization_id
        if len(member_of) > 1:
            raise OrganizationChoiceRequiredError(_CHOOSE_ORGANIZATION_MESSAGE)
        return member_of[0]

    async def _insert_order(
        self,
        data: OrderCreate,
        user: UserRead,
        organization_id: uuid.UUID,
    ) -> int:
        order = OrderDB(
            tracking_number=generate_tracking_number(),
            organization_id=organization_id,
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
                OrderRecipientDB(order_id=order_id, **data.recipient.model_dump()),
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
        organization_id = await self._resolve_organization(data, user)
        for _ in range(_TRACKING_ATTEMPTS):
            try:
                order_id = await self._run(
                    lambda: self._insert_order(data, user, organization_id)
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
            member_of = await self._member_organization_ids(user.id)
            sender_can_edit = (
                detail.order.organization_id in member_of
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
