import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.db_entities.users.user_session import UserSessionDB
from app.funcs.user import User
from app.funcs.user_session import (
    REASON_LOGOUT,
    REASON_LOGOUT_ALL,
    REASON_REUSE,
    REASON_USER_INACTIVE,
    SessionInvalidError,
    SessionRetryError,
    UserSession,
    hash_secret,
    parse_refresh_token,
)
from app.schema.user import UserCreate
from tests.seed import TEST_ORG_ID, TEST_ROLE_ID

PASSWORD = "password123"
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
REFRESH_LIFETIME = timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
GRACE_SECONDS = settings.REFRESH_TOKEN_REUSE_GRACE_SECONDS


async def _user_id(session: AsyncSession, name: str = "alice") -> uuid.UUID:
    user = await User(session).create(
        UserCreate(
            role=TEST_ROLE_ID, organization_id=TEST_ORG_ID, name=name, password=PASSWORD
        )
    )
    return user.id


async def _create_session(
    session: AsyncSession, user_id: uuid.UUID, now: datetime = NOW
) -> tuple[uuid.UUID, str]:
    row, token = await UserSession(session).create(user_id, now)
    return row.id, token


async def _row(session: AsyncSession, sid: uuid.UUID) -> Row[Any]:
    """Read the session columns straight from the database, bypassing the identity map."""
    result = await session.execute(
        select(
            UserSessionDB.refresh_token_hash,
            UserSessionDB.previous_token_hash,
            UserSessionDB.rotated_at,
            UserSessionDB.expires_at,
            UserSessionDB.revoked_at,
            UserSessionDB.revoked_reason,
        ).where(UserSessionDB.id == sid)
    )
    return result.one()


async def _exists(session: AsyncSession, sid: uuid.UUID) -> bool:
    result = await session.execute(
        select(UserSessionDB.id).where(UserSessionDB.id == sid)
    )
    return result.scalar_one_or_none() is not None


async def _count_for_user(session: AsyncSession, user_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(UserSessionDB)
        .where(UserSessionDB.user_id == user_id)
    )
    return int(count or 0)


# --- hash_secret / parse_refresh_token ----------------------------------------


def test_hash_secret_returns_sha256_digest_of_32_bytes() -> None:
    digest = hash_secret("abc")

    assert digest == hashlib.sha256(b"abc").digest()
    assert len(digest) == 32


def test_parse_refresh_token_valid_returns_session_id_and_secret() -> None:
    sid = uuid.uuid4()

    parsed_sid, secret = parse_refresh_token(f"{sid}.abc-_DEF")

    assert parsed_sid == sid
    assert secret == "abc-_DEF"


@pytest.mark.parametrize(
    "token",
    [
        "",
        "no-separator",
        f"{uuid.uuid4()}",
        f"{uuid.uuid4()}.",
        ".secret-only",
        "not-a-uuid.secret",
        "x.y.z",
    ],
)
def test_parse_refresh_token_malformed_raises_session_invalid(token: str) -> None:
    with pytest.raises(SessionInvalidError):
        parse_refresh_token(token)


def test_parse_refresh_token_non_string_raises_session_invalid_only() -> None:
    bad: Any = None

    with pytest.raises(SessionInvalidError):
        parse_refresh_token(bad)


# --- create -------------------------------------------------------------------


async def test_create_returns_token_prefixed_with_session_id(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)

    sid, token = await _create_session(session, user_id)

    token_sid, secret = parse_refresh_token(token)
    assert token_sid == sid
    assert secret


