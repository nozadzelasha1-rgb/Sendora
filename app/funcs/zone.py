import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.zones import ZoneDB
from app.schema.zone import ZoneCreate, ZoneUpdate
from app.utils.constant import ZONE_ADMIN_ROLE_IDS
from app.utils.exception import (
    InvalidZoneReferenceError,
    NoDataError,
    ZoneNotFoundError,
)

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"


class Zone:
    """Business logic for zones."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _commit(self) -> None:
        """Commit; map a foreign key violation to InvalidZoneReferenceError."""
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if getattr(exc.orig, "sqlstate", None) == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                raise InvalidZoneReferenceError("Unknown zone reference") from exc
            raise
        except SQLAlchemyError:
            await self.session.rollback()
            raise

    async def create(self, data: ZoneCreate) -> ZoneDB:
        """Create a zone; raise InvalidZoneReferenceError on an unknown reference."""
        zone = ZoneDB(
            name=data.name,
            city=data.city,
            boundary=data.boundary,
            manager_id=data.manager_id,
            assignment_rule=data.assignment_rule,
            status=data.status,
        )
        self.session.add(zone)
        await self._commit()
        await self.session.refresh(zone)
        return zone

    async def get(self, zone_id: uuid.UUID) -> ZoneDB:
        """Return the zone or raise ZoneNotFoundError."""
        result = await self.session.execute(select(ZoneDB).where(ZoneDB.id == zone_id))
        zone = result.scalar_one_or_none()
        if zone is None:
            raise ZoneNotFoundError("Zone not found")
        return zone

    async def list_visible(
        self, role: int, zone_id: uuid.UUID | None
    ) -> Sequence[ZoneDB]:
        """Return the zones the user may see.

        Admin roles see every zone. Any other role sees only its own zone.
        Raise NoDataError when the user has no zone or no zone rows match.
        """
        query = select(ZoneDB).order_by(ZoneDB.name, ZoneDB.id)
        if role not in ZONE_ADMIN_ROLE_IDS:
            if zone_id is None:
                raise NoDataError("No zone assigned to this user")
            query = query.where(ZoneDB.id == zone_id)
        result = await self.session.execute(query)
        zones = result.scalars().all()
        if not zones:
            raise NoDataError("No zones found")
        return zones

    async def update(self, zone_id: uuid.UUID, data: ZoneUpdate) -> ZoneDB:
        """Apply only the fields that were sent.

        Raise ZoneNotFoundError if missing and InvalidZoneReferenceError on an
        unknown reference.
        """
        zone = await self.get(zone_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(zone, field, value)
        await self._commit()
        return zone
