import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.db_entities.users.user import UserDB
from app.db_entities.users.user_session import UserSessionDB
from app.funcs.auth import (
    ACCESS_TOKEN_TYPE,
    Auth,
    InvalidTokenError,
    LoginResult,
    RefreshRetryError,
    RefreshTokenError,
    TokenExpiredError,
)
from app.funcs.user import User, UserNotFoundError
from app.funcs.user_session import UserSession, parse_refresh_token
from app.schema.user import UserCreate, UserCredentials
from tests.seed import TEST_ORG_ID, TEST_ROLE_ID

PASSWORD = "password123"
CLAIM_KEYS = {"sub", "name", "sid", "type", "iat", "exp", "jti"}


async def _make(session: AsyncSession, name: str = "alice") -> UserDB:
    return await User(session).create(
        UserCreate(
            role=TEST_ROLE_ID, organization_id=TEST_ORG_ID, name=name, password=PASSWORD
        )
    )


async def _session(
    session: AsyncSession, user: UserDB, now: datetime | None = None
) -> tuple[uuid.UUID, str]:
    """Create a real session row for the user; return (session id, refresh token)."""
    row, token = await UserSession(session).create(user.id, now or datetime.now(UTC))
    return row.id, token


async def _session_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(UserSessionDB)
        .where(UserSessionDB.user_id == user_id)
    )
    return int(count or 0)


