import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.utils.constant import ADMIN_OPERATOR_ROLE_ID, SUPER_ADMIN_ROLE_ID
from tests.seed import TEST_ORG_ID, TEST_ROLE_ID

USERS_URL = f"{settings.API_PREFIX}/users"
ORDERS_URL = f"{settings.API_PREFIX}/orders"
PASSWORD = "password123"
INVALID_DETAIL = "Invalid authentication credentials"
FORBIDDEN_DETAIL = "Access denied"
NOT_FOUND_DETAIL = "Order not found"
UNKNOWN_REFERENCE_DETAIL = "Unknown order reference"
UNKNOWN_SERVICE = 987654
OTHER_ORG_ID = "00000000-0000-4000-8000-00000000a003"

BearerHeaders = Callable[..., Awaitable[dict[str, str]]]


async def _user(
    client: AsyncClient,
    bearer_headers: BearerHeaders,
    name: str,
    role: int = TEST_ROLE_ID,
    organization_id: str = str(TEST_ORG_ID),
    phone: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Create a user through the API, log in and return (user id, Authorization header)."""
    payload: dict[str, Any] = {
        "name": name,
        "password": PASSWORD,
        "role": role,
        "organization_id": organization_id,
    }
    if phone is not None:
        payload["phone"] = phone
    response = await client.post(USERS_URL, json=payload)
    assert response.status_code == 201, response.text
    headers = await bearer_headers(name)
    return str(response.json()["id"]), headers


def _order_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "service_type": TEST_ROLE_ID,
        "sender": {
            "sender_company": "Shop",
            "sender_contact": "Anna",
            "sender_phone": "+79990000001",
        },
        "recipient": {
            "recipient_name": "Boris",
            "recipient_phone": "+79990000002",
            "delivery_address": "Rustaveli 1",
            "city": "Tbilisi",
        },
        "parcel": {"parcel_type": TEST_ROLE_ID},
        "payment": {
            "delivery_payer": TEST_ROLE_ID,
            "delivery_fee_gel": "10.00",
            "currency": TEST_ROLE_ID,
        },
    }
    body.update(overrides)
    return body


async def _create_order(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        ORDERS_URL, json=_order_body(**overrides), headers=headers
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _admin(client: AsyncClient, bearer_headers: BearerHeaders) -> dict[str, str]:
    _, headers = await _user(client, bearer_headers, "admin", role=SUPER_ADMIN_ROLE_ID)
    return headers


# --- authentication ----------------------------------------------------------------

_SOME_ID = 999_999_999
_ENDPOINTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", ORDERS_URL, _order_body()),
    ("GET", ORDERS_URL, None),
    ("GET", f"{ORDERS_URL}/{_SOME_ID}", None),
    ("PATCH", f"{ORDERS_URL}/{_SOME_ID}", {"tracking_url": "https://example.test"}),
    ("PUT", f"{ORDERS_URL}/{_SOME_ID}/operation", {"route_id": "R1"}),
    ("POST", f"{ORDERS_URL}/{_SOME_ID}/status-history", {"status": TEST_ROLE_ID}),
    ("DELETE", f"{ORDERS_URL}/{_SOME_ID}", None),
]


@pytest.mark.parametrize(("method", "url", "body"), _ENDPOINTS)
async def test_endpoint_without_token_returns_401(
    client: AsyncClient, method: str, url: str, body: dict[str, Any] | None
) -> None:
    response = await client.request(method, url, json=body)
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_DETAIL}
    assert response.headers["WWW-Authenticate"] == "Bearer"


# --- create ----------------------------------------------------------------------


async def test_sender_creates_order_for_own_organization(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    _, headers = await _user(client, bearer_headers, "sender")
    body = await _create_order(client, headers, external_order_id="ext-http-1")

    assert body["status"] == 2
    assert body["partner_id"] == str(TEST_ORG_ID)
    assert body["tracking_number"].startswith("SND")
    assert body["sender"]["sender_company"] == "Shop"
    assert body["recipient"]["recipient_name"] == "Boris"
    assert len(body["status_history"]) == 1


async def test_sender_cannot_create_for_foreign_organization(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    _, headers = await _user(client, bearer_headers, "sender")
    response = await client.post(
        ORDERS_URL, json=_order_body(partner_id=OTHER_ORG_ID), headers=headers
    )
    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_create_with_unknown_reference_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    _, headers = await _user(client, bearer_headers, "sender")
    response = await client.post(
        ORDERS_URL, json=_order_body(service_type=UNKNOWN_SERVICE), headers=headers
    )
    assert response.status_code == 422
    assert response.json() == {"detail": UNKNOWN_REFERENCE_DETAIL}


async def test_create_with_missing_block_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    _, headers = await _user(client, bearer_headers, "sender")
    body = _order_body()
    del body["sender"]
    response = await client.post(ORDERS_URL, json=body, headers=headers)
    assert response.status_code == 422


# --- read and visibility -----------------------------------------------------------


async def test_stranger_gets_404_for_order(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, sender = await _user(client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    await _ensure_other_org(session)
    _, stranger = await _user(
        client, bearer_headers, "stranger", organization_id=OTHER_ORG_ID
    )
    response = await client.get(f"{ORDERS_URL}/{created['id']}", headers=stranger)
    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND_DETAIL}


async def test_internal_operation_fields_hidden_from_sender(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    admin = await _admin(client, bearer_headers)
    _, sender = await _user(client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    response = await client.put(
        f"{ORDERS_URL}/{created['id']}/operation",
        json={"carrier_id": "C1", "route_id": "R9", "internal_comment": "secret"},
        headers=admin,
    )
    assert response.status_code == 200, response.text

    as_sender = await client.get(f"{ORDERS_URL}/{created['id']}", headers=sender)
    assert as_sender.json()["operation"]["carrier_id"] is None
    assert as_sender.json()["operation"]["internal_comment"] is None

    as_admin = await client.get(f"{ORDERS_URL}/{created['id']}", headers=admin)
    assert as_admin.json()["operation"]["carrier_id"] == "C1"
    assert as_admin.json()["operation"]["internal_comment"] == "secret"


async def test_list_returns_total_count_header(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    _, sender = await _user(client, bearer_headers, "sender")
    await _create_order(client, sender)
    await _create_order(client, sender)
    response = await client.get(f"{ORDERS_URL}?limit=1", headers=sender)
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "2"
    assert len(response.json()) == 1


async def test_list_rejects_invalid_limit(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    headers = await _admin(client, bearer_headers)
    response = await client.get(f"{ORDERS_URL}?limit=0", headers=headers)
    assert response.status_code == 422


# --- update ----------------------------------------------------------------------


async def _ensure_other_org(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO dbo.organizations (id, name, type) "
            "VALUES (:id, 'other_org', :type_id) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": uuid.UUID(OTHER_ORG_ID), "type_id": TEST_ROLE_ID},
    )
    await session.commit()


async def test_recipient_cannot_update_order(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    await _ensure_other_org(session)
    _, recipient = await _user(
        client,
        bearer_headers,
        "recipient",
        organization_id=OTHER_ORG_ID,
        phone="+79990000002",
    )
    _, sender = await _user(client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    response = await client.patch(
        f"{ORDERS_URL}/{created['id']}",
        json={"tracking_url": "https://example.test/x"},
        headers=recipient,
    )
    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_recipient_sees_order_he_is_waiting_for(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    await _ensure_other_org(session)
    _, recipient = await _user(
        client,
        bearer_headers,
        "recipient",
        organization_id=OTHER_ORG_ID,
        phone="+79990000002",
    )
    _, sender = await _user(client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    response = await client.get(f"{ORDERS_URL}/{created['id']}", headers=recipient)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_admin_assigns_courier_who_then_changes_status(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    admin = await _admin(client, bearer_headers)
    _, sender = await _user(client, bearer_headers, "sender")
    courier_id, courier = await _user(client, bearer_headers, "courier")
    created = await _create_order(client, sender)

    patched = await client.patch(
        f"{ORDERS_URL}/{created['id']}", json={"courier_id": courier_id}, headers=admin
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["courier_id"] == courier_id

    status_response = await client.post(
        f"{ORDERS_URL}/{created['id']}/status-history",
        json={"status": TEST_ROLE_ID, "comment": "picked up"},
        headers=courier,
    )
    assert status_response.status_code == 201, status_response.text
    assert status_response.json()["comment"] == "picked up"


async def test_sender_cannot_add_status(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    _, sender = await _user(client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    response = await client.post(
        f"{ORDERS_URL}/{created['id']}/status-history",
        json={"status": TEST_ROLE_ID},
        headers=sender,
    )
    assert response.status_code == 403


# --- delete (soft cancel) -------------------------------------------------------------


async def test_manager_cannot_cancel_order(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    admin = await _admin(client, bearer_headers)
    manager_id, manager = await _user(client, bearer_headers, "manager")
    _, sender = await _user(client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    await client.put(
        f"{ORDERS_URL}/{created['id']}/operation",
        json={"manager_id": manager_id},
        headers=admin,
    )
    response = await client.delete(f"{ORDERS_URL}/{created['id']}", headers=manager)
    assert response.status_code == 403


async def test_admin_cancels_order_idempotently(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    admin = await _admin(client, bearer_headers)
    _, sender = await _user(client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    first: Response = await client.delete(
        f"{ORDERS_URL}/{created['id']}", headers=admin
    )
    second: Response = await client.delete(
        f"{ORDERS_URL}/{created['id']}", headers=admin
    )
    assert first.status_code == 204
    assert second.status_code == 204

    fetched = await client.get(f"{ORDERS_URL}/{created['id']}", headers=admin)
    assert fetched.json()["status"] == 1
    cancelled = [
        item for item in fetched.json()["status_history"] if item["status"] == 1
    ]
    assert len(cancelled) == 1


async def test_admin_operator_role_is_also_admin(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    _, operator = await _user(
        client, bearer_headers, "operator", role=ADMIN_OPERATOR_ROLE_ID
    )
    _, sender = await _user(client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    response = await client.delete(f"{ORDERS_URL}/{created['id']}", headers=operator)
    assert response.status_code == 204
