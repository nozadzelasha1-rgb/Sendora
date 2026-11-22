import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response

from app.core import settings
from app.utils.constant import ADMIN_OPERATOR_ROLE_ID, SUPER_ADMIN_ROLE_ID
from tests.seed import TEST_ROLE_ID

USERS_URL = f"{settings.API_PREFIX}/users"
ORGS_URL = f"{settings.API_PREFIX}/organizations"
PASSWORD = "password123"
INVALID_DETAIL = "Invalid authentication credentials"
FORBIDDEN_DETAIL = "Access denied"
UNKNOWN_TYPE = 987654

BearerHeaders = Callable[..., Awaitable[dict[str, str]]]


async def _login_with_role(
    client: AsyncClient, bearer_headers: BearerHeaders, name: str, role: int
) -> dict[str, str]:
    response = await client.post(
        USERS_URL, json={"name": name, "password": PASSWORD, "role": role}
    )
    assert response.status_code == 201, response.text
    return await bearer_headers(name)


async def _auth(client: AsyncClient, bearer_headers: BearerHeaders) -> dict[str, str]:
    return await _login_with_role(client, bearer_headers, "alice", SUPER_ADMIN_ROLE_ID)


async def _create_org(
    client: AsyncClient, headers: dict[str, str], name: str = "Acme", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        ORGS_URL, json={"name": name, "type": TEST_ROLE_ID, **extra}, headers=headers
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _assert_invalid(response: Response) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_DETAIL}
    assert response.headers["WWW-Authenticate"] == "Bearer"


# --- authentication -------------------------------------------------------------

_SOME_ID = "00000000-0000-4000-8000-0000000000aa"
_ENDPOINTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", ORGS_URL, {"name": "Acme", "type": TEST_ROLE_ID}),
    ("GET", ORGS_URL, None),
    ("GET", f"{ORGS_URL}/{_SOME_ID}", None),
    ("PATCH", f"{ORGS_URL}/{_SOME_ID}", {"name": "New"}),
    ("DELETE", f"{ORGS_URL}/{_SOME_ID}", None),
    ("POST", f"{ORGS_URL}/{_SOME_ID}/users", {"user_id": _SOME_ID}),
    ("DELETE", f"{ORGS_URL}/{_SOME_ID}/users/{_SOME_ID}", None),
]


@pytest.mark.parametrize(("method", "url", "body"), _ENDPOINTS)
async def test_endpoint_without_token_returns_401(
    client: AsyncClient, method: str, url: str, body: dict[str, Any] | None
) -> None:
    _assert_invalid(await client.request(method, url, json=body))


