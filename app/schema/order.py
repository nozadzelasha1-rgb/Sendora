import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

_NAME = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_PHONE = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)
]
_SHORT = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=255)]
_LONG = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=1000)]
_ADDRESS = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]
_CODE = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=32)]
_WINDOW = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=11)]
_NON_NULLABLE_ORDER_FIELDS = (
    "service_type",
    "sender",
    "recipient",
    "parcel",
    "schedule",
    "payment",
)


class OrderSenderIn(BaseModel):
    """Sender contact block of an order. A sent block replaces the stored block."""

    sender_company: _NAME
    sender_contact: _NAME
    sender_phone: _PHONE
    pickup_address: _LONG = None
    sender_comment: _LONG = None


class OrderRecipientIn(BaseModel):
    """Recipient block of an order. Recipients are not linked to user accounts."""

    recipient_name: _NAME
    recipient_phone: _PHONE
    recipient_alt_phone: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=20)
    ] = None
    delivery_address: _ADDRESS
    city: _NAME
    entrance: _SHORT = None
    floor: _SHORT = None
    apartment: _SHORT = None
    door_code: _SHORT = None
    landmark: _SHORT = None


class OrderParcelIn(BaseModel):
    """Parcel block of an order."""

    parcel_type: int
    pieces_count: int = Field(default=1, ge=1, le=32767)
    weight_kg: Decimal | None = Field(
        default=None, ge=0, max_digits=7, decimal_places=3
    )
    length_cm: Decimal | None = Field(
        default=None, ge=0, max_digits=6, decimal_places=1
    )
    width_cm: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=1)
    height_cm: Decimal | None = Field(
        default=None, ge=0, max_digits=6, decimal_places=1
    )
    description: _LONG = None
    fragile: bool = False
    declared_value_gel: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )


class OrderScheduleIn(BaseModel):
    """Pickup and delivery schedule of an order."""

    pickup_date: date | None = None
    pickup_window: _WINDOW = None
    requested_delivery_date: date | None = None
    delivery_window: _WINDOW = None


class OrderPaymentIn(BaseModel):
    """Payment block of an order."""

    delivery_payer: int
    delivery_fee_gel: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    cod_enabled: bool = False
    cod_amount_gel: Decimal = Field(
        default=Decimal(0), ge=0, max_digits=12, decimal_places=2
    )
    currency: int
    cod_method: int | None = None


class OrderCreate(BaseModel):
    """Payload for creating an order with all its blocks.

    organization_id is required for admins. Other users must be members of the
    organization they pass; when omitted, their only organization is used.
    """

    organization_id: uuid.UUID | None = None
    service_type: int
    zone_id: uuid.UUID | None = None
    sender: OrderSenderIn
    recipient: OrderRecipientIn
    parcel: OrderParcelIn
    schedule: OrderScheduleIn = Field(default_factory=OrderScheduleIn)
    payment: OrderPaymentIn


class OrderUpdate(BaseModel):
    """Partial update: only the sent fields change; a sent block replaces the stored block."""

    service_type: int | None = None
    zone_id: uuid.UUID | None = None
    courier_id: uuid.UUID | None = None
    tracking_url: _LONG = None
    sender: OrderSenderIn | None = None
    recipient: OrderRecipientIn | None = None
    parcel: OrderParcelIn | None = None
    schedule: OrderScheduleIn | None = None
    payment: OrderPaymentIn | None = None

    @model_validator(mode="after")
    def _check_sent_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field in _NON_NULLABLE_ORDER_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class OrderListItem(BaseModel):
    """Light order row used by the list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_number: str
    status: int
    organization_id: uuid.UUID
    service_type: int
    zone_id: uuid.UUID | None
    courier_id: uuid.UUID | None
    manager_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None


class SenderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sender_company: str
    sender_contact: str
    sender_phone: str
    pickup_address: str | None
    sender_comment: str | None


class RecipientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient_name: str
    recipient_phone: str
    recipient_alt_phone: str | None
    delivery_address: str
    city: str
    entrance: str | None
    floor: str | None
    apartment: str | None
    door_code: str | None
    landmark: str | None


class ParcelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parcel_type: int
    pieces_count: int
    weight_kg: Decimal | None
    length_cm: Decimal | None
    width_cm: Decimal | None
    height_cm: Decimal | None
    description: str | None
    fragile: bool
    declared_value_gel: Decimal | None


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pickup_date: date | None
    pickup_window: str | None
    requested_delivery_date: date | None
    delivery_window: str | None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    delivery_payer: int
    delivery_fee_gel: Decimal
    cod_enabled: bool
    cod_amount_gel: Decimal
    currency: int
    cod_method: int | None


class OperationRead(BaseModel):
    """Operation block. Internal fields are null for users who are not admin or the order's manager."""

    model_config = ConfigDict(from_attributes=True)

    carrier_id: str | None = None
    manager_id: uuid.UUID | None = None
    route_id: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    internal_comment: str | None = None


class OperationUpsert(BaseModel):
    """Operation fields to set. Only the sent fields change."""

    carrier_id: _CODE = None
    manager_id: uuid.UUID | None = None
    route_id: _CODE = None
    latitude: Decimal | None = Field(
        default=None, ge=-90, le=90, max_digits=9, decimal_places=6
    )
    longitude: Decimal | None = Field(
        default=None, ge=-180, le=180, max_digits=9, decimal_places=6
    )
    internal_comment: _LONG = None

    @model_validator(mode="after")
    def _check_sent_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class StatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: int
    exception_reason: int | None
    next_action: int | None
    comment: str | None
    changed_by: uuid.UUID | None
    created_at: datetime


class StatusChangeCreate(BaseModel):
    """A new status for the order; the history row is written with the change."""

    status: int
    exception_reason: int | None = None
    next_action: int | None = None
    comment: _LONG = None


class OrderRead(BaseModel):
    """Full order card: order row, all blocks and the status history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_number: str
    organization_id: uuid.UUID
    service_type: int
    zone_id: uuid.UUID | None
    courier_id: uuid.UUID | None
    status: int
    tracking_url: str | None
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None
    sender: SenderRead | None
    recipient: RecipientRead | None
    parcel: ParcelRead | None
    schedule: ScheduleRead | None
    payment: PaymentRead | None
    operation: OperationRead | None
    status_history: list[StatusHistoryRead]
