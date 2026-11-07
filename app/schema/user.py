import re
import uuid
from datetime import date, datetime
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.utils.time_utils import get_local_time

PHONE_PATTERN = re.compile(r"^\+?\d{6,15}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_username(value: str) -> str:
    """Strip surrounding whitespace and lower-case the username."""
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

    username: str = Field(min_length=1, max_length=200)
    password: SecretStr = Field(min_length=8, max_length=128)
    phone: str | None = None
    email: str | None = None
    birth_date: date | None = None

    @field_validator("username", mode="after")
    @classmethod
    def _validate_username(cls, value: str) -> str:
        value = normalize_username(value)
        if not 3 <= len(value) <= 50:
            raise ValueError("Username must be between 3 and 50 characters")
        return value

    @field_validator("phone", mode="after")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        return _check_phone(normalize_phone(value))

    @field_validator("email", mode="after")
    @classmethod
    def _validate_email(cls, value: str | None) -> str | None:
        return _check_email(normalize_email(value))

    @field_validator("birth_date", mode="after")
    @classmethod
    def _validate_birth_date(cls, value: date | None) -> date | None:
        if value is not None and value > get_local_time().date():
            raise ValueError("Birth date cannot be in the future")
        return value


class UserCredentials(BaseModel):
    """Login payload: a password and exactly one identifier."""

    password: SecretStr = Field(min_length=1, max_length=128)
    username: str | None = None
    phone: str | None = None
    email: str | None = None

    @field_validator("username", mode="after")
    @classmethod
    def _validate_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_username(value) or None

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
        supplied = [v for v in (self.username, self.phone, self.email) if v is not None]
        if len(supplied) != 1:
            raise ValueError("Provide exactly one of username, phone or email")
        return self


class UserRead(BaseModel):
    """Public representation of a user; never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str | None
    phone: str | None
    email: str | None
    birth_date: date | None
    is_active: bool | None
    created_at: datetime | None
    updated_at: datetime | None
