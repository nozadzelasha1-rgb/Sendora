import uuid
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NAME_MAX_LENGTH = 255

_NON_NULLABLE_FIELDS = ("name", "type", "active")


def _normalize_name(value: str) -> str:
    """Strip the name; it must not be empty or longer than the limit."""
    value = value.strip()
    if not 1 <= len(value) <= NAME_MAX_LENGTH:
        raise ValueError(f"Name must be between 1 and {NAME_MAX_LENGTH} characters")
    return value


class OrganizationCreate(BaseModel):
    """Payload for creating an organization."""

    name: str
    type: int
    delivery_fee_gel: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_name(value)


class OrganizationUpdate(BaseModel):
    """Partial update payload: only the fields that were sent are changed."""

    name: str | None = None
    type: int | None = None
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
    delivery_fee_gel: Decimal | None
    active: bool


class OrganizationMemberCreate(BaseModel):
    """Payload for adding a user to an organization."""

    user_id: uuid.UUID


class OrganizationMemberRead(BaseModel):
    """A user's membership in an organization."""

    organization_id: uuid.UUID
    user_id: uuid.UUID
