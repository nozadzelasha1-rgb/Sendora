import uuid
from typing import Any

from sqlalchemy import UUID, BigInteger, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db_entities.base import Base


class ZoneDB(Base):
    __tablename__ = "zones"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    boundary: Mapped[Any | None] = mapped_column(JSONB)
    assignment_rule: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dbo.dictionary.id")
    )
    status: Mapped[int] = mapped_column(BigInteger, ForeignKey("dbo.dictionary.id"))


class ZoneUserDB(Base):
    """Membership of a user in a zone."""

    __tablename__ = "zones_users"

    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dbo.zones.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dbo.users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
