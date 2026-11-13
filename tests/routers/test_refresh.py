import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings
from app.db_entities.users.user_session import UserSessionDB
from app.funcs.auth import Auth
from app.funcs.user_session import parse_refresh_token

PROJECT_ROOT = Path(__file__).resolve().parents[2]
USERS_URL = f"{settings.API_PREFIX}/users"
LOGIN_URL = f"{USERS_URL}/login"
REFRESH_URL = f"{USERS_URL}/refresh"
LOGOUT_URL = f"{USERS_URL}/logout"
LOGOUT_ALL_URL = f"{USERS_URL}/logout-all"
ME_URL = f"{USERS_URL}/me"
DELETE_URL = f"{USERS_URL}/delete"
PASSWORD = "password123"
INVALID_DETAIL = "Invalid authentication credentials"
WRONG_CREDENTIALS_DETAIL = "Invalid credentials"
RETRY_DETAIL = "Refresh in progress, please try again"
TOKEN_KEYS = {"access_token", "refresh_token", "token_type", "expires_in", "user"}


async def _create(client: AsyncClient, username: str = "alice") -> dict[str, Any]:
    response = await client.post(
        USERS_URL, json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _login(client: AsyncClient, username: str = "alice") -> dict[str, Any]:
    response = await client.post(
        LOGIN_URL, json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _post_refresh(client: AsyncClient, token: str) -> Response:
    return await client.post(REFRESH_URL, json={"refresh_token": token})


async def _logout(client: AsyncClient, token: str) -> Response:
    return await client.post(LOGOUT_URL, json={"refresh_token": token})


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sid(refresh_token: str) -> uuid.UUID:
    sid, _ = parse_refresh_token(refresh_token)
    return sid


def _assert_invalid(response: Response) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_DETAIL}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def _expire_session(session: AsyncSession, sid: uuid.UUID) -> None:
    await session.execute(
        text(
            "UPDATE personal.user_sessions "
            "SET expires_at = now() - interval '1 day' WHERE id = :sid"
        ),
        {"sid": sid},
    )
    await session.commit()


async def _session_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(UserSessionDB)
        .where(UserSessionDB.user_id == user_id)
    )
    return int(count or 0)


# --- login returns refresh token ----------------------------------------------


