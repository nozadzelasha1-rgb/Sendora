import asyncio
import uuid

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db_entities.users.user import UserDB
from app.schema.user import UserCreate, UserCredentials

_password_hash = PasswordHash.recommended()
# Verified against when no user is found, so timing does not reveal existence.
_DUMMY_HASH: str = _password_hash.hash("dummy-password-for-timing")


class UserAlreadyExistsError(Exception):
    """A user with the same username, phone or email already exists."""


class UserNotFoundError(Exception):
    """User not found, inactive, or credentials are invalid."""


class User:
    """Business logic for users."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    async def hash_password(plain: str) -> str:
        """Hash a password in a worker thread."""
        return await asyncio.to_thread(_password_hash.hash, plain)

    @staticmethod
    async def verify_password(plain: str, hashed: str) -> bool:
        """Verify a password in a worker thread; False for a malformed hash."""
        try:
            return await asyncio.to_thread(_password_hash.verify, plain, hashed)
        except UnknownHashError:
            return False

    async def create(self, data: UserCreate) -> UserDB:
        """Create a user; raise UserAlreadyExistsError on a duplicate identifier."""
        conditions: list[ColumnElement[bool]] = [UserDB.username == data.username]
        if data.phone is not None:
            conditions.append(UserDB.phone == data.phone)
        if data.email is not None:
            conditions.append(UserDB.email == data.email)
        existing = await self.session.execute(
            select(UserDB.id).where(or_(*conditions)).limit(1)
        )
        if existing.first() is not None:
            raise UserAlreadyExistsError("User already exists")

        user = UserDB(
            username=data.username,
            phone=data.phone,
            email=data.email,
            birth_date=data.birth_date,
            password_hash=await self.hash_password(data.password.get_secret_value()),
        )
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise UserAlreadyExistsError("User already exists") from exc
        except SQLAlchemyError:
            await self.session.rollback()
            raise
        return user

    async def get_by_credentials(self, creds: UserCredentials) -> UserDB:
        """Return the active user matching the credentials or raise UserNotFoundError."""
        if creds.username is not None:
            column = UserDB.username == creds.username
        elif creds.phone is not None:
            column = UserDB.phone == creds.phone
        elif creds.email is not None:
            column = UserDB.email == creds.email
        else:
            raise UserNotFoundError("Invalid credentials")

        result = await self.session.execute(select(UserDB).where(column))
        user = result.scalar_one_or_none()

        # Always run exactly one verification to equalise timing.
        password_ok = await self.verify_password(
            creds.password.get_secret_value(),
            user.password_hash if user is not None else _DUMMY_HASH,
        )
        if user is None or user.is_active is False or not password_ok:
            raise UserNotFoundError("Invalid credentials")
        return user

    async def check_credentials(self, creds: UserCredentials) -> bool:
        """Return True for valid credentials; raise UserNotFoundError otherwise."""
        await self.get_by_credentials(creds)
        return True

    async def delete_with_credentials(self, creds: UserCredentials) -> None:
        """Delete the user confirmed by credentials; raise UserNotFoundError if invalid."""
        user = await self.get_by_credentials(creds)
        await self.delete(user.id)

    async def delete_user_with_credentials(
        self, creds: UserCredentials, expected_user_id: uuid.UUID
    ) -> None:
        """Delete the user confirmed by credentials if it is the expected user.

        Raise UserNotFoundError if the credentials are invalid or belong to
        another user.
        """
        user = await self.get_by_credentials(creds)
        if user.id != expected_user_id:
            raise UserNotFoundError("Credentials do not match the expected user")
        await self.delete(user.id)

    async def delete(self, user_id: uuid.UUID) -> None:
        """Hard-delete an active user; raise UserNotFoundError if missing or inactive."""
        try:
            result = await self.session.execute(
                delete(UserDB)
                .where(UserDB.id == user_id, UserDB.is_active.is_not(False))
                .returning(UserDB.id)
            )
            deleted = result.first()
            if deleted is None:
                await self.session.rollback()
                raise UserNotFoundError("User not found")
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
