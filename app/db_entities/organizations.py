import uuid
from decimal import Decimal

from sqlalchemy import (
    UUID,
    BigInteger,
    Boolean,
    ForeignKey,
    Numeric,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db_entities.base import Base


class OrganizationDB(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[int] = mapped_column(BigInteger, ForeignKey("dbo.dictionary.id"))
    delivery_fee_gel: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class OrganizationUserDB(Base):
    """Membership of a user in an organization."""

    __tablename__ = "organizations_users"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dbo.organizations.id"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dbo.users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
