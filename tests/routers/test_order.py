import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.funcs.organization import Organization
from app.utils.constant import (
    ADMIN_OPERATOR_ROLE_ID,
    ORDER_STATUS_CANCELLED_ID,
    ORDER_STATUS_CREATED_ID,
    ORDER_STATUS_DELIVERED_ID,
    SUPER_ADMIN_ROLE_ID,
)
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


async def _ensure_org(session: AsyncSession, org_id: str) -> None:
    await session.execute(
        text(
            "INSERT INTO dbo.organizations (id, name, type) "
            "VALUES (:id, 'test_org', :type_id) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": uuid.UUID(org_id), "type_id": TEST_ROLE_ID},
    )
    await session.commit()


async def _user(
    session: AsyncSession,
    client: AsyncClient,
    bearer_headers: BearerHeaders,
    name: str,
    role: int = TEST_ROLE_ID,
    organization_id: str | None = str(TEST_ORG_ID),
) -> tuple[str, dict[str, str]]:
    """Create a user through the API, make it a member of the organization, log in.

    Return (user id, Authorization header).
    """
    response = await client.post(
        USERS_URL,
        json={"name": name, "password": PASSWORD, "role": role},
    )
    assert response.status_code == 201, response.text
    user_id = str(response.json()["id"])
    if organization_id is not None:
        await _ensure_org(session, organization_id)
        await Organization(session).add_user(
            uuid.UUID(organization_id), uuid.UUID(user_id)
        )
    headers = await bearer_headers(name)
    return user_id, headers


async def _admin(
    session: AsyncSession, client: AsyncClient, bearer_headers: BearerHeaders
) -> dict[str, str]:
    _, headers = await _user(
        session,
        client,
        bearer_headers,
        "admin",
        role=SUPER_ADMIN_ROLE_ID,
        organization_id=None,
    )
    return headers


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
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, headers = await _user(session, client, bearer_headers, "sender")
    body = await _create_order(client, headers)

    assert body["status"] == ORDER_STATUS_CREATED_ID
    assert body["organization_id"] == str(TEST_ORG_ID)
    assert "external_order_id" not in body
    assert body["tracking_number"].startswith("SND")
    assert body["sender"]["sender_company"] == "Shop"
    assert body["recipient"]["recipient_name"] == "Boris"
    assert "user_id" not in body["recipient"]
    assert len(body["status_history"]) == 1