def _claims(user_id: str | None = None, **overrides: Any) -> dict[str, Any]:
    """Return a complete, valid claim set that tests can alter or strip."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": user_id or str(uuid.uuid4()),
        "name": "alice",
        "sid": str(uuid.uuid4()),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": uuid.uuid4().hex,
    }
    claims.update(overrides)
    return claims


def _sign(claims: dict[str, Any], key: str | None = None, alg: str = "HS256") -> str:
    secret = settings.JWT_SECRET_KEY if key is None else key
    return jwt.encode(claims, secret, algorithm=alg)


# --- create / decode round trip -----------------------------------------------


async def test_create_access_token_decodes_to_user_identity(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    sid = uuid.uuid4()

    token = Auth.create_access_token(user, sid)
    identity = Auth.decode_token(token)

    assert identity.id == user.id
    assert identity.name == "alice"
    assert identity.session_id == sid


async def test_create_access_token_claims_are_flat_and_minimal(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    sid = uuid.uuid4()

    payload = jwt.decode(
        Auth.create_access_token(user, sid),
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )

    assert set(payload) == CLAIM_KEYS
    assert payload["sub"] == str(user.id)
    assert payload["sid"] == str(sid)
    assert payload["type"] == ACCESS_TOKEN_TYPE


async def test_create_access_token_exposes_no_secret_or_personal_data(
    session: AsyncSession,
) -> None:
    user = await User(session).create(
        UserCreate(
            role=TEST_ROLE_ID,
            organization_id=TEST_ORG_ID,
            name="alice",
            password=PASSWORD,
            phone="+79991234567",
            email="alice@example.com",
        )
    )

    token = Auth.create_access_token(user, uuid.uuid4())
    payload = jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )

    assert "password" not in payload
    assert "password_hash" not in payload
    assert "phone" not in payload
    assert "email" not in payload
    assert user.password_hash not in token
    assert PASSWORD not in token
    assert "+79991234567" not in token
    assert "alice@example.com" not in token


async def test_create_access_token_lifetime_equals_configured_minutes(
    session: AsyncSession,
) -> None:
    user = await _make(session)

    payload = jwt.decode(
        Auth.create_access_token(user, uuid.uuid4()),
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )

    assert payload["exp"] - payload["iat"] == (
        settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


async def test_create_access_token_explicit_delta_overrides_setting(
    session: AsyncSession,
) -> None:
    user = await _make(session)

    payload = jwt.decode(
        Auth.create_access_token(user, uuid.uuid4(), timedelta(seconds=90)),
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )

    assert payload["exp"] - payload["iat"] == 90


async def test_create_access_token_each_call_has_unique_jti(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    sid = uuid.uuid4()

    first = jwt.decode(
        Auth.create_access_token(user, sid),
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    second = jwt.decode(
        Auth.create_access_token(user, sid),
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )

    assert first["jti"] != second["jti"]


# --- decode failures ----------------------------------------------------------


def test_decode_token_expired_raises_token_expired_error() -> None:
    token = _sign(_claims(exp=datetime.now(UTC) - timedelta(minutes=1)))

    with pytest.raises(TokenExpiredError):
        Auth.decode_token(token)


async def test_create_access_token_negative_delta_is_expired(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    token = Auth.create_access_token(user, uuid.uuid4(), timedelta(minutes=-1))

    with pytest.raises(TokenExpiredError):
        Auth.decode_token(token)


def test_decode_token_bad_signature_raises_invalid_token_error() -> None:
    token = _sign(_claims(), key="another-secret-key-that-is-not-ours-0000")

    with pytest.raises(InvalidTokenError):
        Auth.decode_token(token)


def test_decode_token_tampered_payload_raises_invalid_token_error() -> None:
    header, _payload, signature = _sign(_claims()).split(".")
    forged_json = (
        b'{"sub":"00000000-0000-0000-0000-000000000001","name":"x",'
        b'"sid":"00000000-0000-0000-0000-000000000002",'
        b'"type":"access","iat":1,"exp":9999999999}'
    )
    forged = base64.urlsafe_b64encode(forged_json).rstrip(b"=").decode()

    with pytest.raises(InvalidTokenError):
        Auth.decode_token(f"{header}.{forged}.{signature}")


def test_decode_token_alg_none_raises_invalid_token_error() -> None:
    token = jwt.encode(_claims(), None, algorithm="none")

    with pytest.raises(InvalidTokenError):
        Auth.decode_token(token)


def test_decode_token_other_algorithm_raises_invalid_token_error() -> None:
    token = _sign(_claims(), alg="HS512")

    with pytest.raises(InvalidTokenError):
        Auth.decode_token(token)


@pytest.mark.parametrize(
    "garbage",
    ["", "not-a-jwt", "a.b.c", "....", "eyJhbGciOiJIUzI1NiJ9.e30."],
)
def test_decode_token_garbage_raises_invalid_token_error(garbage: str) -> None:
    with pytest.raises(InvalidTokenError):
        Auth.decode_token(garbage)


@pytest.mark.parametrize("missing", ["exp", "iat", "sub", "type", "sid"])
def test_decode_token_missing_required_claim_raises_invalid_token_error(
    missing: str,
) -> None:
    claims = _claims()
    del claims[missing]

    with pytest.raises(InvalidTokenError):
        Auth.decode_token(_sign(claims))


def test_decode_token_missing_sid_with_expired_exp_is_invalid_not_expired() -> None:
    """Required-claim validation runs before expiry, so a sid-less token is invalid."""
    claims = _claims(exp=datetime.now(UTC) - timedelta(minutes=1))
    del claims["sid"]

    with pytest.raises(InvalidTokenError):
        Auth.decode_token(_sign(claims))


@pytest.mark.parametrize("wrong_type", ["refresh", "", "ACCESS", None])
def test_decode_token_wrong_type_raises_invalid_token_error(wrong_type: Any) -> None:
    with pytest.raises(InvalidTokenError):
        Auth.decode_token(_sign(_claims(type=wrong_type)))


@pytest.mark.parametrize("bad_sub", ["not-a-uuid", "", 12345])
def test_decode_token_non_uuid_sub_raises_invalid_token_error(bad_sub: Any) -> None:
    with pytest.raises(InvalidTokenError):
        Auth.decode_token(_sign(_claims(sub=bad_sub)))


@pytest.mark.parametrize("bad_sid", ["not-a-uuid", "", 12345, None])
def test_decode_token_non_uuid_sid_raises_invalid_token_error(bad_sid: Any) -> None:
    with pytest.raises(InvalidTokenError):
        Auth.decode_token(_sign(_claims(sid=bad_sid)))


@pytest.mark.parametrize("bad_name", [123, ["alice"], {"name": "alice"}, True])
def test_decode_token_non_string_name_raises_invalid_token_error(
    bad_name: Any,
) -> None:
    with pytest.raises(InvalidTokenError):
        Auth.decode_token(_sign(_claims(name=bad_name)))


# --- is_token_valid -----------------------------------------------------------


async def test_is_token_valid_fresh_token_returns_true(session: AsyncSession) -> None:
    user = await _make(session)

    assert Auth.is_token_valid(Auth.create_access_token(user, uuid.uuid4())) is True


def test_is_token_valid_garbage_returns_false() -> None:
    assert Auth.is_token_valid("not-a-token") is False


async def test_is_token_valid_expired_token_returns_false(
    session: AsyncSession,
) -> None:
    user = await _make(session)

    assert (
        Auth.is_token_valid(
            Auth.create_access_token(user, uuid.uuid4(), timedelta(minutes=-1))
        )
        is False
    )


# --- get_user_from_token ------------------------------------------------------


async def test_get_user_from_token_active_user_returns_user(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    sid, _ = await _session(session, user)

    found = await Auth(session).get_user_from_token(Auth.create_access_token(user, sid))

    assert found.id == user.id


async def test_get_user_from_token_inactive_user_raises_invalid_token(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    sid, _ = await _session(session, user)
    token = Auth.create_access_token(user, sid)
    user.active = False
    await session.commit()

    with pytest.raises(InvalidTokenError):
        await Auth(session).get_user_from_token(token)


async def test_get_user_from_token_deleted_user_raises_invalid_token(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    user_id = user.id
    sid, _ = await _session(session, user)
    token = Auth.create_access_token(user, sid)
    await User(session).delete(user_id)

    with pytest.raises(InvalidTokenError):
        await Auth(session).get_user_from_token(token)


async def test_get_user_from_token_expired_token_raises_expired(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    sid, _ = await _session(session, user)
    token = Auth.create_access_token(user, sid, timedelta(minutes=-1))

    with pytest.raises(TokenExpiredError):
        await Auth(session).get_user_from_token(token)


async def test_get_user_from_token_revoked_session_raises_invalid_token(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    sid, refresh = await _session(session, user)
    token = Auth.create_access_token(user, sid)
    await UserSession(session).revoke(refresh, datetime.now(UTC))

    with pytest.raises(InvalidTokenError):
        await Auth(session).get_user_from_token(token)


async def test_get_user_from_token_expired_session_raises_invalid_token(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    sid, _ = await _session(session, user, datetime.now(UTC) - timedelta(days=8))
    token = Auth.create_access_token(user, sid)

    with pytest.raises(InvalidTokenError):
        await Auth(session).get_user_from_token(token)


async def test_get_user_from_token_unknown_session_raises_invalid_token(
    session: AsyncSession,
) -> None:
    user = await _make(session)
    token = Auth.create_access_token(user, uuid.uuid4())

    with pytest.raises(InvalidTokenError):
        await Auth(session).get_user_from_token(token)


async def test_get_user_from_token_session_of_other_user_raises_invalid_token(
    session: AsyncSession,
) -> None:
    alice = await _make(session, name="alice")
    bob = await _make(session, name="bob")
    bob_sid, _ = await _session(session, bob)
    token = Auth.create_access_token(alice, bob_sid)

    with pytest.raises(InvalidTokenError):
        await Auth(session).get_user_from_token(token)


# --- login --------------------------------------------------------------------


async def test_login_valid_credentials_returns_login_result(
    session: AsyncSession,
) -> None:
    created = await _make(session)

    result = await Auth(session).login(UserCredentials(name="alice", password=PASSWORD))

    assert isinstance(result, LoginResult)
    assert result.user.id == created.id
    identity = Auth.decode_token(result.access_token)
    assert identity.id == created.id
    refresh_sid, _ = parse_refresh_token(result.refresh_token)
    assert identity.session_id == refresh_sid


async def test_login_creates_one_session_per_call(session: AsyncSession) -> None:
    created = await _make(session)
    auth = Auth(session)

    first = await auth.login(UserCredentials(name="alice", password=PASSWORD))
    second = await auth.login(UserCredentials(name="alice", password=PASSWORD))

    assert first.refresh_token != second.refresh_token
    assert await _session_count(session, created.id) == 2


async def test_login_wrong_password_raises_user_not_found_and_creates_no_session(
    session: AsyncSession,
) -> None:
    created = await _make(session)

    with pytest.raises(UserNotFoundError):
        await Auth(session).login(
            UserCredentials(name="alice", password="wrong-password")
        )

    assert await _session_count(session, created.id) == 0


async def test_login_unknown_user_raises_user_not_found(session: AsyncSession) -> None:
    with pytest.raises(UserNotFoundError):
        await Auth(session).login(UserCredentials(name="nobody", password=PASSWORD))


# --- refresh ------------------------------------------------------------------


async def test_refresh_rotates_and_returns_access_for_same_session(
    session: AsyncSession,
) -> None:
    created = await _make(session)
    login = await Auth(session).login(UserCredentials(name="alice", password=PASSWORD))

    result = await Auth(session).refresh(login.refresh_token)

    assert result.user.id == created.id
    assert result.refresh_token != login.refresh_token
    new_sid, _ = parse_refresh_token(result.refresh_token)
    assert Auth.decode_token(result.access_token).session_id == new_sid
    assert new_sid == Auth.decode_token(login.access_token).session_id


async def test_refresh_garbage_token_raises_refresh_token_error(
    session: AsyncSession,
) -> None:
    with pytest.raises(RefreshTokenError):
        await Auth(session).refresh("garbage")


async def test_refresh_revoked_token_raises_refresh_token_error(
    session: AsyncSession,
) -> None:
    await _make(session)
    login = await Auth(session).login(UserCredentials(name="alice", password=PASSWORD))
    await Auth(session).logout(login.refresh_token)

    with pytest.raises(RefreshTokenError):
        await Auth(session).refresh(login.refresh_token)


async def test_refresh_parallel_retry_inside_grace_raises_retry_error(
    session: AsyncSession,
) -> None:
    await _make(session)
    login = await Auth(session).login(UserCredentials(name="alice", password=PASSWORD))
    await Auth(session).refresh(login.refresh_token)

    with pytest.raises(RefreshRetryError):
        await Auth(session).refresh(login.refresh_token)


async def test_refresh_reuse_after_grace_raises_refresh_token_error(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _make(session)
    login = await Auth(session).login(UserCredentials(name="alice", password=PASSWORD))
    await Auth(session).refresh(login.refresh_token)
    monkeypatch.setattr(settings, "REFRESH_TOKEN_REUSE_GRACE_SECONDS", 0)

    with pytest.raises(RefreshTokenError):
        await Auth(session).refresh(login.refresh_token)


async def test_refresh_random_secret_raises_and_keeps_session_usable(
    session: AsyncSession,
) -> None:
    await _make(session)
    login = await Auth(session).login(UserCredentials(name="alice", password=PASSWORD))
    sid = parse_refresh_token(login.refresh_token)[0]

    with pytest.raises(RefreshTokenError):
        await Auth(session).refresh(f"{sid}.{'z' * 43}")

    rotated = await Auth(session).refresh(login.refresh_token)
    assert parse_refresh_token(rotated.refresh_token)[0] == sid


# --- logout / logout_all ------------------------------------------------------


async def test_logout_revokes_session_of_refresh_token(session: AsyncSession) -> None:
    await _make(session)
    login = await Auth(session).login(UserCredentials(name="alice", password=PASSWORD))

    await Auth(session).logout(login.refresh_token)

    with pytest.raises(InvalidTokenError):
        await Auth(session).get_user_from_token(login.access_token)


@pytest.mark.parametrize(
    "token",
    ["garbage", "", f"{uuid.uuid4()}.unknown-secret"],
)
async def test_logout_bad_token_never_raises(session: AsyncSession, token: str) -> None:
    await Auth(session).logout(token)


async def test_logout_all_revokes_every_session_and_returns_count(
    session: AsyncSession,
) -> None:
    alice = await _make(session, name="alice")
    bob = await _make(session, name="bob")
    auth = Auth(session)
    alice_one = await auth.login(UserCredentials(name="alice", password=PASSWORD))
    alice_two = await auth.login(UserCredentials(name="alice", password=PASSWORD))
    bob_login = await auth.login(UserCredentials(name="bob", password=PASSWORD))

    count = await auth.logout_all(alice.id)

    assert count == 2
    for result in (alice_one, alice_two):
        with pytest.raises(InvalidTokenError):
            await auth.get_user_from_token(result.access_token)
        with pytest.raises(RefreshTokenError):
            await auth.refresh(result.refresh_token)
    still_bob = await auth.get_user_from_token(bob_login.access_token)
    assert still_bob.id == bob.id


async def test_logout_all_without_sessions_returns_zero(session: AsyncSession) -> None:
    user = await _make(session)

    assert await Auth(session).logout_all(user.id) == 0
