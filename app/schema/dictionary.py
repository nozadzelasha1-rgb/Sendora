from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

NAME_MAX_LENGTH = 255
DESCRIPTION_MAX_LENGTH = 1000

_NON_NULLABLE_FIELDS = ("name",)


def _normalize_name(value: str) -> str:
    """Strip the name; it must not be empty or longer than the column limit."""
    value = value.strip()
    if not 1 <= len(value) <= NAME_MAX_LENGTH:
        raise ValueError(f"Name must be between 1 and {NAME_MAX_LENGTH} characters")
    return value


def _normalize_description(value: str | None) -> str | None:
    """Strip the description; an empty value becomes None."""
    if value is None:
        return None
    value = value.strip()
    if len(value) > DESCRIPTION_MAX_LENGTH:
        raise ValueError(
            f"Description must be at most {DESCRIPTION_MAX_LENGTH} characters"
        )
    return value or None


class DictionarySpecRead(BaseModel):
    """A dictionary spec: a named group of items, e.g. order_status."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class DictionaryItemRead(BaseModel):
    """One item of a dictionary spec."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    spec_id: int
    name: str
    description: str | None


class DictionaryItemCreate(BaseModel):
    """Payload for adding an item to a dictionary spec."""

    name: str
    description: str | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _normalize_name(value)

    @field_validator("description", mode="after")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        return _normalize_description(value)


class DictionaryItemUpdate(BaseModel):
    """Partial update: only the fields that were sent are changed."""

    name: str | None = None
    description: str | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_name(value)

    @field_validator("description", mode="after")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        return _normalize_description(value)

    @model_validator(mode="after")
    def _check_sent_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for field in _NON_NULLABLE_FIELDS:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self
