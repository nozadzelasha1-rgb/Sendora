import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schema.auth import LogoutRequest, RefreshRequest, TokenResponse, TokenUser
from app.schema.user import UserRead


def _user_read() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="alice",
        phone=None,
        email="alice@example.com",
        birth_date=None,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# --- TokenUser ----------------------------------------------------------------


def test_token_user_accepts_uuid_username_and_session_id() -> None:
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()

    token_user = TokenUser(id=user_id, username="alice", session_id=session_id)

    assert token_user.id == user_id
    assert token_user.username == "alice"
    assert token_user.session_id == session_id


def test_token_user_accepts_none_username() -> None:
    token_user = TokenUser(id=uuid.uuid4(), username=None, session_id=uuid.uuid4())

    assert token_user.username is None


def test_token_user_dump_exposes_only_id_username_and_session_id() -> None:
    dumped = TokenUser(
        id=uuid.uuid4(), username="alice", session_id=uuid.uuid4()
    ).model_dump()

    assert set(dumped) == {"id", "username", "session_id"}


def test_token_user_invalid_id_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        TokenUser(id="not-a-uuid", username="alice", session_id=uuid.uuid4())


def test_token_user_invalid_session_id_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        TokenUser(id=uuid.uuid4(), username="alice", session_id="not-a-uuid")


def test_token_user_missing_session_id_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        TokenUser(id=uuid.uuid4(), username="alice")  # type: ignore[call-arg]


# --- TokenResponse ------------------------------------------------------------


def test_token_response_token_type_defaults_to_bearer() -> None:
    response = TokenResponse(
        access_token="abc", refresh_token="def", expires_in=1800, user=_user_read()
    )

    assert response.token_type == "bearer"


def test_token_response_dump_has_exact_keys_and_no_secrets() -> None:
    response = TokenResponse(
        access_token="abc", refresh_token="def", expires_in=1800, user=_user_read()
    )

    dumped = response.model_dump()

    assert set(dumped) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_in",
        "user",
    }
    assert set(dumped["user"]) == set(UserRead.model_fields)
    assert "password" not in dumped["user"]
    assert "password_hash" not in dumped["user"]


def test_token_response_missing_expires_in_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        TokenResponse(access_token="abc", refresh_token="def", user=_user_read())  # type: ignore[call-arg]


def test_token_response_missing_refresh_token_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        TokenResponse(access_token="abc", expires_in=1800, user=_user_read())  # type: ignore[call-arg]


# --- RefreshRequest -----------------------------------------------------------


def test_refresh_request_accepts_token_of_max_length() -> None:
    token = "a" * 512

    assert RefreshRequest(refresh_token=token).refresh_token == token


@pytest.mark.parametrize("token", ["", "a" * 513])
def test_refresh_request_out_of_bounds_token_raises_validation_error(
    token: str,
) -> None:
    with pytest.raises(ValidationError):
        RefreshRequest(refresh_token=token)


def test_refresh_request_missing_token_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        RefreshRequest()  # type: ignore[call-arg]


# --- LogoutRequest ------------------------------------------------------------


@pytest.mark.parametrize("token", ["", "garbage", "x" * 5000, "ყ.ა"])
def test_logout_request_accepts_any_string(token: str) -> None:
    assert LogoutRequest(refresh_token=token).refresh_token == token


def test_logout_request_missing_token_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        LogoutRequest()  # type: ignore[call-arg]