async def test_login_returns_refresh_token_in_body_and_no_store_header(
    client: AsyncClient,
) -> None:
    await _create(client)

    response = await client.post(
        LOGIN_URL, json={"username": "alice", "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert response.headers["Cache-Control"] == "no-store"
    assert Auth.decode_token(body["access_token"]).session_id == _sid(
        body["refresh_token"]
    )


# --- refresh ------------------------------------------------------------------


async def test_refresh_rotates_tokens_and_new_access_token_works_on_me(
    client: AsyncClient,
) -> None:
    await _create(client)
    login = await _login(client)

    response = await _post_refresh(client, login["refresh_token"])

    assert response.status_code == 200
    body = response.json()
    assert set(body) == TOKEN_KEYS
    assert response.headers["Cache-Control"] == "no-store"
    assert body["refresh_token"] != login["refresh_token"]
    assert _sid(body["refresh_token"]) == _sid(login["refresh_token"])
    me = await client.get(ME_URL, headers=_bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


async def test_refresh_replayed_token_after_grace_returns_401_and_kills_session(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create(client)
    login = await _login(client)
    rotated = await _post_refresh(client, login["refresh_token"])
    assert rotated.status_code == 200
    monkeypatch.setattr(settings, "REFRESH_TOKEN_REUSE_GRACE_SECONDS", 0)

    replay = await _post_refresh(client, login["refresh_token"])

    _assert_invalid(replay)
    _assert_invalid(await _post_refresh(client, rotated.json()["refresh_token"]))


async def test_refresh_parallel_retry_inside_grace_returns_409_and_keeps_session(
    client: AsyncClient,
) -> None:
    await _create(client)
    login = await _login(client)
    first = await _post_refresh(client, login["refresh_token"])
    assert first.status_code == 200

    retry = await _post_refresh(client, login["refresh_token"])

    assert retry.status_code == 409
    assert retry.json() == {"detail": RETRY_DETAIL}
    follow_up = await _post_refresh(client, first.json()["refresh_token"])
    assert follow_up.status_code == 200
    me = await client.get(ME_URL, headers=_bearer(follow_up.json()["access_token"]))
    assert me.status_code == 200


async def test_refresh_invalid_tokens_return_identical_401(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _create(client)
    revoked_login = await _login(client)
    expired_login = await _login(client)
    await _expire_session(session, _sid(expired_login["refresh_token"]))
    await _logout(client, revoked_login["refresh_token"])

    responses = {
        "garbage": await _post_refresh(client, "garbage"),
        "unknown_session": await _post_refresh(client, f"{uuid.uuid4()}.{'x' * 43}"),
        "revoked": await _post_refresh(client, revoked_login["refresh_token"]),
        "expired": await _post_refresh(client, expired_login["refresh_token"]),
    }

    baseline = responses["garbage"].content
    for name, response in responses.items():
        _assert_invalid(response)
        assert response.content == baseline, name


async def test_refresh_without_refresh_token_field_returns_422(
    client: AsyncClient,
) -> None:
    response = await client.post(REFRESH_URL, json={})

    assert response.status_code == 422


async def test_refresh_empty_refresh_token_returns_422(client: AsyncClient) -> None:
    response = await client.post(REFRESH_URL, json={"refresh_token": ""})

    assert response.status_code == 422


async def test_refresh_random_secret_returns_401_and_keeps_session(
    client: AsyncClient,
) -> None:
    await _create(client)
    login = await _login(client)
    forged = f"{_sid(login['refresh_token'])}.{'z' * 43}"

    response = await _post_refresh(client, forged)

    _assert_invalid(response)
    follow_up = await _post_refresh(client, login["refresh_token"])
    assert follow_up.status_code == 200


async def test_refresh_random_secret_after_rotation_keeps_current_token_working(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create(client)
    login = await _login(client)
    rotated = await _post_refresh(client, login["refresh_token"])
    assert rotated.status_code == 200
    monkeypatch.setattr(settings, "REFRESH_TOKEN_REUSE_GRACE_SECONDS", 0)
    forged = f"{_sid(login['refresh_token'])}.{'z' * 43}"

    _assert_invalid(await _post_refresh(client, forged))

    current = await _post_refresh(client, rotated.json()["refresh_token"])
    assert current.status_code == 200


# --- logout -------------------------------------------------------------------


async def test_logout_without_bearer_returns_204_and_token_is_dead(
    client: AsyncClient,
) -> None:
    await _create(client)
    login = await _login(client)

    response = await _logout(client, login["refresh_token"])

    assert response.status_code == 204
    assert response.content == b""
    _assert_invalid(await _post_refresh(client, login["refresh_token"]))
    _assert_invalid(await client.get(ME_URL, headers=_bearer(login["access_token"])))


async def test_logout_with_garbage_or_unknown_token_returns_204(
    client: AsyncClient,
) -> None:
    await _create(client)

    garbage = await _logout(client, "garbage")
    unknown = await _logout(client, f"{uuid.uuid4()}.{'x' * 43}")

    assert garbage.status_code == 204
    assert unknown.status_code == 204


async def test_logout_with_wrong_secret_returns_204_and_keeps_session(
    client: AsyncClient,
) -> None:
    await _create(client)
    login = await _login(client)
    forged = f"{_sid(login['refresh_token'])}.wrong-secret"

    response = await _logout(client, forged)

    assert response.status_code == 204
    me = await client.get(ME_URL, headers=_bearer(login["access_token"]))
    assert me.status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        "",
        "garbage",
        "a.b",
        "x" * 5000,
        "ყველა.სიმბოლო",
        "\u0000\n",
        f"{uuid.uuid4()}.{'z' * 43}",
    ],
    ids=["empty", "garbage", "dot", "long", "unicode", "control", "random-secret"],
)
async def test_logout_arbitrary_string_returns_204(
    client: AsyncClient, token: str
) -> None:
    response = await _logout(client, token)

    assert response.status_code == 204
    assert response.content == b""


async def test_logout_without_refresh_token_field_returns_422(
    client: AsyncClient,
) -> None:
    response = await client.post(LOGOUT_URL, json={})

    assert response.status_code == 422


# --- logout-all ---------------------------------------------------------------


async def test_logout_all_revokes_every_session_of_user_and_spares_others(
    client: AsyncClient,
) -> None:
    await _create(client, username="alice")
    await _create(client, username="bob")
    alice_one = await _login(client, username="alice")
    alice_two = await _login(client, username="alice")
    bob = await _login(client, username="bob")

    response = await client.post(
        LOGOUT_ALL_URL, headers=_bearer(alice_one["access_token"])
    )

    assert response.status_code == 204
    assert response.content == b""
    for alice in (alice_one, alice_two):
        _assert_invalid(
            await client.get(ME_URL, headers=_bearer(alice["access_token"]))
        )
        _assert_invalid(await _post_refresh(client, alice["refresh_token"]))
    bob_me = await client.get(ME_URL, headers=_bearer(bob["access_token"]))
    assert bob_me.status_code == 200
    assert (await _post_refresh(client, bob["refresh_token"])).status_code == 200


async def test_logout_all_without_bearer_returns_invalid_401(
    client: AsyncClient,
) -> None:
    await _create(client)
    login = await _login(client)

    response = await client.post(LOGOUT_ALL_URL)

    _assert_invalid(response)
    assert (await _post_refresh(client, login["refresh_token"])).status_code == 200


# --- revocation and deletion --------------------------------------------------


async def test_manual_revoke_in_database_blocks_me_immediately(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _create(client)
    login = await _login(client)
    await session.execute(
        text("UPDATE personal.user_sessions SET revoked_at = now() WHERE id = :sid"),
        {"sid": _sid(login["refresh_token"])},
    )

    _assert_invalid(await client.get(ME_URL, headers=_bearer(login["access_token"])))


async def test_delete_with_other_users_credentials_carries_www_authenticate(
    client: AsyncClient,
) -> None:
    await _create(client, username="alice")
    await _create(client, username="bob")
    alice = await _login(client, username="alice")

    for creds in (
        {"username": "bob", "password": PASSWORD},
        {"username": "alice", "password": "wrong-password"},
    ):
        response = await client.post(
            DELETE_URL, json=creds, headers=_bearer(alice["access_token"])
        )

        assert response.status_code == 401
        assert response.json() == {"detail": WRONG_CREDENTIALS_DETAIL}
        assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_delete_user_cascades_to_sessions_and_refresh_fails(
    client: AsyncClient, session: AsyncSession
) -> None:
    created = await _create(client)
    login = await _login(client)

    response = await client.post(
        DELETE_URL,
        json={"username": "alice", "password": PASSWORD},
        headers=_bearer(login["access_token"]),
    )

    assert response.status_code == 204
    _assert_invalid(await _post_refresh(client, login["refresh_token"]))
    assert await _session_count(session, uuid.UUID(str(created["id"]))) == 0


async def test_login_purges_own_expired_and_revoked_sessions(
    client: AsyncClient, session: AsyncSession
) -> None:
    created = await _create(client)
    revoked = await _login(client)
    expired = await _login(client)
    await _expire_session(session, _sid(expired["refresh_token"]))
    await _logout(client, revoked["refresh_token"])

    fresh = await _login(client)

    assert await _session_count(session, uuid.UUID(str(created["id"]))) == 1
    assert _sid(fresh["refresh_token"]) != _sid(expired["refresh_token"])


# --- OpenAPI security ---------------------------------------------------------


async def test_openapi_security_matches_authentication_requirements(
    client: AsyncClient,
) -> None:
    response = await client.get(f"{settings.API_PREFIX}/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    for public in (USERS_URL, LOGIN_URL, REFRESH_URL, LOGOUT_URL):
        assert "security" not in paths[public]["post"], public
    for protected in (LOGOUT_ALL_URL, DELETE_URL):
        assert paths[protected]["post"]["security"], protected
    assert paths[ME_URL]["get"]["security"]


# --- CORS ---------------------------------------------------------------------


def test_main_app_cors_allows_only_get_post_and_declared_headers() -> None:
    """Import root main.py in a child process so the shared test app stays untouched."""
    script = (
        "import json\n"
        "import main\n"
        "for middleware in main.app.user_middleware:\n"
        "    if middleware.cls.__name__ == 'CORSMiddleware':\n"
        "        options = middleware.kwargs\n"
        "        print(json.dumps({\n"
        "            'origins': list(options['allow_origins']),\n"
        "            'methods': sorted(options['allow_methods']),\n"
        "            'headers': sorted(options['allow_headers']),\n"
        "            'credentials': options['allow_credentials'],\n"
        "        }))\n"
        "        break\n"
        "else:\n"
        "    raise SystemExit('CORS middleware is not registered')\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    cors = json.loads(result.stdout.strip().splitlines()[-1])
    assert cors == {
        "origins": settings.CORS_ORIGINS,
        "methods": ["GET", "POST"],
        "headers": ["Authorization", "Content-Type"],
        "credentials": False,
    }
