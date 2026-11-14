import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.seed import seed_references


def _test_database_url() -> str:
    """Return TEST_DATABASE_URL, refusing to run against a non-test database."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.exit("TEST_DATABASE_URL is not set; refusing to run tests", returncode=2)
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.exit(
            "TEST_DATABASE_URL must point to a database ending with _test", returncode=2
        )
    return url


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(_test_database_url(), poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Session bound to an outer transaction that is rolled back after each test."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
            autoflush=False,
        ) as db_session:
            await seed_references(db_session)
            yield db_session
        await outer.rollback()
