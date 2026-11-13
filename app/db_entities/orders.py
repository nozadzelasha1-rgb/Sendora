import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    UUID,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db_entities.base import Base


class OrderDB(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("partner_id", "external_order_id"),
        {"schema": "dbo"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tracking_number: Mapped[str] = mapped_column(Text, unique=True)
    external_order_id: Mapped[str | None] = mapped_column(Text)
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dbo.organizations.id")
    )
    service_type: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.dictionary.id")
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dbo.zones.id")
    )
    courier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dbo.users.id")
    )
    status: Mapped[int] = mapped_column(BigInteger, ForeignKey("dbo.dictionary.id"))
    tracking_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderStatusHistoryDB(Base):
    __tablename__ = "order_status_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("dbo.orders.id"))
    status: Mapped[int] = mapped_column(BigInteger, ForeignKey("dbo.dictionary.id"))
    exception_reason: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dbo.dictionary.id")
    )
    next_action: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dbo.dictionary.id")
    )
    comment: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dbo.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class OrderSenderDB(Base):
    __tablename__ = "order_senders"

    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.orders.id"), primary_key=True
    )
    sender_company: Mapped[str] = mapped_column(Text)
    sender_contact: Mapped[str] = mapped_column(Text)
    sender_phone: Mapped[str] = mapped_column(String(20))
    pickup_address: Mapped[str | None] = mapped_column(Text)
    sender_comment: Mapped[str | None] = mapped_column(Text)


class OrderRecipientDB(Base):
    __tablename__ = "order_recipients"

    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.orders.id"), primary_key=True
    )
    recipient_name: Mapped[str] = mapped_column(Text)
    recipient_phone: Mapped[str] = mapped_column(String(20))
    recipient_alt_phone: Mapped[str | None] = mapped_column(String(20))
    delivery_address: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    entrance: Mapped[str | None] = mapped_column(Text)
    floor: Mapped[str | None] = mapped_column(Text)
    apartment: Mapped[str | None] = mapped_column(Text)
    door_code: Mapped[str | None] = mapped_column(Text)
    landmark: Mapped[str | None] = mapped_column(Text)


class OrderParcelDB(Base):
    __tablename__ = "order_parcels"

    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.orders.id"), primary_key=True
    )
    parcel_type: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.dictionary.id")
    )
    pieces_count: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    length_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    description: Mapped[str | None] = mapped_column(Text)
    fragile: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    declared_value_gel: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class OrderScheduleDB(Base):
    __tablename__ = "order_schedules"

    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.orders.id"), primary_key=True
    )
    pickup_date: Mapped[date | None] = mapped_column(Date)
    pickup_window: Mapped[str | None] = mapped_column(String(11))
    requested_delivery_date: Mapped[date | None] = mapped_column(Date)
    delivery_window: Mapped[str | None] = mapped_column(String(11))


class OrderPaymentDB(Base):
    __tablename__ = "order_payments"

    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.orders.id"), primary_key=True
    )
    delivery_payer: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.dictionary.id")
    )
    delivery_fee_gel: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    cod_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    cod_amount_gel: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), server_default=text("0")
    )
    currency: Mapped[int] = mapped_column(BigInteger, ForeignKey("dbo.dictionary.id"))
    cod_method: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dbo.dictionary.id")
    )


class OrderOperationDB(Base):
    __tablename__ = "order_operations"

    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.orders.id"), primary_key=True
    )
    carrier_id: Mapped[str | None] = mapped_column(String(32))
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dbo.users.id")
    )
    route_id: Mapped[str | None] = mapped_column(String(32))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    internal_comment: Mapped[str | None] = mapped_column(Text)
