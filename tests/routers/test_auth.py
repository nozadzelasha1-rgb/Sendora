import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.db_entities.users.user import UserDB
from app.funcs.user_session import parse_refresh_token

USERS_URL = f"{settings.API_PREFIX}/users"
LOGIN_URL = f"{USERS_URL}/login"
DELETE_URL = f"{USERS_URL}/delete"
ME_URL = f"{USERS_URL}/me"
PASSWORD = "password123"
INVALID_DETAIL = "Invalid authentication credentials"
EXPIRED_DETAIL = "Authentication expired, please sign in again"
WRONG_CREDENTIALS_DETAIL = "Invalid credentials"

BearerHeaders = Callable[..., Awaitable[dict[str, str]]]


async def _create(client: AsyncClient, username: str = "alice") -> dict[str, Any]:
    response = await client.post(
        USERS_URL, json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _row_exists(session: AsyncSession, user_id: str) -> bool:
    result = await session.execute(
        select(UserDB.id).where(UserDB.id == uuid.UUID(user_id))
    )
    return result.scalar_one_or_none() is not None


def _assert_invalid(response: Response) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_DETAIL}
    assert response.headers["WWW-Authenticate"] == "Bearer"


def _crafted_token(user_id: str, sid: str, **overrides: Any) -> str:
    """Sign a token with the app secret so only the overridden claims differ."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": user_id,
        "username": "alice",
        "sid": sid,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": uuid.uuid4().hex,
    }
    claims.update(overrides)
    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def _login_body(client: AsyncClient, username: str = "alice") -> dict[str, Any]:
    response = await client.post(
        LOGIN_URL, json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _login_token(client: AsyncClient, username: str = "alice") -> str:
    token: str = (await _login_body(client, username))["access_token"]
    return token


def _sid_of(refresh_token: str) -> str:
    sid, _ = parse_refresh_token(refresh_token)
    return str(sid)


# --- /me happy path -----------------------------------------------------------


async def test_me_with_login_token_returns_200_and_user(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    created = await _create(client)

    response = await client.get(ME_URL, headers=await bearer_headers("alice"))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["username"] == "alice"
    assert "password" not in body
    assert "password_hash" not in body


# --- /me failures: identical invalid body -------------------------------------


async def test_me_without_authorization_header_returns_invalid_401(
    client: AsyncClient,
) -> None:
    _assert_invalid(await client.get(ME_URL))


async def test_me_with_basic_scheme_returns_invalid_401(client: AsyncClient) -> None:
    await _create(client)
    token = await _login_token(client)

    response = await client.get(ME_URL, headers={"Authorization": f"Basic {token}"})

    _assert_invalid(response)


async def test_me_with_expired_token_returns_expired_401(client: AsyncClient) -> None:
    created = await _create(client)
    login = await _login_body(client)
    expired = _crafted_token(
        created["id"],
        _sid_of(login["refresh_token"]),
        iat=datetime.now(UTC) - timedelta(minutes=10),
        exp=datetime.now(UTC) - timedelta(minutes=1),
    )

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert response.json() == {"detail": EXPIRED_DETAIL}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_me_with_tampered_signature_returns_invalid_401(
    client: AsyncClient,
) -> None:
    await _create(client)
    token = await _login_token(client)
    last = token[-1]
    tampered = token[:-1] + ("A" if last != "A" else "B")

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {tampered}"})

    _assert_invalid(response)


async def test_me_with_token_of_deleted_user_returns_invalid_401(
    client: AsyncClient, bearer_headers: BearerHeaders
) -> None:
    await _create(client)
    headers = await bearer_headers("alice")
    token = headers["Authorization"].removeprefix("Bearer ")
    deleted = await client.post(
        DELETE_URL, json={"username": "alice", "password": PASSWORD}, headers=headers
    )
    assert deleted.status_code == 204

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

    _assert_invalid(response)


async def test_me_with_token_of_inactive_user_returns_invalid_401(
    client: AsyncClient, session: AsyncSession, bearer_headers: BearerHeaders
) -> None:
    created = await _create(client)
    headers = await bearer_headers("alice")
    user = await session.get(UserDB, uuid.UUID(str(created["id"])))
    assert user is not None
    user.is_active = False
    await session.commit()

    response = await client.get(ME_URL, headers=headers)

    _assert_invalid(response)


async def test_me_failure_bodies_are_byte_identical_for_non_expired_causes(
    client: AsyncClient, session: AsyncSession, bearer_headers: BearerHeaders
) -> None:
    """Missing, wrong-scheme, tampered, deleted and inactive must look the same."""
    created = await _create(client)
    headers = await bearer_headers("alice")
    token = headers["Authorization"].removeprefix("Bearer ")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    await _create(client, username="bob")
    bob_headers = await bearer_headers("bob")
    user = await session.get(UserDB, uuid.UUID(str(created["id"])))
    assert user is not None
    user.is_active = False
    await session.commit()

    responses = [
        await client.get(ME_URL),
        await client.get(ME_URL, headers={"Authorization": f"Basic {token}"}),
        await client.get(ME_URL, headers={"Authorization": f"Bearer {tampered}"}),
        await client.get(ME_URL, headers=headers),  # alice is inactive now
        await client.get(ME_URL, headers=bob_headers),  # bob is active: control
    ]

    baseline = responses[0]
    for response in responses[:4]:
        assert response.status_code == 401
        assert response.content == baseline.content
        assert response.headers["WWW-Authenticate"] == "Bearer"
    assert responses[4].status_code == 200


# --- delete with token --------------------------------------------------------


async def test_delete_with_other_users_credentials_returns_401_and_keeps_row(
    client: AsyncClient, session: AsyncSession, bearer_headers: BearerHeaders
) -> None:
    alice = await _create(client, username="alice")
    bob = await _create(client, username="bob")
    alice_headers = await bearer_headers("alice")

    response = await client.post(
        DELETE_URL,
        json={"username": "bob", "password": PASSWORD},
        headers=alice_headers,
    )

    assert response.status_code == 401
    assert response.json() == {"detail": WRONG_CREDENTIALS_DETAIL}
    assert await _row_exists(session, str(bob["id"])) is True
    assert await _row_exists(session, str(alice["id"])) is True


async def test_delete_without_token_returns_401_and_keeps_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    created = await _create(client)

    response = await client.post(
        DELETE_URL, json={"username": "alice", "password": PASSWORD}
    )

    _assert_invalid(response)
    assert await _row_exists(session, str(created["id"])) is True


async def test_delete_with_invalid_token_returns_401_and_keeps_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    created = await _create(client)

    response = await client.post(
        DELETE_URL,
        json={"username": "alice", "password": PASSWORD},
        headers={"Authorization": "Bearer not-a-token"},
    )

    _assert_invalid(response)
    assert await _row_exists(session, str(created["id"])) is True


# --- public endpoints ---------------------------------------------------------


async def test_create_and_login_work_without_token(client: AsyncClient) -> None:
    created = await client.post(
        USERS_URL, json={"username": "alice", "password": PASSWORD}
    )
    login = await client.post(
        LOGIN_URL, json={"username": "alice", "password": PASSWORD}
    )

    assert created.status_code == 201
    assert login.status_code == 200


# --- OpenAPI contract ---------------------------------------------------------


async def test_openapi_declares_bearer_scheme_and_protects_me_and_delete(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{settings.API_PREFIX}/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    schemes = spec["components"]["securitySchemes"]
    assert any(
        scheme.get("type") == "http" and scheme.get("scheme") == "bearer"
        for scheme in schemes.values()
    )
    paths = spec["paths"]
    assert "security" in paths[ME_URL]["get"]
    assert "security" in paths[DELETE_URL]["post"]
    assert "security" not in paths[LOGIN_URL]["post"]
    assert "security" not in paths[USERS_URL]["post"]


# --- access token bound to a live session -------------------------------------


async def test_me_with_token_of_other_users_session_returns_invalid_401(
    client: AsyncClient,
) -> None:
    alice = await _create(client, username="alice")
    await _create(client, username="bob")
    bob_login = await _login_body(client, username="bob")
    forged = _crafted_token(alice["id"], _sid_of(bob_login["refresh_token"]))

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {forged}"})

    _assert_invalid(response)


async def test_me_with_token_of_unknown_session_returns_invalid_401(
    client: AsyncClient,
) -> None:
    created = await _create(client)
    forged = _crafted_token(created["id"], str(uuid.uuid4()))

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {forged}"})

    _assert_invalid(response)


async def test_me_without_sid_claim_returns_invalid_401(client: AsyncClient) -> None:
    created = await _create(client)
    login = await _login_body(client)
    token = _crafted_token(created["id"], _sid_of(login["refresh_token"]))
    legacy = jwt.encode(
        {
            key: value
            for key, value in jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            ).items()
            if key != "sid"
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {legacy}"})

    _assert_invalid(response)