async def test_sender_cannot_create_for_foreign_organization(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, headers = await _user(session, client, bearer_headers, "sender")
    await _ensure_org(session, OTHER_ORG_ID)
    response = await client.post(
        ORDERS_URL,
        json=_order_body(organization_id=OTHER_ORG_ID),
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_user_in_several_organizations_must_name_one(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    user_id, headers = await _user(session, client, bearer_headers, "multi")
    await _ensure_org(session, OTHER_ORG_ID)
    await Organization(session).add_user(uuid.UUID(OTHER_ORG_ID), uuid.UUID(user_id))

    response = await client.post(ORDERS_URL, json=_order_body(), headers=headers)
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Choose the organization the order is created for"
    }

    named = await _create_order(client, headers, organization_id=OTHER_ORG_ID)
    assert named["organization_id"] == OTHER_ORG_ID


async def test_admin_must_send_organization_id(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    admin = await _admin(session, client, bearer_headers)
    response = await client.post(ORDERS_URL, json=_order_body(), headers=admin)
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Choose the organization the order is created for"
    }


async def test_user_without_organization_gets_403_on_create(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, headers = await _user(
        session, client, bearer_headers, "loner", organization_id=None
    )
    response = await client.post(ORDERS_URL, json=_order_body(), headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_create_with_unknown_reference_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, headers = await _user(session, client, bearer_headers, "sender")
    response = await client.post(
        ORDERS_URL, json=_order_body(service_type=UNKNOWN_SERVICE), headers=headers
    )
    assert response.status_code == 422
    assert response.json() == {"detail": UNKNOWN_REFERENCE_DETAIL}


async def test_create_with_missing_block_returns_422(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, headers = await _user(session, client, bearer_headers, "sender")
    body = _order_body()
    del body["sender"]
    response = await client.post(ORDERS_URL, json=body, headers=headers)
    assert response.status_code == 422


# --- read and visibility -----------------------------------------------------------


async def test_stranger_gets_404_for_order(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, sender = await _user(session, client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    _, stranger = await _user(
        session, client, bearer_headers, "stranger", organization_id=OTHER_ORG_ID
    )
    response = await client.get(f"{ORDERS_URL}/{created['id']}", headers=stranger)
    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND_DETAIL}


async def test_member_of_second_organization_sees_its_orders(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    await _ensure_org(session, OTHER_ORG_ID)
    _, creator = await _user(
        session, client, bearer_headers, "creator", organization_id=OTHER_ORG_ID
    )
    created = await _create_order(client, creator, organization_id=OTHER_ORG_ID)

    viewer_id, viewer = await _user(session, client, bearer_headers, "viewer")
    await Organization(session).add_user(uuid.UUID(OTHER_ORG_ID), uuid.UUID(viewer_id))

    response = await client.get(f"{ORDERS_URL}/{created['id']}", headers=viewer)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_internal_operation_fields_hidden_from_sender(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    admin = await _admin(session, client, bearer_headers)
    _, sender = await _user(session, client, bearer_headers, "sender")
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
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, sender = await _user(session, client, bearer_headers, "sender")
    await _create_order(client, sender)
    await _create_order(client, sender)
    response = await client.get(f"{ORDERS_URL}?limit=1", headers=sender)
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "2"
    assert len(response.json()) == 1


async def test_list_rejects_invalid_limit(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    headers = await _admin(session, client, bearer_headers)
    response = await client.get(f"{ORDERS_URL}?limit=0", headers=headers)
    assert response.status_code == 422


# --- update ----------------------------------------------------------------------


async def test_user_outside_organization_cannot_update_order(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, outsider = await _user(
        session, client, bearer_headers, "outsider", organization_id=OTHER_ORG_ID
    )
    _, sender = await _user(session, client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    response = await client.patch(
        f"{ORDERS_URL}/{created['id']}",
        json={"tracking_url": "https://example.test/x"},
        headers=outsider,
    )
    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND_DETAIL}


async def test_admin_assigns_courier_who_then_changes_status(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    admin = await _admin(session, client, bearer_headers)
    _, sender = await _user(session, client, bearer_headers, "sender")
    courier_id, courier = await _user(session, client, bearer_headers, "courier")
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
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, sender = await _user(session, client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    response = await client.post(
        f"{ORDERS_URL}/{created['id']}/status-history",
        json={"status": TEST_ROLE_ID},
        headers=sender,
    )
    assert response.status_code == 403


# --- delete (soft cancel) -------------------------------------------------------------


async def test_manager_cannot_cancel_order(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    admin = await _admin(session, client, bearer_headers)
    manager_id, manager = await _user(session, client, bearer_headers, "manager")
    _, sender = await _user(session, client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    await client.put(
        f"{ORDERS_URL}/{created['id']}/operation",
        json={"manager_id": manager_id},
        headers=admin,
    )
    response = await client.delete(f"{ORDERS_URL}/{created['id']}", headers=manager)
    assert response.status_code == 403


async def test_admin_cancels_order_idempotently(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    admin = await _admin(session, client, bearer_headers)
    _, sender = await _user(session, client, bearer_headers, "sender")
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
    assert fetched.json()["status"] == ORDER_STATUS_CANCELLED_ID
    cancelled = [
        item
        for item in fetched.json()["status_history"]
        if item["status"] == ORDER_STATUS_CANCELLED_ID
    ]
    assert len(cancelled) == 1


async def test_admin_operator_role_is_also_admin(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    _, operator = await _user(
        session,
        client,
        bearer_headers,
        "operator",
        role=ADMIN_OPERATOR_ROLE_ID,
        organization_id=None,
    )
    _, sender = await _user(session, client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    response = await client.delete(f"{ORDERS_URL}/{created['id']}", headers=operator)
    assert response.status_code == 204


# --- list filter by user ----------------------------------------------------------


async def test_admin_filters_list_by_user_id(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    member_id, member = await _user(session, client, bearer_headers, "member")
    await _create_order(client, member)
    admin = await _admin(session, client, bearer_headers)

    response = await client.get(f"{ORDERS_URL}?user_id={member_id}", headers=admin)

    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "1"


async def test_non_admin_cannot_list_another_users_orders(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    other_id, _ = await _user(session, client, bearer_headers, "other")
    _, viewer = await _user(session, client, bearer_headers, "viewer")

    response = await client.get(f"{ORDERS_URL}?user_id={other_id}", headers=viewer)

    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_list_rejects_malformed_user_id(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    admin = await _admin(session, client, bearer_headers)
    response = await client.get(f"{ORDERS_URL}?user_id=not-a-uuid", headers=admin)
    assert response.status_code == 422


# --- delivered_at ----------------------------------------------------------------


async def test_delivered_status_sets_delivered_at_and_reopen_clears_it(
    client: AsyncClient, bearer_headers: BearerHeaders, session: AsyncSession
) -> None:
    admin = await _admin(session, client, bearer_headers)
    _, sender = await _user(session, client, bearer_headers, "sender")
    created = await _create_order(client, sender)
    url = f"{ORDERS_URL}/{created['id']}"

    delivered = await client.post(
        f"{url}/status-history",
        json={"status": ORDER_STATUS_DELIVERED_ID},
        headers=admin,
    )
    assert delivered.status_code == 201, delivered.text
    after_delivery = (await client.get(url, headers=admin)).json()
    assert after_delivery["status"] == ORDER_STATUS_DELIVERED_ID
    assert after_delivery["delivered_at"] is not None

    reopened = await client.post(
        f"{url}/status-history", json={"status": ORDER_STATUS_CREATED_ID}, headers=admin
    )
    assert reopened.status_code == 201, reopened.text
    assert (await client.get(url, headers=admin)).json()["delivered_at"] is None
