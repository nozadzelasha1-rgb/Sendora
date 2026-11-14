import uuid
from datetime import datetime

from sqlalchemy import UUID, DateTime, ForeignKey, LargeBinary, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db_entities.base import Base


class UserSessionDB(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dbo.users.id", ondelete="CASCADE"),
        index=True,
    )
    refresh_token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    previous_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(20))
