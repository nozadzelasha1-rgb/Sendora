import uuid
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

NAME_MAX_LENGTH = 255
CITY_MAX_LENGTH = 255

_NON_NULLABLE_FIELDS = ("name", "city", "status")


def _normalize_text(value: str, label: str, max_length: int) -> str:
    """Strip the text; it must not be empty or longer than the column limit."""
    value = value.strip()
    if not 1 <= len(value) <= max_length:
        raise ValueError(f"{label} must be between 1 and {max_length} characters")
    return value


class ZoneCreate(BaseModel):
    """Payload for creating a zone."""

    name: str
    city: str
    boundary: Any | None = None
    assignment_rule: int | None = None
    status: int

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_text(value, "Name", NAME_MAX_LENGTH)

    @field_validator("city", mode="after")
    @classmethod
    def _validate_city(cls, value: str) -> str:
        return _normalize_text(value, "City", CITY_MAX_LENGTH)


class ZoneUpdate(BaseModel):
    """Partial update payload: only the fields that were sent are changed."""

    name: str | None = None
    city: str | None = None
    boundary: Any | None = None
    assignment_rule: int | None = None
    status: int | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_text(value, "Name", NAME_MAX_LENGTH)

    @field_validator("city", mode="after")
    @classmethod
    def _validate_city(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_text(value, "City", CITY_MAX_LENGTH)

    @model_validator(mode="after")
    def _check_sent_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field in _NON_NULLABLE_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ZoneRead(BaseModel):
    """Public representation of a zone."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    city: str
    boundary: Any | None
    assignment_rule: int | None
    status: int


class ZoneMemberCreate(BaseModel):
    """Payload for adding a user to a zone."""

    user_id: uuid.UUID


class ZoneMemberRead(BaseModel):
    """A user's membership in a zone."""

    zone_id: uuid.UUID
    user_id: uuid.UUID