@pytest.mark.parametrize(("method", "url", "body"), _ENDPOINTS)
async def test_endpoint_with_bad_token_returns_401(
    client: AsyncClient, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = await client.request(
        method, url, json=body, headers={"Authorization": "Bearer not-a-token"}
    )

    _assert_invalid(response)


# --- role gate (super_admin and admin_operator only) ---------------------------


@pytest.mark.parametrize(("method", "url", "body"), _ENDPOINTS)
async def test_endpoint_with_disallowed_role_returns_403(
    client: AsyncClient,
    bearer_headers: BearerHeaders,
    method: str,
    url: str,
    body: dict[str, Any] | None,
) -> None:
    headers = await _login_with_role(client, bearer_headers, "plain_user", TEST_ROLE_ID)

    response = await client.request(method, url, json=body, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_admin_operator_can_use_all_endpoints(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _login_with_role(
        client, bearer_headers, "operator", ADMIN_OPERATOR_ROLE_ID
    )

    created = await _create_org(client, headers, name="Ops Org")
    fetched = await client.get(f"{ORGS_URL}/{created['id']}", headers=headers)
    listed = await client.get(ORGS_URL, headers=headers)
    patched = await client.patch(
        f"{ORGS_URL}/{created['id']}", json={"name": "Ops Org 2"}, headers=headers
    )
    deleted = await client.delete(f"{ORGS_URL}/{created['id']}", headers=headers)

    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert patched.status_code == 200
    assert deleted.status_code == 204


# --- create ---------------------------------------------------------------------


async def test_create_returns_201_with_organization(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)

    response = await client.post(
        ORGS_URL,
        json={
            "name": "  Acme  ",
            "type": TEST_ROLE_ID,
            "delivery_fee_gel": "4.50",
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["name"] == "Acme"
    assert body["type"] == TEST_ROLE_ID
    assert "contact" not in body
    assert "phone" not in body
    assert float(body["delivery_fee_gel"]) == 4.5
    assert body["active"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"type": TEST_ROLE_ID},
        {"name": "Acme"},
        {"name": "", "type": TEST_ROLE_ID},
        {"name": "Acme", "type": TEST_ROLE_ID, "delivery_fee_gel": "-1"},
        {"name": "Acme", "type": TEST_ROLE_ID, "delivery_fee_gel": "1.234"},
    ],
)
async def test_create_invalid_body_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders, payload: dict[str, Any]
) -> None:
    headers = await _auth(client, bearer_headers)

    response = await client.post(ORGS_URL, json=payload, headers=headers)

    assert response.status_code == 422


async def test_create_unknown_type_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)

    response = await client.post(
        ORGS_URL, json={"name": "Acme", "type": UNKNOWN_TYPE}, headers=headers
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unknown organization type"}


# --- get ------------------------------------------------------------------------


async def test_get_returns_organization(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    created = await _create_org(client, headers)

    response = await client.get(f"{ORGS_URL}/{created['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json() == created


async def test_get_unknown_id_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)

    response = await client.get(f"{ORGS_URL}/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Organization not found"}


async def test_get_invalid_id_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)

    response = await client.get(f"{ORGS_URL}/not-a-uuid", headers=headers)

    assert response.status_code == 422


# --- list -----------------------------------------------------------------------


async def test_list_contains_created_organization(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    created = await _create_org(client, headers, name="zz-router-list")

    response = await client.get(ORGS_URL, params={"limit": 100}, headers=headers)

    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert created in items


async def test_list_limit_is_respected(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    await _create_org(client, headers, name="zz-limit-a")
    await _create_org(client, headers, name="zz-limit-b")

    response = await client.get(ORGS_URL, params={"limit": 1}, headers=headers)

    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"active": "maybe"}],
)
async def test_list_invalid_query_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders, params: dict[str, Any]
) -> None:
    headers = await _auth(client, bearer_headers)

    response = await client.get(ORGS_URL, params=params, headers=headers)

    assert response.status_code == 422


# --- update ---------------------------------------------------------------------


