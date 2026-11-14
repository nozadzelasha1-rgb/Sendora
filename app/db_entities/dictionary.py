from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db_entities.base import Base


class DictionarySpecDB(Base):
    __tablename__ = "dictionary_spec"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)


class DictionaryDB(Base):
    __tablename__ = "dictionary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    spec_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dbo.dictionary_spec.id")
    )
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
