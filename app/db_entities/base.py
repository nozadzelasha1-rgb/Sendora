from typing import Any

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # Inherited by every model. A model that defines its own __table_args__
    # must include the schema itself.
    __table_args__: Any = {"schema": "dbo"}  # noqa: RUF012 - SQLAlchemy attribute
