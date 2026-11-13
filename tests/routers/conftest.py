from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.core.db_connector import get_session
from app.routers import app

PASSWORD = "password123"
LOGIN_URL = f"{settings.API_PREFIX}/users/login"


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client whose requests share the savepoint-scoped test session."""

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def bearer_headers(client: AsyncClient) -> Callable[..., Awaitable[dict[str, str]]]:
    """Log in through the API and return an Authorization header for the user."""

    async def _headers(name: str = "alice", password: str = PASSWORD) -> dict[str, str]:
        response = await client.post(
            LOGIN_URL, json={"name": name, "password": password}
        )
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _headers
