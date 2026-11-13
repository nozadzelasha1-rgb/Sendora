import app.db_entities  # noqa: F401  # registers every model on Base.metadata
from app.db_entities.base import Base

EXPECTED_SCHEMA = "dbo"


def test_all_tables_use_dbo_schema() -> None:
    assert Base.metadata.sorted_tables
    wrong = [
        t.fullname for t in Base.metadata.sorted_tables if t.schema != EXPECTED_SCHEMA
    ]
    assert wrong == []


def test_all_foreign_keys_target_dbo_schema() -> None:
    targets = [
        fk.target_fullname
        for table in Base.metadata.sorted_tables
        for fk in table.foreign_keys
    ]
    assert targets
    wrong = [t for t in targets if not t.startswith(f"{EXPECTED_SCHEMA}.")]
    assert wrong == []
