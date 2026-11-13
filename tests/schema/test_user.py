import uuid

import pytest
from pydantic import ValidationError

from app.schema.user import UserCreate, UserCredentials, UserRead
from tests.seed import REF_PAYLOAD, TEST_ORG_ID, TEST_ROLE_ID

VALID_PASSWORD = "password123"


def _create(**overrides: object) -> UserCreate:
    payload: dict[str, object] = {
        "name": "alice",
        "password": VALID_PASSWORD,
        **REF_PAYLOAD,
    }
    payload.update(overrides)
    return UserCreate.model_validate(payload)


def _creds(**overrides: object) -> UserCredentials:
    payload: dict[str, object] = {"password": VALID_PASSWORD, "name": "alice"}
    payload.update(overrides)
    return UserCredentials.model_validate(payload)


# --- UserCreate: normalisation -------------------------------------------------


def test_user_create_name_stripped_and_lowered_returns_normalized() -> None:
    user = _create(name="  Alice_01  ")

    assert user.name == "alice_01"


def test_user_create_email_stripped_and_lowered_returns_normalized() -> None:
    user = _create(email="  Alice@Example.COM  ")

    assert user.email == "alice@example.com"


def test_user_create_phone_stripped_only_keeps_plus_and_digits() -> None:
    user = _create(phone="  +79991234567  ")

    assert user.phone == "+79991234567"


def test_user_create_empty_phone_returns_none() -> None:
    user = _create(phone="   ")

    assert user.phone is None


def test_user_create_empty_email_returns_none() -> None:
    user = _create(email="   ")

    assert user.email is None


def test_user_create_optional_fields_omitted_returns_none() -> None:
    user = _create()

    assert user.phone is None
    assert user.email is None


# --- UserCreate: required fields and name bounds --------------------------


def test_user_create_missing_name_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        UserCreate.model_validate({"password": VALID_PASSWORD})


def test_user_create_missing_password_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        UserCreate.model_validate({"name": "alice"})


@pytest.mark.parametrize("name", ["ab", "  ab  ", ""])
def test_user_create_name_too_short_raises_validation_error(name: str) -> None:
    with pytest.raises(ValidationError):
        _create(name=name)


def test_user_create_name_min_length_accepted() -> None:
    assert _create(name="abc").name == "abc"


def test_user_create_name_max_length_accepted() -> None:
    assert _create(name="a" * 50).name == "a" * 50


def test_user_create_name_too_long_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _create(name="a" * 51)


# --- UserCreate: password bounds ----------------------------------------------


def test_user_create_password_7_chars_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _create(password="a" * 7)


def test_user_create_password_8_chars_accepted() -> None:
    assert _create(password="a" * 8).password.get_secret_value() == "a" * 8


def test_user_create_password_128_chars_accepted() -> None:
    assert _create(password="a" * 128).password.get_secret_value() == "a" * 128


def test_user_create_password_129_chars_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _create(password="a" * 129)


# --- UserCreate: phone and email format ---------------------------------------


@pytest.mark.parametrize("phone", ["+79991234567", "123456", "1" * 15, "+" + "1" * 15])
def test_user_create_valid_phone_accepted(phone: str) -> None:
    assert _create(phone=phone).phone == phone


@pytest.mark.parametrize(
    "phone",
    ["12345", "1" * 16, "+7 999 123", "+7-999-123-45-67", "phone", "++79991234567"],
)
def test_user_create_invalid_phone_raises_validation_error(phone: str) -> None:
    with pytest.raises(ValidationError):
        _create(phone=phone)


@pytest.mark.parametrize("email", ["alice@example.com", "a.b+c@sub.example.org"])
def test_user_create_valid_email_accepted(email: str) -> None:
    assert _create(email=email).email == email


@pytest.mark.parametrize(
    "email",
    [
        "alice",
        "alice@",
        "@example.com",
        "alice@example",
        "al ice@example.com",
        "a@b@c.com",
    ],
)
def test_user_create_invalid_email_raises_validation_error(email: str) -> None:
    with pytest.raises(ValidationError):
        _create(email=email)


def test_user_create_email_longer_than_255_raises_validation_error() -> None:
    local = "a" * 250
    with pytest.raises(ValidationError):
        _create(email=f"{local}@x.com")


# --- UserCreate: secret handling ----------------------------------------------


def test_user_create_repr_does_not_leak_password() -> None:
    user = _create(password="super-secret-pass")

    assert "super-secret-pass" not in repr(user)
    assert "super-secret-pass" not in str(user)


# --- UserCredentials ----------------------------------------------------------


def test_user_credentials_name_only_accepted_and_normalized() -> None:
    creds = _creds(name="  ALICE ")

    assert creds.name == "alice"
    assert creds.phone is None
    assert creds.email is None


def test_user_credentials_phone_only_accepted() -> None:
    creds = _creds(name=None, phone=" +79991234567 ")

    assert creds.phone == "+79991234567"


def test_user_credentials_email_only_accepted_and_normalized() -> None:
    creds = _creds(name=None, email=" Alice@Example.com ")

    assert creds.email == "alice@example.com"


def test_user_credentials_no_identifier_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        UserCredentials.model_validate({"password": VALID_PASSWORD})


def test_user_credentials_two_identifiers_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _creds(name="alice", email="alice@example.com")


def test_user_credentials_all_three_identifiers_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _creds(name="alice", phone="+79991234567", email="alice@example.com")


def test_user_credentials_blank_name_counts_as_missing_raises_validation_error() -> (
    None
):
    with pytest.raises(ValidationError):
        _creds(name="   ")


def test_user_credentials_empty_password_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _creds(password="")


def test_user_credentials_password_1_char_accepted() -> None:
    assert _creds(password="x").password.get_secret_value() == "x"


def test_user_credentials_password_128_chars_accepted() -> None:
    assert _creds(password="x" * 128).password.get_secret_value() == "x" * 128


def test_user_credentials_password_129_chars_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _creds(password="x" * 129)


def test_user_credentials_invalid_email_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _creds(name=None, email="not-an-email")


def test_user_credentials_repr_does_not_leak_password() -> None:
    creds = _creds(password="super-secret-pass")

    assert "super-secret-pass" not in repr(creds)


# --- UserRead -----------------------------------------------------------------


def test_user_read_has_no_password_field() -> None:
    assert "password" not in UserRead.model_fields
    assert "password_hash" not in UserRead.model_fields


def test_user_read_from_orm_like_object_never_exposes_hash() -> None:
    class FakeUserDB:
        id = uuid.uuid4()
        name = "alice"
        role = TEST_ROLE_ID
        organization_id = TEST_ORG_ID
        zone_id = None
        active = True
        phone = None
        email = "alice@example.com"
        password_hash = "$argon2id$v=19$secret-hash-value"

    read = UserRead.model_validate(FakeUserDB(), from_attributes=True)

    dumped = read.model_dump()
    assert "password_hash" not in dumped
    assert "secret-hash-value" not in read.model_dump_json()
    assert dumped["name"] == "alice"
