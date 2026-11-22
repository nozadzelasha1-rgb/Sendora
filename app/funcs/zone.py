import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.users.user import UserDB
from app.db_entities.zones import ZoneDB, ZoneUserDB
from app.schema.zone import ZoneCreate, ZoneUpdate
from app.utils.constant import ZONE_ADMIN_ROLE_IDS
from app.utils.exception import (
    InvalidZoneReferenceError,
    MembershipAlreadyExistsError,
    MembershipNotFoundError,
    NoDataError,
    UserNotFoundError,
    ZoneNotFoundError,
)

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"
_SQLSTATE_UNIQUE_VIOLATION = "23505"


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

    async def list_visible(self, role: int, user_id: uuid.UUID) -> Sequence[ZoneDB]:
        """Return the zones the user may see.

        Admin roles see every zone. Any other role sees only the zones it is a
        member of. Raise NoDataError when no zone rows match.
        """
        query = select(ZoneDB).order_by(ZoneDB.name, ZoneDB.id)
        if role not in ZONE_ADMIN_ROLE_IDS:
            query = query.join(ZoneUserDB, ZoneUserDB.zone_id == ZoneDB.id).where(
                ZoneUserDB.user_id == user_id
            )
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

    async def add_user(self, zone_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Make an active user a member of the zone.

        Raise ZoneNotFoundError, UserNotFoundError (missing or inactive user)
        or MembershipAlreadyExistsError.
        """
        await self.get(zone_id)
        active = await self.session.execute(
            select(UserDB.id).where(UserDB.id == user_id, UserDB.active.is_(True))
        )
        if active.scalar_one_or_none() is None:
            raise UserNotFoundError("User not found")
        self.session.add(ZoneUserDB(zone_id=zone_id, user_id=user_id))
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

    async def remove_user(self, zone_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Remove a user from the zone; raise MembershipNotFoundError if not a member."""
        try:
            result = await self.session.execute(
                delete(ZoneUserDB)
                .where(ZoneUserDB.zone_id == zone_id, ZoneUserDB.user_id == user_id)
                .returning(ZoneUserDB.user_id)
            )
            if result.first() is None:
                await self.session.rollback()
                raise MembershipNotFoundError("User is not a member")
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise
