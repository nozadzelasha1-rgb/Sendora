import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.core import settings
from app.utils.constant import ADMIN_OPERATOR_ROLE_ID, SUPER_ADMIN_ROLE_ID
from tests.seed import TEST_ORG_ID, TEST_ROLE_ID

USERS_URL = f"{settings.API_PREFIX}/users"
ZONES_URL = f"{settings.API_PREFIX}/zones"
PASSWORD = "password123"
INVALID_DETAIL = "Invalid authentication credentials"
FORBIDDEN_DETAIL = "Access denied"
NO_DATA_DETAIL = "No zones available"
NOT_FOUND_DETAIL = "Zone not found"
UNKNOWN_REFERENCE = 987654

BearerHeaders = Callable[..., Awaitable[dict[str, str]]]


async def _login_with_user(
    client: AsyncClient,
    bearer_headers: BearerHeaders,
    name: str,
    role: int,
    zone_id: str | None = None,
) -> dict[str, str]:
    payload: dict[str, Any] = {
        "name": name,
        "password": PASSWORD,
        "role": role,
        "organization_id": str(TEST_ORG_ID),
    }
    if zone_id is not None:
        payload["zone_id"] = zone_id
    response = await client.post(USERS_URL, json=payload)
    assert response.status_code == 201, response.text
    return await bearer_headers(name)


async def _admin(client: AsyncClient, bearer_headers: BearerHeaders) -> dict[str, str]:
    return await _login_with_user(client, bearer_headers, "admin", SUPER_ADMIN_ROLE_ID)


async def _create_zone(
    client: AsyncClient, headers: dict[str, str], name: str = "Central"
) -> dict[str, Any]:
    response = await client.post(
        ZONES_URL,
        json={"name": name, "city": "Tbilisi", "status": TEST_ROLE_ID},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _assert_invalid(response: Response) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_DETAIL}
    assert response.headers["WWW-Authenticate"] == "Bearer"


# --- authentication -------------------------------------------------------------

_SOME_ID = "00000000-0000-4000-8000-0000000000bb"
_ENDPOINTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", ZONES_URL, {"name": "Central", "city": "Tbilisi", "status": TEST_ROLE_ID}),
    ("GET", ZONES_URL, None),
    ("GET", f"{ZONES_URL}/{_SOME_ID}", None),
    ("PATCH", f"{ZONES_URL}/{_SOME_ID}", {"name": "New"}),
]


@pytest.mark.parametrize(("method", "url", "body"), _ENDPOINTS)
async def test_endpoint_without_token_returns_401(
    client: AsyncClient, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = await client.request(method, url, json=body)

    _assert_invalid(response)


# --- role access ----------------------------------------------------------------


async def test_ordinary_role_cannot_manage_zones(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _login_with_user(client, bearer_headers, "bob", TEST_ROLE_ID)
    zone = await _create_zone(client, await _admin(client, bearer_headers))

    create = await client.post(
        ZONES_URL,
        json={"name": "Other", "city": "Batumi", "status": TEST_ROLE_ID},
        headers=headers,
    )
    get_one = await client.get(f"{ZONES_URL}/{zone['id']}", headers=headers)
    patch = await client.patch(
        f"{ZONES_URL}/{zone['id']}", json={"name": "New"}, headers=headers
    )

    for response in (create, get_one, patch):
        assert response.status_code == 403
        assert response.json() == {"detail": FORBIDDEN_DETAIL}


@pytest.mark.parametrize("admin_role", [SUPER_ADMIN_ROLE_ID, ADMIN_OPERATOR_ROLE_ID])
async def test_admin_roles_can_create_and_get_zone(
    client: AsyncClient, bearer_headers: BearerHeaders, admin_role: int
) -> None:
    headers = await _login_with_user(client, bearer_headers, "carol", admin_role)

    created = await _create_zone(client, headers)
    response = await client.get(f"{ZONES_URL}/{created['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


# --- create / get / update ------------------------------------------------------


async def test_create_with_unknown_status_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)

    response = await client.post(
        ZONES_URL,
        json={"name": "Central", "city": "Tbilisi", "status": UNKNOWN_REFERENCE},
        headers=headers,
    )

    assert response.status_code == 422


async def test_get_unknown_zone_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)

    response = await client.get(f"{ZONES_URL}/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND_DETAIL}


async def test_patch_zone_changes_only_sent_fields(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)
    zone = await _create_zone(client, headers)

    response = await client.patch(
        f"{ZONES_URL}/{zone['id']}", json={"name": "Renamed"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["city"] == "Tbilisi"


async def test_patch_unknown_status_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)
    zone = await _create_zone(client, headers)

    response = await client.patch(
        f"{ZONES_URL}/{zone['id']}",
        json={"status": UNKNOWN_REFERENCE},
        headers=headers,
    )

    assert response.status_code == 422


async def test_patch_unknown_zone_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)

    response = await client.patch(
        f"{ZONES_URL}/{uuid.uuid4()}", json={"name": "Renamed"}, headers=headers
    )

    assert response.status_code == 404


# --- GET /zones (role-based visibility) -----------------------------------------


async def test_admin_list_returns_every_zone(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)
    first = await _create_zone(client, headers, name="First")
    second = await _create_zone(client, headers, name="Second")

    response = await client.get(ZONES_URL, headers=headers)

    assert response.status_code == 200
    assert {zone["id"] for zone in response.json()} == {first["id"], second["id"]}


async def test_ordinary_user_list_returns_only_own_zone(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    admin_headers = await _admin(client, bearer_headers)
    own = await _create_zone(client, admin_headers, name="Own")
    await _create_zone(client, admin_headers, name="Other")
    user_headers = await _login_with_user(
        client, bearer_headers, "dave", TEST_ROLE_ID, zone_id=own["id"]
    )

    response = await client.get(ZONES_URL, headers=user_headers)

    assert response.status_code == 200
    assert [zone["id"] for zone in response.json()] == [own["id"]]


async def test_ordinary_user_without_zone_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    admin_headers = await _admin(client, bearer_headers)
    await _create_zone(client, admin_headers)
    user_headers = await _login_with_user(client, bearer_headers, "erin", TEST_ROLE_ID)

    response = await client.get(ZONES_URL, headers=user_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": NO_DATA_DETAIL}


async def test_admin_list_with_no_zones_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)

    response = await client.get(ZONES_URL, headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": NO_DATA_DETAIL}
