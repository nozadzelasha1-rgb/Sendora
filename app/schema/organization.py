import uuid
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NAME_MAX_LENGTH = 255
PHONE_MAX_LENGTH = 20

_NON_NULLABLE_FIELDS = ("name", "type", "active")


def _normalize_name(value: str) -> str:
    """Strip the name; it must not be empty or longer than the limit."""
    value = value.strip()
    if not 1 <= len(value) <= NAME_MAX_LENGTH:
        raise ValueError(f"Name must be between 1 and {NAME_MAX_LENGTH} characters")
    return value


def _normalize_optional_text(value: str | None) -> str | None:
    """Strip the text; an empty value becomes None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _normalize_phone(value: str | None) -> str | None:
    """Strip the phone; an empty value becomes None; enforce the column length."""
    value = _normalize_optional_text(value)
    if value is not None and len(value) > PHONE_MAX_LENGTH:
        raise ValueError(f"Phone must be at most {PHONE_MAX_LENGTH} characters")
    return value


class OrganizationCreate(BaseModel):
    """Payload for creating an organization."""

    name: str
    type: int
    contact: str | None = None
    phone: str | None = None
    delivery_fee_gel: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_name(value)

    @field_validator("contact", mode="after")
    @classmethod
    def _validate_contact(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("phone", mode="after")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return _normalize_phone(value)


class OrganizationUpdate(BaseModel):
    """Partial update payload: only the fields that were sent are changed."""

    name: str | None = None
    type: int | None = None
    contact: str | None = None
    phone: str | None = None
    delivery_fee_gel: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    active: bool | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_name(value)

    @field_validator("contact", mode="after")
    @classmethod
    def _validate_contact(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("phone", mode="after")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return _normalize_phone(value)

    @model_validator(mode="after")
    def _check_sent_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field in _NON_NULLABLE_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class OrganizationRead(BaseModel):
    """Public representation of an organization."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: int
    contact: str | None
    phone: str | None
    delivery_fee_gel: Decimal | None
    active: bool
