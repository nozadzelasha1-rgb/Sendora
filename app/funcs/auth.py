import uuid
from datetime import timedelta
from typing import NamedTuple

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.db_entities.users.user import UserDB
from app.funcs.user import User
from app.funcs.user_session import (
    SessionInvalidError,
    SessionRetryError,
    UserSession,
)
from app.schema.auth import TokenUser
from app.schema.user import UserCredentials
from app.utils.time_utils import get_local_time

ACCESS_TOKEN_TYPE = "access"


class AuthError(Exception):
    """Base class for authentication failures."""


class TokenExpiredError(AuthError):
    """The access token has expired."""


class InvalidTokenError(AuthError):
    """The access token is missing, malformed, tampered or not usable."""


class RefreshTokenError(AuthError):
    """The refresh token is invalid, expired, revoked or reused."""


class RefreshRetryError(AuthError):
    """A parallel refresh is in progress inside the grace window; retry."""


class LoginResult(NamedTuple):
    """Outcome of a login or refresh."""

    user: UserDB
    access_token: str
    refresh_token: str


class Auth:
    """Business logic for access tokens."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def create_access_token(
        user: UserDB, session_id: uuid.UUID, expires_delta: timedelta | None = None
    ) -> str:
        """Create a signed access token with the user id, name and session id."""
        issued_at = get_local_time()
        lifetime = expires_delta or timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
        claims = {
            "sub": str(user.id),
            "name": user.name,
            "sid": str(session_id),
            "type": ACCESS_TOKEN_TYPE,
            "iat": issued_at,
            "exp": issued_at + lifetime,
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(
            claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )

    @staticmethod
    def decode_token(token: str) -> TokenUser:
        """Verify an access token and return its identity."""
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                options={"require": ["exp", "iat", "sub", "type", "sid"]},
            )
            if payload.get("type") != ACCESS_TOKEN_TYPE:
                raise InvalidTokenError("Invalid token")
            name = payload.get("name")
            if name is not None and not isinstance(name, str):
                raise InvalidTokenError("Invalid token")
            return TokenUser(
                id=uuid.UUID(str(payload["sub"])),
                name=name,
                session_id=uuid.UUID(str(payload["sid"])),
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("Token expired") from exc
        except (jwt.PyJWTError, ValueError) as exc:
            raise InvalidTokenError("Invalid token") from exc

    @staticmethod
    def is_token_valid(token: str) -> bool:
        """Return True if the token decodes successfully."""
        try:
            Auth.decode_token(token)
        except AuthError:
            return False
        return True

    async def get_user_from_token(self, token: str) -> UserDB:
        """Return the active user for a valid token and live session or raise an AuthError."""
        token_user = self.decode_token(token)
        try:
            return await UserSession(self.session).get_active_user(
                token_user.id, token_user.session_id, get_local_time()
            )
        except SessionInvalidError as exc:
            raise InvalidTokenError("Invalid token") from exc

    async def login(self, creds: UserCredentials) -> LoginResult:
        """Check credentials, open a session and issue tokens.

        UserNotFoundError propagates for invalid credentials.
        """
        user = await User(self.session).get_by_credentials(creds)
        session, refresh_token = await UserSession(self.session).create(
            user.id, get_local_time()
        )
        return LoginResult(
            user, self.create_access_token(user, session.id), refresh_token
        )

    async def refresh(self, refresh_token: str) -> LoginResult:
        """Rotate the refresh token and issue a new access token."""
        try:
            user, session_id, new_refresh_token = await UserSession(
                self.session
            ).rotate(refresh_token, get_local_time())
        except SessionInvalidError as exc:
            raise RefreshTokenError("Invalid refresh token") from exc
        except SessionRetryError as exc:
            raise RefreshRetryError("Refresh in progress") from exc
        return LoginResult(
            user, self.create_access_token(user, session_id), new_refresh_token
        )

    async def logout(self, refresh_token: str) -> None:
        """Revoke the session of the refresh token; never raises for a bad token."""
        await UserSession(self.session).revoke(refresh_token, get_local_time())

    async def logout_all(self, user_id: uuid.UUID) -> int:
        """Revoke all sessions of the user and return how many were revoked."""
        return await UserSession(self.session).revoke_all_for_user(
            user_id, get_local_time()
        )