async def test_patch_changes_only_sent_fields(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    created = await _create_org(client, headers, delivery_fee_gel="4.50")

    response = await client.patch(
        f"{ORGS_URL}/{created['id']}", json={"name": "Renamed"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert float(body["delivery_fee_gel"]) == 4.5
    assert body["id"] == created["id"]


async def test_patch_empty_body_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    created = await _create_org(client, headers)

    response = await client.patch(
        f"{ORGS_URL}/{created['id']}", json={}, headers=headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["name", "type", "active"])
async def test_patch_null_non_nullable_field_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders, field: str
) -> None:
    headers = await _auth(client, bearer_headers)
    created = await _create_org(client, headers)

    response = await client.patch(
        f"{ORGS_URL}/{created['id']}", json={field: None}, headers=headers
    )

    assert response.status_code == 422


async def test_patch_unknown_type_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    created = await _create_org(client, headers)

    response = await client.patch(
        f"{ORGS_URL}/{created['id']}", json={"type": UNKNOWN_TYPE}, headers=headers
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Unknown organization type"}


async def test_patch_unknown_id_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)

    response = await client.patch(
        f"{ORGS_URL}/{uuid.uuid4()}", json={"name": "Nobody"}, headers=headers
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Organization not found"}


# --- delete ---------------------------------------------------------------------


async def test_delete_is_soft_and_visible_through_filters(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    created = await _create_org(client, headers, name="zz-soft-delete")
    url = f"{ORGS_URL}/{created['id']}"

    response = await client.delete(url, headers=headers)

    assert response.status_code == 204
    assert response.content == b""
    fetched = await client.get(url, headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["active"] is False
    active = await client.get(ORGS_URL, params={"limit": 100}, headers=headers)
    assert created["id"] not in {item["id"] for item in active.json()}
    inactive = await client.get(
        ORGS_URL, params={"limit": 100, "active": "false"}, headers=headers
    )
    assert created["id"] in {item["id"] for item in inactive.json()}


async def test_delete_twice_returns_204_both_times(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    created = await _create_org(client, headers)
    url = f"{ORGS_URL}/{created['id']}"

    first = await client.delete(url, headers=headers)
    second = await client.delete(url, headers=headers)

    assert first.status_code == 204
    assert second.status_code == 204


async def test_delete_unknown_id_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)

    response = await client.delete(f"{ORGS_URL}/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Organization not found"}


async def test_patch_reactivates_deleted_organization(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    created = await _create_org(client, headers)
    url = f"{ORGS_URL}/{created['id']}"
    await client.delete(url, headers=headers)

    response = await client.patch(url, json={"active": True}, headers=headers)

    assert response.status_code == 200
    assert response.json()["active"] is True


# --- organization membership ----------------------------------------------------------


async def _new_user_id(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    response = await client.post(
        USERS_URL,
        json={"name": name, "password": PASSWORD, "role": TEST_ROLE_ID},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    user_id: str = response.json()["id"]
    return user_id


async def test_admin_adds_and_removes_organization_member(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    org = await _create_org(client, headers)
    user_id = await _new_user_id(client, headers, "member")
    url = f"{ORGS_URL}/{org['id']}/users"

    added = await client.post(url, json={"user_id": user_id}, headers=headers)
    assert added.status_code == 201, added.text
    assert added.json() == {"organization_id": org["id"], "user_id": user_id}

    removed = await client.delete(f"{url}/{user_id}", headers=headers)
    assert removed.status_code == 204

    again = await client.delete(f"{url}/{user_id}", headers=headers)
    assert again.status_code == 404
    assert again.json() == {"detail": "User is not a member of the organization"}


async def test_adding_same_organization_member_twice_returns_409(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    org = await _create_org(client, headers)
    user_id = await _new_user_id(client, headers, "member")
    url = f"{ORGS_URL}/{org['id']}/users"
    await client.post(url, json={"user_id": user_id}, headers=headers)

    response = await client.post(url, json={"user_id": user_id}, headers=headers)

    assert response.status_code == 409


async def test_adding_to_unknown_organization_or_user_returns_404(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _auth(client, bearer_headers)
    org = await _create_org(client, headers)
    user_id = await _new_user_id(client, headers, "member")

    unknown_org = await client.post(
        f"{ORGS_URL}/{_SOME_ID}/users", json={"user_id": user_id}, headers=headers
    )
    assert unknown_org.status_code == 404
    assert unknown_org.json() == {"detail": "Organization not found"}

    unknown_user = await client.post(
        f"{ORGS_URL}/{org['id']}/users", json={"user_id": _SOME_ID}, headers=headers
    )
    assert unknown_user.status_code == 404
    assert unknown_user.json() == {"detail": "User not found"}


async def test_ordinary_user_cannot_change_organization_members(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    admin = await _auth(client, bearer_headers)
    org = await _create_org(client, admin)
    user_headers = await _login_with_role(client, bearer_headers, "bob", TEST_ROLE_ID)
    user_id = await _new_user_id(client, admin, "carol")

    response = await client.post(
        f"{ORGS_URL}/{org['id']}/users", json={"user_id": user_id}, headers=user_headers
    )

    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}
