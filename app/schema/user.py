import re
import uuid
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

PHONE_PATTERN = re.compile(r"^\+?\d{6,15}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_name(value: str) -> str:
    """Strip surrounding whitespace and lower-case the user name."""
    return value.strip().lower()


def normalize_email(value: str | None) -> str | None:
    """Strip and lower-case the email; an empty value becomes None."""
    if value is None:
        return None
    value = value.strip().lower()
    return value or None


def normalize_phone(value: str | None) -> str | None:
    """Strip the phone number; an empty value becomes None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _check_phone(value: str | None) -> str | None:
    if value is not None and not PHONE_PATTERN.fullmatch(value):
        raise ValueError("Invalid phone number format")
    return value


def _check_email(value: str | None) -> str | None:
    if value is not None:
        if len(value) > 255:
            raise ValueError("Email is too long")
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("Invalid email format")
    return value


class UserCreate(BaseModel):
    """Payload for creating a user."""

    name: str = Field(min_length=1, max_length=200)
    password: SecretStr = Field(min_length=8, max_length=128)
    role: int
    organization_id: uuid.UUID
    zone_id: uuid.UUID | None = None
    phone: str | None = None
    email: str | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = normalize_name(value)
        if not 3 <= len(value) <= 50:
            raise ValueError("Name must be between 3 and 50 characters")
        return value

    @field_validator("phone", mode="after")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return _check_phone(normalize_phone(value))

    @field_validator("email", mode="after")
    @classmethod
    def _validate_email(cls, value: str | None) -> str | None:
        return _check_email(normalize_email(value))


class UserCredentials(BaseModel):
    """Login payload: a password and exactly one identifier."""

    password: SecretStr = Field(min_length=1, max_length=128)
    name: str | None = None
    phone: str | None = None
    email: str | None = None

    @field_validator("name", mode="after")
    @classmethod
    def _validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_name(value) or None

    @field_validator("phone", mode="after")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return _check_phone(normalize_phone(value))

    @field_validator("email", mode="after")
    @classmethod
    def _validate_email(cls, value: str | None) -> str | None:
        return _check_email(normalize_email(value))

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> Self:
        supplied = [v for v in (self.name, self.phone, self.email) if v is not None]
        if len(supplied) != 1:
            raise ValueError("Provide exactly one of name, phone or email")
        return self


class UserRead(BaseModel):
    """Public representation of a user; never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: int
    organization_id: uuid.UUID
    zone_id: uuid.UUID | None
    active: bool
    email: str | None
    phone: str | None
