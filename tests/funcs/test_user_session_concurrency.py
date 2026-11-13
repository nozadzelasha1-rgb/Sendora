import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db_entities.users.user import UserDB
from app.db_entities.users.user_session import UserSessionDB
from app.funcs.user import User
from app.funcs.user_session import (
    REASON_REUSE,
    SessionRetryError,
    UserSession,
)
from app.schema.user import UserCreate

PASSWORD = "password123"
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def committed_session(
    engine: AsyncEngine,
) -> AsyncGenerator[tuple[uuid.UUID, uuid.UUID, str], None]:
    """Commit a real user and session on their own connection; delete them afterwards.

    Deleting the user cascades to user_sessions, so nothing leaks into other tests.
    """
    username = f"race_{uuid.uuid4().hex[:16]}"
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        user = await User(setup).create(
            UserCreate(username=username, password=PASSWORD)
        )
        user_id = user.id
        row, token = await UserSession(setup).create(user_id, NOW)
        sid = row.id
    try:
        yield user_id, sid, token
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as cleanup:
            await cleanup.execute(delete(UserDB).where(UserDB.id == user_id))
            await cleanup.commit()


async def _rotate_on_own_connection(
    engine: AsyncEngine, token: str
) -> tuple[uuid.UUID, str] | type[Exception]:
    async with AsyncSession(engine, expire_on_commit=False) as db_session:
        try:
            _, sid, new_token = await UserSession(db_session).rotate(token, NOW)
        except SessionRetryError:
            return SessionRetryError
        return sid, new_token


async def test_rotate_same_token_concurrently_one_wins_other_retries(
    engine: AsyncEngine,
    committed_session: tuple[uuid.UUID, uuid.UUID, str],
) -> None:
    _, sid, token = committed_session

    results = await asyncio.gather(
        _rotate_on_own_connection(engine, token),
        _rotate_on_own_connection(engine, token),
    )

    winners = [r for r in results if isinstance(r, tuple)]
    losers = [r for r in results if r is SessionRetryError]
    assert len(winners) == 1
    assert len(losers) == 1
    assert winners[0][0] == sid

    async with AsyncSession(engine, expire_on_commit=False) as check:
        stored = (
            await check.execute(
                select(
                    UserSessionDB.revoked_at,
                    UserSessionDB.revoked_reason,
                ).where(UserSessionDB.id == sid)
            )
        ).one()
    assert stored.revoked_at is None
    assert stored.revoked_reason != REASON_REUSE

    new_token = winners[0][1]
    async with AsyncSession(engine, expire_on_commit=False) as follow_up:
        _, rotated_sid, _ = await UserSession(follow_up).rotate(
            new_token, NOW + timedelta(seconds=1)
        )
    assert rotated_sid == sid
