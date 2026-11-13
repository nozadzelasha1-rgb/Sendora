import uuid
from datetime import date, datetime

from sqlalchemy import UUID, Boolean, Date, DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db_entities.base import Base
from app.utils.time_utils import get_local_time


class UserDB(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "personal"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(Text)
    birth_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_local_time
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_local_time
    )
