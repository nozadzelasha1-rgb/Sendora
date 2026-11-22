import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.organizations import OrganizationDB, OrganizationUserDB
from app.db_entities.users.user import UserDB
from app.schema.organization import OrganizationCreate, OrganizationUpdate
from app.utils.exception import (
    InvalidOrganizationTypeError,
    MembershipAlreadyExistsError,
    MembershipNotFoundError,
    OrganizationNotFoundError,
    UserNotFoundError,
)

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
_SQLSTATE_UNIQUE_VIOLATION = "23505"


class Organization:
    """Business logic for organizations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _commit(self) -> None:
        """Commit; map a foreign key violation to InvalidOrganizationTypeError."""
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if getattr(exc.orig, "sqlstate", None) == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                raise InvalidOrganizationTypeError("Unknown organization type") from exc
            raise
        except SQLAlchemyError:
            await self.session.rollback()
            raise

    async def create(self, data: OrganizationCreate) -> OrganizationDB:
        """Create an organization; raise InvalidOrganizationTypeError on a bad type."""
        organization = OrganizationDB(
            name=data.name,
            type=data.type,
            delivery_fee_gel=data.delivery_fee_gel,
        )
        self.session.add(organization)
        await self._commit()
        await self.session.refresh(organization)
        return organization

    async def get(self, organization_id: uuid.UUID) -> OrganizationDB:
        """Return the organization (active or not) or raise OrganizationNotFoundError."""
        result = await self.session.execute(
            select(OrganizationDB).where(OrganizationDB.id == organization_id)
        )
        organization = result.scalar_one_or_none()
        if organization is None:
            raise OrganizationNotFoundError("Organization not found")
        return organization

    async def list(
        self, limit: int, offset: int, active: bool = True
    ) -> Sequence[OrganizationDB]:
        """Return a page of organizations with the given active flag."""
        result = await self.session.execute(
            select(OrganizationDB)
            .where(OrganizationDB.active.is_(active))
            .order_by(OrganizationDB.name, OrganizationDB.id)
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def update(
        self, organization_id: uuid.UUID, data: OrganizationUpdate
    ) -> OrganizationDB:
        """Apply only the fields that were sent.

        Raise OrganizationNotFoundError if missing and
        InvalidOrganizationTypeError on a bad type.
        """
        organization = await self.get(organization_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(organization, field, value)
        await self._commit()
        return organization

    async def delete(self, organization_id: uuid.UUID) -> None:
        """Soft-delete (active=false); idempotent, raise OrganizationNotFoundError if missing."""
        try:
            result = await self.session.execute(
                update(OrganizationDB)
                .where(OrganizationDB.id == organization_id)
                .values(active=False)
                .returning(OrganizationDB.id)
            )
            if result.first() is None:
                await self.session.rollback()
                raise OrganizationNotFoundError("Organization not found")
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise

    async def add_user(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Make an active user a member of the organization.

        Raise OrganizationNotFoundError, UserNotFoundError (missing or inactive user)
        or MembershipAlreadyExistsError.
        """
        await self.get(organization_id)
        active = await self.session.execute(
            select(UserDB.id).where(UserDB.id == user_id, UserDB.active.is_(True))
        )
        if active.scalar_one_or_none() is None:
            raise UserNotFoundError("User not found")
        self.session.add(
            OrganizationUserDB(organization_id=organization_id, user_id=user_id)
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate == _SQLSTATE_UNIQUE_VIOLATION:
                raise MembershipAlreadyExistsError("User is already a member") from exc
            if sqlstate == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                raise UserNotFoundError("User not found") from exc
            raise
        except SQLAlchemyError:
            await self.session.rollback()
            raise

    async def remove_user(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Remove a user from the organization; raise MembershipNotFoundError if not a member."""
        try:
            result = await self.session.execute(
                delete(OrganizationUserDB)
                .where(
                    OrganizationUserDB.organization_id == organization_id,
                    OrganizationUserDB.user_id == user_id,
                )
                .returning(OrganizationUserDB.user_id)
            )
            if result.first() is None:
                await self.session.rollback()
                raise MembershipNotFoundError("User is not a member")
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
