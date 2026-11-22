from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.utils.constant import ADMIN_OPERATOR_ROLE_ID, SUPER_ADMIN_ROLE_ID
from tests.seed import TEST_ROLE_ID, TEST_SPEC_ID

USERS_URL = f"{settings.API_PREFIX}/users"
DICT_URL = f"{settings.API_PREFIX}/dictionaries"
PASSWORD = "password123"
INVALID_DETAIL = "Invalid authentication credentials"
FORBIDDEN_DETAIL = "Access denied"
SPEC_NOT_FOUND_DETAIL = "Dictionary spec not found"
ITEM_NOT_FOUND_DETAIL = "Dictionary item not found"
IN_USE_DETAIL = "Dictionary item is in use"
PROTECTED_DETAIL = "Protected dictionary item cannot be deleted"
UNKNOWN_ID = 999_999

BearerHeaders = Callable[..., Awaitable[dict[str, str]]]


@pytest_asyncio.fixture(autouse=True)
async def _advance_dictionary_sequence(
    session: AsyncSession,
) -> AsyncGenerator[None, None]:
    """Seed rows use explicit ids; move the identity past them so new rows do not collide."""
    await session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('dbo.dictionary', 'id'), 1000, true)"
        )
    )
    yield


async def _login(
    client: AsyncClient, bearer_headers: BearerHeaders, name: str, role: int
) -> dict[str, str]:
    response = await client.post(
        USERS_URL, json={"name": name, "password": PASSWORD, "role": role}
    )
    assert response.status_code == 201, response.text
    return await bearer_headers(name)


async def _admin(client: AsyncClient, bearer_headers: BearerHeaders) -> dict[str, str]:
    return await _login(client, bearer_headers, "admin", SUPER_ADMIN_ROLE_ID)


# --- authentication --------------------------------------------------------------

_ENDPOINTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", DICT_URL, None),
    ("GET", f"{DICT_URL}/{TEST_SPEC_ID}", None),
    ("GET", f"{DICT_URL}/{TEST_SPEC_ID}/{TEST_ROLE_ID}", None),
    ("POST", f"{DICT_URL}/{TEST_SPEC_ID}", {"name": "New"}),
    ("PATCH", f"{DICT_URL}/{TEST_SPEC_ID}/{TEST_ROLE_ID}", {"name": "New"}),
    ("DELETE", f"{DICT_URL}/{TEST_SPEC_ID}/{TEST_ROLE_ID}", None),
]


@pytest.mark.parametrize(("method", "url", "body"), _ENDPOINTS)
async def test_endpoint_without_token_returns_401(
    client: AsyncClient, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = await client.request(method, url, json=body)
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_DETAIL}


# --- read: any authenticated user --------------------------------------------------


async def test_ordinary_user_reads_specs_and_items(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _login(client, bearer_headers, "reader", TEST_ROLE_ID)

    specs = await client.get(DICT_URL, headers=headers)
    assert specs.status_code == 200
    assert TEST_SPEC_ID in {spec["id"] for spec in specs.json()}

    items = await client.get(f"{DICT_URL}/{TEST_SPEC_ID}", headers=headers)
    assert items.status_code == 200
    assert TEST_ROLE_ID in {item["id"] for item in items.json()}

    item = await client.get(
        f"{DICT_URL}/{TEST_SPEC_ID}/{TEST_ROLE_ID}", headers=headers
    )
    assert item.status_code == 200
    assert item.json()["spec_id"] == TEST_SPEC_ID


async def test_unknown_spec_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _login(client, bearer_headers, "reader", TEST_ROLE_ID)
    response = await client.get(f"{DICT_URL}/{UNKNOWN_ID}", headers=headers)
    assert response.status_code == 404
    assert response.json() == {"detail": SPEC_NOT_FOUND_DETAIL}


async def test_unknown_item_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _login(client, bearer_headers, "reader", TEST_ROLE_ID)
    response = await client.get(
        f"{DICT_URL}/{TEST_SPEC_ID}/{UNKNOWN_ID}", headers=headers
    )
    assert response.status_code == 404
    assert response.json() == {"detail": ITEM_NOT_FOUND_DETAIL}


# --- write: admins only ----------------------------------------------------------


async def test_ordinary_user_cannot_write(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _login(client, bearer_headers, "writer", TEST_ROLE_ID)
    item_url = f"{DICT_URL}/{TEST_SPEC_ID}/{TEST_ROLE_ID}"

    created = await client.post(
        f"{DICT_URL}/{TEST_SPEC_ID}", json={"name": "New"}, headers=headers
    )
    updated = await client.patch(item_url, json={"name": "New"}, headers=headers)
    deleted = await client.delete(item_url, headers=headers)

    for response in (created, updated, deleted):
        assert response.status_code == 403
        assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_admin_creates_updates_and_deletes_item(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)

    created = await client.post(
        f"{DICT_URL}/{TEST_SPEC_ID}",
        json={"name": "  Night  ", "description": "after 22:00"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Night"
    assert body["description"] == "after 22:00"
    assert body["spec_id"] == TEST_SPEC_ID
    item_url = f"{DICT_URL}/{TEST_SPEC_ID}/{body['id']}"

    renamed = await client.patch(item_url, json={"name": "Late"}, headers=headers)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Late"
    assert renamed.json()["description"] == "after 22:00"

    deleted = await client.delete(item_url, headers=headers)
    assert deleted.status_code == 204

    gone = await client.get(item_url, headers=headers)
    assert gone.status_code == 404


async def test_create_in_unknown_spec_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)
    response = await client.post(
        f"{DICT_URL}/{UNKNOWN_ID}", json={"name": "New"}, headers=headers
    )
    assert response.status_code == 404
    assert response.json() == {"detail": SPEC_NOT_FOUND_DETAIL}


async def test_create_with_blank_name_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)
    response = await client.post(
        f"{DICT_URL}/{TEST_SPEC_ID}", json={"name": "  "}, headers=headers
    )
    assert response.status_code == 422


async def test_delete_item_in_use_returns_409(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)
    response = await client.delete(
        f"{DICT_URL}/{TEST_SPEC_ID}/{TEST_ROLE_ID}", headers=headers
    )
    assert response.status_code == 409
    assert response.json() == {"detail": IN_USE_DETAIL}


async def test_delete_protected_item_returns_409(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)
    for protected_id in (SUPER_ADMIN_ROLE_ID, ADMIN_OPERATOR_ROLE_ID):
        response = await client.delete(
            f"{DICT_URL}/{TEST_SPEC_ID}/{protected_id}", headers=headers
        )
        assert response.status_code == 409
        assert response.json() == {"detail": PROTECTED_DETAIL}
