import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.db_entities.users.user import UserDB
from app.db_entities.users.user_session import UserSessionDB

REASON_LOGOUT = "logout"
REASON_LOGOUT_ALL = "logout_all"
REASON_REUSE = "reuse"
REASON_USER_INACTIVE = "user_inactive"


class SessionInvalidError(Exception):
    """The session is missing, invalid, expired, revoked or the token mismatches."""


class SessionRetryError(Exception):
    """Parallel refresh inside the grace window; the session is NOT revoked."""


def hash_secret(secret: str) -> bytes:
    """Return the SHA-256 digest (32 bytes) of a refresh token secret."""
    return hashlib.sha256(secret.encode()).digest()


def parse_refresh_token(token: str) -> tuple[uuid.UUID, str]:
    """Split a refresh token into (session id, secret); SessionInvalidError if malformed."""
    try:
        sid_part, separator, secret = token.partition(".")
        if not separator or not secret:
            raise ValueError("malformed token")
        return uuid.UUID(sid_part), secret
    except (ValueError, AttributeError, TypeError) as exc:
        raise SessionInvalidError("Invalid session") from exc


class UserSession:
    """Business logic for refresh-token sessions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _expires_at(now: datetime) -> datetime:
        return now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    async def create(
        self, user_id: uuid.UUID, now: datetime
    ) -> tuple[UserSessionDB, str]:
        """Purge dead sessions of the user, insert a new one; return it and the plain token."""
        sid = uuid.uuid4()
        token = f"{sid}.{secrets.token_urlsafe(32)}"
        _, secret = parse_refresh_token(token)
        row = UserSessionDB(
            id=sid,
            user_id=user_id,
            refresh_token_hash=hash_secret(secret),
            created_at=now,
            expires_at=self._expires_at(now),
        )
        try:
            await self.session.execute(
                delete(UserSessionDB)
                .where(
                    UserSessionDB.user_id == user_id,
                    or_(
                        UserSessionDB.expires_at < now,
                        UserSessionDB.revoked_at.is_not(None),
                    ),
                )
                .execution_options(synchronize_session=False)
            )
            self.session.add(row)
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        return row, token

    async def rotate(
        self, refresh_token: str, now: datetime
    ) -> tuple[UserDB, uuid.UUID, str]:
        """Atomically rotate the refresh token; return (user, session id, new token)."""
        sid, secret = parse_refresh_token(refresh_token)
        presented_hash = hash_secret(secret)
        new_secret = secrets.token_urlsafe(32)
        new_token = f"{sid}.{new_secret}"
        try:
            result = await self.session.execute(
                update(UserSessionDB)
                .where(
                    UserSessionDB.id == sid,
                    UserDB.id == UserSessionDB.user_id,
                    UserDB.is_active.is_not(False),
                    UserSessionDB.refresh_token_hash == presented_hash,
                    UserSessionDB.revoked_at.is_(None),
                    UserSessionDB.expires_at > now,
                )
                .values(
                    previous_token_hash=UserSessionDB.refresh_token_hash,
                    refresh_token_hash=hash_secret(new_secret),
                    rotated_at=now,
                    expires_at=self._expires_at(now),
                )
                .returning(UserSessionDB.user_id)
                .execution_options(synchronize_session=False)
            )
            user_id = result.scalar_one_or_none()
            if user_id is not None:
                user = (
                    await self.session.execute(
                        select(UserDB).where(UserDB.id == user_id)
                    )
                ).scalar_one()
                await self.session.commit()
                return user, sid, new_token
            await self._classify_failed_rotation(sid, presented_hash, now)
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        raise SessionInvalidError("Invalid session")  # pragma: no cover

    async def _classify_failed_rotation(
        self, sid: uuid.UUID, presented_hash: bytes, now: datetime
    ) -> None:
        """Always raises SessionInvalidError or SessionRetryError.

        The session is revoked (reason 'reuse') only on genuine reuse: the
        presented secret equals the previous one and the grace window has
        passed. The session id is not secret, so a random or wrong secret is
        not evidence of theft and must not let anyone kill a victim's session;
        such a mismatch leaves the session untouched.
        """
        row = (
            await self.session.execute(
                select(UserSessionDB, UserDB.is_active)
                .join(UserDB, UserDB.id == UserSessionDB.user_id)
                .where(UserSessionDB.id == sid)
            )
        ).first()
        if row is None:
            await self.session.rollback()
            raise SessionInvalidError("Invalid session")
        record, is_active = row
        if record.revoked_at is not None or record.expires_at <= now:
            await self.session.rollback()
            raise SessionInvalidError("Invalid session")
        if is_active is False:
            await self._revoke_by_id(sid, now, REASON_USER_INACTIVE)
            raise SessionInvalidError("Invalid session")
        previous = record.previous_token_hash
        if previous is None or not hmac.compare_digest(previous, presented_hash):
            await self.session.rollback()
            raise SessionInvalidError("Invalid session")
        if record.rotated_at is not None and now - record.rotated_at <= timedelta(
            seconds=settings.REFRESH_TOKEN_REUSE_GRACE_SECONDS
        ):
            await self.session.rollback()
            raise SessionRetryError("Concurrent refresh")
        await self._revoke_by_id(sid, now, REASON_REUSE)
        raise SessionInvalidError("Invalid session")

    async def _revoke_by_id(self, sid: uuid.UUID, now: datetime, reason: str) -> None:
        await self.session.execute(
            update(UserSessionDB)
            .where(UserSessionDB.id == sid, UserSessionDB.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()

    async def revoke(self, refresh_token: str, now: datetime) -> None:
        """Revoke the session matching the token; silent and idempotent."""
        try:
            sid, secret = parse_refresh_token(refresh_token)
        except SessionInvalidError:
            return
        try:
            await self.session.execute(
                update(UserSessionDB)
                .where(
                    UserSessionDB.id == sid,
                    UserSessionDB.refresh_token_hash == hash_secret(secret),
                    UserSessionDB.revoked_at.is_(None),
                )
                .values(revoked_at=now, revoked_reason=REASON_LOGOUT)
                .execution_options(synchronize_session=False)
            )
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise

    async def revoke_all_for_user(
        self, user_id: uuid.UUID, now: datetime, reason: str = REASON_LOGOUT_ALL
    ) -> int:
        """Revoke all unrevoked sessions of the user; return how many were revoked."""
        try:
            result = await self.session.execute(
                update(UserSessionDB)
                .where(
                    UserSessionDB.user_id == user_id,
                    UserSessionDB.revoked_at.is_(None),
                )
                .values(revoked_at=now, revoked_reason=reason)
                .returning(UserSessionDB.id)
                .execution_options(synchronize_session=False)
            )
            count = len(result.all())
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        return count

    async def get_active_user(
        self, user_id: uuid.UUID, session_id: uuid.UUID, now: datetime
    ) -> UserDB:
        """Return the active user bound to a live session or raise SessionInvalidError."""
        result = await self.session.execute(
            select(UserDB)
            .join(UserSessionDB, UserSessionDB.user_id == UserDB.id)
            .where(
                UserDB.id == user_id,
                UserDB.is_active.is_not(False),
                UserSessionDB.id == session_id,
                UserSessionDB.user_id == user_id,
                UserSessionDB.revoked_at.is_(None),
                UserSessionDB.expires_at > now,
            )
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise SessionInvalidError("Invalid session")
        return user