async def test_create_stores_sha256_of_secret_and_no_plain_token(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, token = await _create_session(session, user_id)
    _, secret = parse_refresh_token(token)

    stored = await _row(session, sid)

    assert stored.refresh_token_hash == hashlib.sha256(secret.encode()).digest()
    assert stored.refresh_token_hash != token.encode()
    assert stored.previous_token_hash is None
    assert stored.rotated_at is None
    assert stored.revoked_at is None
    assert stored.revoked_reason is None


async def test_create_sets_expiry_to_configured_refresh_lifetime(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, _ = await _create_session(session, user_id)

    stored = await _row(session, sid)

    assert stored.expires_at == NOW + REFRESH_LIFETIME


async def test_create_purges_only_own_expired_and_revoked_sessions(
    session: AsyncSession,
) -> None:
    alice = await _user_id(session, "alice")
    bob = await _user_id(session, "bob")
    user_session = UserSession(session)
    expired_sid, _ = await _create_session(session, alice, NOW - timedelta(days=8))
    revoked_sid, revoked_token = await _create_session(session, alice, NOW)
    await user_session.revoke(revoked_token, NOW)
    live_sid, _ = await _create_session(session, alice, NOW)
    bob_expired_sid, _ = await _create_session(session, bob, NOW - timedelta(days=8))

    new_sid, _ = await _create_session(session, alice, NOW)

    assert not await _exists(session, expired_sid)
    assert not await _exists(session, revoked_sid)
    assert await _exists(session, live_sid)
    assert await _exists(session, new_sid)
    assert await _exists(session, bob_expired_sid)


# --- rotate: success ----------------------------------------------------------


async def test_rotate_returns_user_session_and_new_token(session: AsyncSession) -> None:
    user_id = await _user_id(session)
    sid, token = await _create_session(session, user_id)
    _, old_secret = parse_refresh_token(token)
    later = NOW + timedelta(seconds=1)

    user, rotated_sid, new_token = await UserSession(session).rotate(token, later)

    assert user.id == user_id
    assert rotated_sid == sid
    assert new_token != token
    new_sid, new_secret = parse_refresh_token(new_token)
    assert new_sid == sid
    stored = await _row(session, sid)
    assert stored.refresh_token_hash == hash_secret(new_secret)
    assert stored.previous_token_hash == hash_secret(old_secret)
    assert stored.rotated_at == later
    assert stored.expires_at == later + REFRESH_LIFETIME


async def test_rotate_old_token_fails_after_grace_window(session: AsyncSession) -> None:
    user_id = await _user_id(session)
    _, token = await _create_session(session, user_id)
    await UserSession(session).rotate(token, NOW)

    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(token, NOW + timedelta(seconds=60))


async def test_rotate_chain_issues_working_token_each_time(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, first = await _create_session(session, user_id)

    _, _, second = await UserSession(session).rotate(first, NOW + timedelta(minutes=1))
    _, rotated_sid, third = await UserSession(session).rotate(
        second, NOW + timedelta(minutes=2)
    )

    assert rotated_sid == sid
    assert len({first, second, third}) == 3


# --- rotate: grace window and reuse -------------------------------------------


async def test_rotate_inside_grace_window_raises_retry_and_keeps_session(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, first = await _create_session(session, user_id)
    _, _, second = await UserSession(session).rotate(first, NOW)

    with pytest.raises(SessionRetryError):
        await UserSession(session).rotate(first, NOW + timedelta(seconds=5))

    stored = await _row(session, sid)
    assert stored.revoked_at is None
    assert stored.revoked_reason is None
    _, rotated_sid, _ = await UserSession(session).rotate(
        second, NOW + timedelta(seconds=6)
    )
    assert rotated_sid == sid


@pytest.mark.parametrize(
    ("delay", "expected"),
    [
        (timedelta(seconds=GRACE_SECONDS), SessionRetryError),
        (timedelta(seconds=GRACE_SECONDS, microseconds=1), SessionInvalidError),
    ],
    ids=["at-window-edge-retry", "just-past-window-revoked"],
)
async def test_rotate_grace_window_boundary(
    session: AsyncSession, delay: timedelta, expected: type[Exception]
) -> None:
    user_id = await _user_id(session)
    sid, first = await _create_session(session, user_id)
    await UserSession(session).rotate(first, NOW)

    with pytest.raises(expected):
        await UserSession(session).rotate(first, NOW + delay)

    stored = await _row(session, sid)
    if expected is SessionRetryError:
        assert stored.revoked_at is None
    else:
        assert stored.revoked_reason == REASON_REUSE


async def test_rotate_reuse_outside_grace_revokes_session_with_reuse_reason(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, first = await _create_session(session, user_id)
    _, _, second = await UserSession(session).rotate(first, NOW)
    reuse_at = NOW + timedelta(seconds=60)

    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(first, reuse_at)

    stored = await _row(session, sid)
    assert stored.revoked_reason == REASON_REUSE
    assert stored.revoked_at == reuse_at
    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(second, reuse_at + timedelta(seconds=1))


async def test_rotate_previous_token_replay_outside_grace_revokes_session(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, first = await _create_session(session, user_id)
    await UserSession(session).rotate(first, NOW)

    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(first, NOW + timedelta(seconds=60))

    stored = await _row(session, sid)
    assert stored.revoked_reason == REASON_REUSE


async def test_rotate_random_secret_outside_grace_does_not_revoke_session(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, first = await _create_session(session, user_id)
    _, _, second = await UserSession(session).rotate(first, NOW)
    attacker_token = f"{sid}.{'z' * 43}"

    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(attacker_token, NOW + timedelta(seconds=60))

    stored = await _row(session, sid)
    assert stored.revoked_at is None
    assert stored.revoked_reason is None
    _, rotated_sid, _ = await UserSession(session).rotate(
        second, NOW + timedelta(seconds=61)
    )
    assert rotated_sid == sid


async def test_rotate_random_secret_inside_grace_raises_invalid_not_retry(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, first = await _create_session(session, user_id)
    await UserSession(session).rotate(first, NOW)

    with pytest.raises(SessionInvalidError) as excinfo:
        await UserSession(session).rotate(f"{sid}.{'z' * 43}", NOW)

    assert not isinstance(excinfo.value, SessionRetryError)
    assert (await _row(session, sid)).revoked_at is None


async def test_rotate_random_secret_on_fresh_session_does_not_revoke(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, _ = await _create_session(session, user_id)

    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(f"{sid}.{'z' * 43}", NOW)

    stored = await _row(session, sid)
    assert stored.revoked_at is None
    assert stored.revoked_reason is None


# --- rotate: invalid sessions -------------------------------------------------


async def test_rotate_expired_session_raises_invalid_and_does_not_rotate(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, token = await _create_session(session, user_id, NOW - timedelta(days=8))

    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(token, NOW)

    stored = await _row(session, sid)
    assert stored.rotated_at is None
    assert stored.revoked_at is None


async def test_rotate_revoked_session_raises_invalid_and_keeps_original_reason(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, token = await _create_session(session, user_id)
    await UserSession(session).revoke(token, NOW)

    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(token, NOW + timedelta(seconds=1))

    stored = await _row(session, sid)
    assert stored.revoked_reason == REASON_LOGOUT


async def test_rotate_inactive_user_revokes_session_with_user_inactive_reason(
    session: AsyncSession,
) -> None:
    user = await User(session).create(
        UserCreate(
            role=TEST_ROLE_ID,
            organization_id=TEST_ORG_ID,
            name="alice",
            password=PASSWORD,
        )
    )
    user_id = user.id
    sid, token = await _create_session(session, user_id)
    user.active = False
    await session.commit()

    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(token, NOW)

    stored = await _row(session, sid)
    assert stored.revoked_reason == REASON_USER_INACTIVE
    assert stored.revoked_at == NOW


async def test_rotate_unknown_session_raises_invalid(session: AsyncSession) -> None:
    token = f"{uuid.uuid4()}.{'a' * 43}"

    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(token, NOW)


@pytest.mark.parametrize("token", ["garbage", "", "a.b"])
async def test_rotate_malformed_token_raises_invalid(
    session: AsyncSession, token: str
) -> None:
    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(token, NOW)


# --- revoke -------------------------------------------------------------------


async def test_revoke_marks_session_logout_and_blocks_rotation(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, token = await _create_session(session, user_id)

    await UserSession(session).revoke(token, NOW)

    stored = await _row(session, sid)
    assert stored.revoked_at == NOW
    assert stored.revoked_reason == REASON_LOGOUT
    with pytest.raises(SessionInvalidError):
        await UserSession(session).rotate(token, NOW + timedelta(seconds=1))


async def test_revoke_twice_keeps_first_revocation_time(session: AsyncSession) -> None:
    user_id = await _user_id(session)
    sid, token = await _create_session(session, user_id)

    await UserSession(session).revoke(token, NOW)
    await UserSession(session).revoke(token, NOW + timedelta(hours=1))

    stored = await _row(session, sid)
    assert stored.revoked_at == NOW


@pytest.mark.parametrize("token", ["garbage", "", f"{uuid.uuid4()}.unknown-secret"])
async def test_revoke_garbage_or_unknown_token_is_silent(
    session: AsyncSession, token: str
) -> None:
    await UserSession(session).revoke(token, NOW)


async def test_revoke_with_wrong_secret_does_not_revoke_session(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, _ = await _create_session(session, user_id)

    await UserSession(session).revoke(f"{sid}.wrong-secret", NOW)

    stored = await _row(session, sid)
    assert stored.revoked_at is None


# --- revoke_all_for_user ------------------------------------------------------


async def test_revoke_all_for_user_revokes_only_live_sessions_of_that_user(
    session: AsyncSession,
) -> None:
    alice = await _user_id(session, "alice")
    bob = await _user_id(session, "bob")
    user_session = UserSession(session)
    live_one, _ = await _create_session(session, alice)
    live_two, _ = await _create_session(session, alice)
    already_gone, gone_token = await _create_session(session, alice)
    await user_session.revoke(gone_token, NOW)
    bob_sid, _ = await _create_session(session, bob)
    logout_all_at = NOW + timedelta(minutes=1)

    count = await user_session.revoke_all_for_user(alice, logout_all_at)

    assert count == 2
    for sid in (live_one, live_two):
        stored = await _row(session, sid)
        assert stored.revoked_reason == REASON_LOGOUT_ALL
        assert stored.revoked_at == logout_all_at
    kept = await _row(session, already_gone)
    assert kept.revoked_reason == REASON_LOGOUT
    assert kept.revoked_at == NOW
    untouched = await _row(session, bob_sid)
    assert untouched.revoked_at is None


async def test_revoke_all_for_user_without_live_sessions_returns_zero(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)

    assert await UserSession(session).revoke_all_for_user(user_id, NOW) == 0


async def test_revoke_all_for_user_stores_custom_reason(session: AsyncSession) -> None:
    user_id = await _user_id(session)
    sid, _ = await _create_session(session, user_id)

    count = await UserSession(session).revoke_all_for_user(
        user_id, NOW, reason="manual"
    )

    assert count == 1
    stored = await _row(session, sid)
    assert stored.revoked_reason == "manual"


# --- get_active_user ----------------------------------------------------------


async def test_get_active_user_live_session_returns_user(session: AsyncSession) -> None:
    user_id = await _user_id(session)
    sid, _ = await _create_session(session, user_id)

    user = await UserSession(session).get_active_user(user_id, sid, NOW)

    assert user.id == user_id


async def test_get_active_user_revoked_session_raises_invalid(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, token = await _create_session(session, user_id)
    await UserSession(session).revoke(token, NOW)

    with pytest.raises(SessionInvalidError):
        await UserSession(session).get_active_user(user_id, sid, NOW)


async def test_get_active_user_expired_session_raises_invalid(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, _ = await _create_session(session, user_id, NOW - timedelta(days=8))

    with pytest.raises(SessionInvalidError):
        await UserSession(session).get_active_user(user_id, sid, NOW)


async def test_get_active_user_inactive_user_raises_invalid(
    session: AsyncSession,
) -> None:
    user = await User(session).create(
        UserCreate(
            role=TEST_ROLE_ID,
            organization_id=TEST_ORG_ID,
            name="alice",
            password=PASSWORD,
        )
    )
    user_id = user.id
    sid, _ = await _create_session(session, user_id)
    user.active = False
    await session.commit()

    with pytest.raises(SessionInvalidError):
        await UserSession(session).get_active_user(user_id, sid, NOW)


async def test_get_active_user_deleted_user_raises_invalid(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    sid, _ = await _create_session(session, user_id)
    await User(session).delete(user_id)

    with pytest.raises(SessionInvalidError):
        await UserSession(session).get_active_user(user_id, sid, NOW)


async def test_get_active_user_wrong_session_id_raises_invalid(
    session: AsyncSession,
) -> None:
    user_id = await _user_id(session)
    await _create_session(session, user_id)

    with pytest.raises(SessionInvalidError):
        await UserSession(session).get_active_user(user_id, uuid.uuid4(), NOW)


async def test_get_active_user_session_of_other_user_raises_invalid(
    session: AsyncSession,
) -> None:
    alice = await _user_id(session, "alice")
    bob = await _user_id(session, "bob")
    bob_sid, _ = await _create_session(session, bob)

    with pytest.raises(SessionInvalidError):
        await UserSession(session).get_active_user(alice, bob_sid, NOW)


# --- cascade ------------------------------------------------------------------


async def test_deleting_user_cascades_to_their_sessions(session: AsyncSession) -> None:
    user_id = await _user_id(session)
    await _create_session(session, user_id)
    await _create_session(session, user_id)

    await User(session).delete(user_id)

    assert await _count_for_user(session, user_id) == 0
