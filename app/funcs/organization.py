import uuid
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.organizations import OrganizationDB
from app.schema.organization import OrganizationCreate, OrganizationUpdate
from app.utils.exception import InvalidOrganizationTypeError, OrganizationNotFoundError

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"


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
            contact=data.contact,
            phone=data.phone,
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
