import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.db_entities.users.user import UserDB
from tests.seed import REF_PAYLOAD

USERS_URL = f"{settings.API_PREFIX}/users"
LOGIN_URL = f"{USERS_URL}/login"
DELETE_URL = f"{USERS_URL}/delete"
ME_URL = f"{USERS_URL}/me"
PASSWORD = "password123"


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "alice",
        "password": PASSWORD,
        **REF_PAYLOAD,
    }
    payload.update(overrides)
    return payload


async def _create(client: AsyncClient, **overrides: object) -> dict[str, object]:
    response = await client.post(USERS_URL, json=_payload(**overrides))
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def _row_exists(session: AsyncSession, user_id: str) -> bool:
    result = await session.execute(
        select(UserDB.id).where(UserDB.id == uuid.UUID(user_id))
    )
    return result.scalar_one_or_none() is not None


async def _deactivate(session: AsyncSession, user_id: str) -> None:
    user = await session.get(UserDB, uuid.UUID(user_id))
    assert user is not None
    user.active = False
    await session.commit()


# --- POST /users ----------------------------------------------------------------


async def test_create_user_valid_payload_returns_201(client: AsyncClient) -> None:
    response = await client.post(USERS_URL, json=_payload(email="alice@example.com"))

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "alice"
    assert body["email"] == "alice@example.com"
    assert body["active"] is True
    assert "id" in body


async def test_create_user_response_excludes_password_fields(
    client: AsyncClient,
) -> None:
    body = await _create(client)

    assert "password" not in body
    assert "password_hash" not in body


async def test_create_user_duplicate_name_returns_409(client: AsyncClient) -> None:
    await _create(client, name="alice")

    response = await client.post(
        USERS_URL, json=_payload(name="alice", phone="+79990000001")
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "User already exists"}


async def test_create_user_duplicate_phone_returns_409(client: AsyncClient) -> None:
    await _create(client, name="alice", phone="+79991234567")

    response = await client.post(
        USERS_URL, json=_payload(name="bob", phone="+79991234567")
    )

    assert response.status_code == 409


async def test_create_user_duplicate_email_returns_409(client: AsyncClient) -> None:
    await _create(client, name="alice", email="alice@example.com")

    response = await client.post(
        USERS_URL, json=_payload(name="bob", email="alice@example.com")
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "al", "password": PASSWORD},  # name too short
        {"name": "alice", "password": "short"},  # password too short
        {"name": "alice"},  # password missing
        {"password": PASSWORD},  # name missing
        {"name": "alice", "password": PASSWORD, "email": "not-an-email"},
        {"name": "alice", "password": PASSWORD, "phone": "12ab"},
    ],
)
async def test_create_user_invalid_payload_returns_422(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    response = await client.post(USERS_URL, json=payload)

    assert response.status_code == 422


# --- POST /users/login ----------------------------------------------------------


async def test_login_by_name_returns_token_response(client: AsyncClient) -> None:
    created = await _create(client, name="alice")

    response = await client.post(
        LOGIN_URL, json={"name": "alice", "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_in",
        "user",
    }
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert isinstance(body["refresh_token"], str) and "." in body["refresh_token"]
    assert body["user"]["id"] == created["id"]
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


async def test_login_by_phone_returns_200(client: AsyncClient) -> None:
    created = await _create(client, name="alice", phone="+79991234567")

    response = await client.post(
        LOGIN_URL, json={"phone": "+79991234567", "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["user"]["id"] == created["id"]


async def test_login_by_email_returns_200(client: AsyncClient) -> None:
    created = await _create(client, name="alice", email="alice@example.com")

    response = await client.post(
        LOGIN_URL, json={"email": "alice@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["user"]["id"] == created["id"]


async def test_login_failures_return_identical_401_bodies(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Unknown user, inactive user and wrong password must not be distinguishable."""
    await _create(client, name="alice")
    inactive = await _create(client, name="inactive")
    await _deactivate(session, str(inactive["id"]))

    responses = [
        await client.post(LOGIN_URL, json={"name": "nobody", "password": PASSWORD}),
        await client.post(LOGIN_URL, json={"name": "inactive", "password": PASSWORD}),
        await client.post(
            LOGIN_URL, json={"name": "alice", "password": "wrong-password"}
        ),
    ]

    for response in responses:
        assert response.status_code == 401
    assert responses[0].json() == {"detail": "Invalid credentials"}
    assert responses[1].content == responses[0].content
    assert responses[2].content == responses[0].content


@pytest.mark.parametrize(
    "payload",
    [
        {"password": PASSWORD},  # zero identifiers
        {"name": "alice", "email": "alice@example.com", "password": PASSWORD},
        {"name": "alice", "phone": "+79991234567", "password": PASSWORD},
    ],
)
async def test_login_wrong_identifier_count_returns_422(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    response = await client.post(LOGIN_URL, json=payload)

    assert response.status_code == 422


# --- POST /users/delete ---------------------------------------------------------


async def test_delete_user_valid_credentials_returns_204_and_removes_row(
    client: AsyncClient,
    session: AsyncSession,
    bearer_headers: Callable[..., Awaitable[dict[str, str]]],
) -> None:
    created = await _create(client, name="alice")
    headers = await bearer_headers("alice")

    response = await client.post(
        DELETE_URL, json={"name": "alice", "password": PASSWORD}, headers=headers
    )

    assert response.status_code == 204
    assert response.content == b""
    assert await _row_exists(session, str(created["id"])) is False


async def test_delete_user_wrong_password_returns_401_and_keeps_row(
    client: AsyncClient,
    session: AsyncSession,
    bearer_headers: Callable[..., Awaitable[dict[str, str]]],
) -> None:
    created = await _create(client, name="alice")
    headers = await bearer_headers("alice")

    response = await client.post(
        DELETE_URL,
        json={"name": "alice", "password": "wrong-password"},
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert await _row_exists(session, str(created["id"])) is True


async def test_delete_user_repeat_request_returns_401(
    client: AsyncClient,
    bearer_headers: Callable[..., Awaitable[dict[str, str]]],
) -> None:
    await _create(client, name="alice")
    headers = await bearer_headers("alice")
    body = {"name": "alice", "password": PASSWORD}
    first = await client.post(DELETE_URL, json=body, headers=headers)

    second = await client.post(DELETE_URL, json=body, headers=headers)

    assert first.status_code == 204
    assert second.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "alice"},  # password missing
        {"password": PASSWORD},  # zero identifiers
        {"name": "alice", "email": "alice@example.com", "password": PASSWORD},
    ],
)
async def test_delete_user_invalid_body_returns_422(
    client: AsyncClient,
    payload: dict[str, object],
    bearer_headers: Callable[..., Awaitable[dict[str, str]]],
) -> None:
    await _create(client, name="alice")
    headers = await bearer_headers("alice")

    response = await client.post(DELETE_URL, json=payload, headers=headers)

    assert response.status_code == 422


# --- removed / contract ---------------------------------------------------------


async def test_list_users_route_removed_returns_404_or_405(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{USERS_URL}/users")

    assert response.status_code in (404, 405)


async def test_openapi_lists_create_login_and_delete_operations(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{settings.API_PREFIX}/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert set(paths[USERS_URL]) == {"post"}
    assert set(paths[LOGIN_URL]) == {"post"}
    assert set(paths[DELETE_URL]) == {"post"}


async def test_create_user_unknown_role_returns_422(client: AsyncClient) -> None:
    response = await client.post(USERS_URL, json=_payload(role=987654))

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown role or organization"
