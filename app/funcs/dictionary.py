from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.dictionary import DictionaryDB, DictionarySpecDB
from app.schema.dictionary import DictionaryItemCreate, DictionaryItemUpdate
from app.utils.constant import PROTECTED_DICTIONARY_ITEM_IDS
from app.utils.exception import (
    DictionaryItemInUseError,
    DictionaryItemNotFoundError,
    DictionarySpecNotFoundError,
)

_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"


class Dictionary:
    """Business logic for dictionaries: specs and the items inside them."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except SQLAlchemyError:
            await self.session.rollback()
            raise

    async def _ensure_spec(self, spec_id: int) -> None:
        result = await self.session.execute(
            select(DictionarySpecDB.id).where(DictionarySpecDB.id == spec_id)
        )
        if result.scalar_one_or_none() is None:
            raise DictionarySpecNotFoundError("Dictionary spec not found")

    async def list_specs(self) -> Sequence[DictionarySpecDB]:
        """Return every dictionary spec ordered by id."""
        result = await self.session.execute(
            select(DictionarySpecDB).order_by(DictionarySpecDB.id)
        )
        return result.scalars().all()

    async def list_items(self, spec_id: int) -> Sequence[DictionaryDB]:
        """Return the items of a spec; raise DictionarySpecNotFoundError if it is missing."""
        await self._ensure_spec(spec_id)
        result = await self.session.execute(
            select(DictionaryDB)
            .where(DictionaryDB.spec_id == spec_id)
            .order_by(DictionaryDB.id)
        )
        return result.scalars().all()

    async def get_item(self, spec_id: int, item_id: int) -> DictionaryDB:
        """Return an item of the given spec.

        Raise DictionarySpecNotFoundError if the spec is missing and
        DictionaryItemNotFoundError if the item is missing or belongs to another spec.
        """
        await self._ensure_spec(spec_id)
        result = await self.session.execute(
            select(DictionaryDB).where(
                DictionaryDB.id == item_id, DictionaryDB.spec_id == spec_id
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise DictionaryItemNotFoundError("Dictionary item not found")
        return item

    async def create_item(
        self, spec_id: int, data: DictionaryItemCreate
    ) -> DictionaryDB:
        """Add an item to the spec; raise DictionarySpecNotFoundError if it is missing."""
        await self._ensure_spec(spec_id)
        item = DictionaryDB(
            spec_id=spec_id, name=data.name, description=data.description
        )
        self.session.add(item)
        await self._commit()
        await self.session.refresh(item)
        return item

    async def update_item(
        self, spec_id: int, item_id: int, data: DictionaryItemUpdate
    ) -> DictionaryDB:
        """Apply only the sent fields to the item."""
        item = await self.get_item(spec_id, item_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        await self._commit()
        return item

    async def delete_item(self, spec_id: int, item_id: int) -> None:
        """Delete an item.

        Raise DictionaryItemInUseError for protected items and for items still
        referenced by other records (foreign key), DictionaryItemNotFoundError if missing.
        """
        item = await self.get_item(spec_id, item_id)
        if item.id in PROTECTED_DICTIONARY_ITEM_IDS:
            raise DictionaryItemInUseError(
                "Protected dictionary item cannot be deleted"
            )
        try:
            await self.session.execute(
                delete(DictionaryDB).where(DictionaryDB.id == item.id)
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if getattr(exc.orig, "sqlstate", None) == _SQLSTATE_FOREIGN_KEY_VIOLATION:
                raise DictionaryItemInUseError("Dictionary item is in use") from exc
            raise
        except SQLAlchemyError:
            await self.session.rollback()
            raise
