import uuid
from typing import Any

import pytest
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_entities.users.user import UserDB
from app.funcs.user import (
    InvalidReferenceError,
    User,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.schema.user import UserCreate, UserCredentials
from tests.seed import TEST_ORG_ID, TEST_ROLE_ID

PASSWORD = "password123"


async def _make(
    session: AsyncSession,
    name: str = "alice",
    password: str = PASSWORD,
    phone: str | None = None,
    email: str | None = None,
) -> UserDB:
    return await User(session).create(
        UserCreate(
            role=TEST_ROLE_ID,
            organization_id=TEST_ORG_ID,
            name=name,
            password=password,
            phone=phone,
            email=email,
        )
    )


# --- hashing ------------------------------------------------------------------


async def test_hash_password_round_trip_verifies_true() -> None:
    hashed = await User.hash_password(PASSWORD)

    assert await User.verify_password(PASSWORD, hashed) is True


async def test_hash_password_wrong_password_verifies_false() -> None:
    hashed = await User.hash_password(PASSWORD)

    assert await User.verify_password("wrong-password", hashed) is False


async def test_hash_password_called_twice_returns_different_hashes() -> None:
    first = await User.hash_password(PASSWORD)
    second = await User.hash_password(PASSWORD)

    assert first != second
    assert first.startswith("$argon2")
    assert second.startswith("$argon2")


async def test_verify_password_malformed_hash_returns_false() -> None:
    assert await User.verify_password(PASSWORD, "not-a-valid-hash") is False


# --- create -------------------------------------------------------------------


async def test_create_stores_argon2_hash_not_plaintext(session: AsyncSession) -> None:
    user = await _make(session)

    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert user.password_hash.startswith("$argon2")
    assert await User.verify_password(PASSWORD, user.password_hash) is True


async def test_create_persists_normalized_fields(session: AsyncSession) -> None:
    user = await User(session).create(
        UserCreate(
            role=TEST_ROLE_ID,
            organization_id=TEST_ORG_ID,
            name="  Alice_01 ",
            password=PASSWORD,
            phone=" +79991234567 ",
            email=" Alice@Example.COM ",
        )
    )

    assert user.id is not None
    assert user.name == "alice_01"
    assert user.phone == "+79991234567"
    assert user.email == "alice@example.com"


async def test_create_duplicate_name_raises_already_exists(
    session: AsyncSession,
) -> None:
    await _make(session, name="alice")

    with pytest.raises(UserAlreadyExistsError):
        await _make(session, name="alice", phone="+79990000001")


async def test_create_duplicate_phone_raises_already_exists(
    session: AsyncSession,
) -> None:
    await _make(session, name="alice", phone="+79991234567")

    with pytest.raises(UserAlreadyExistsError):
        await _make(session, name="bob", phone="+79991234567")


async def test_create_duplicate_email_raises_already_exists(
    session: AsyncSession,
) -> None:
    await _make(session, name="alice", email="alice@example.com")

    with pytest.raises(UserAlreadyExistsError):
        await _make(session, name="bob", email="alice@example.com")


async def test_create_duplicate_name_differing_case_raises_already_exists(
    session: AsyncSession,
) -> None:
    await _make(session, name="alice")

    with pytest.raises(UserAlreadyExistsError):
        await _make(session, name="ALICE")


async def test_create_without_phone_and_email_succeeds(session: AsyncSession) -> None:
    user = await _make(session, name="alice")

    assert user.phone is None
    assert user.email is None


async def test_create_several_users_without_phone_or_email_allowed(
    session: AsyncSession,
) -> None:
    first = await _make(session, name="alice")
    second = await _make(session, name="bob")

    assert first.id != second.id
    assert first.phone is None and second.phone is None
    assert first.email is None and second.email is None


async def test_create_integrity_error_maps_to_already_exists(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate a race: the pre-check misses a row that the UNIQUE constraint rejects."""
    await _make(session, name="racer", email="racer@example.com")

    class _NoRowsResult:
        def first(self) -> None:
            return None

    original_execute = session.execute

    async def _skip_precheck(statement: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(statement, Select):
            return _NoRowsResult()
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", _skip_precheck)

    with pytest.raises(UserAlreadyExistsError) as exc_info:
        await _make(session, name="racer", password=PASSWORD)

    assert isinstance(exc_info.value.__cause__, IntegrityError)


# --- get_by_credentials / check_credentials -----------------------------------


async def test_get_by_credentials_by_name_returns_user(
    session: AsyncSession,
) -> None:
    created = await _make(session, name="alice")

    found = await User(session).get_by_credentials(
        UserCredentials(name="alice", password=PASSWORD)
    )

    assert found.id == created.id


async def test_get_by_credentials_by_phone_returns_user(session: AsyncSession) -> None:
    created = await _make(session, name="alice", phone="+79991234567")

    found = await User(session).get_by_credentials(
        UserCredentials(phone="+79991234567", password=PASSWORD)
    )

    assert found.id == created.id


async def test_get_by_credentials_by_email_returns_user(session: AsyncSession) -> None:
    created = await _make(session, name="alice", email="alice@example.com")

    found = await User(session).get_by_credentials(
        UserCredentials(email="alice@example.com", password=PASSWORD)
    )

    assert found.id == created.id


async def test_get_by_credentials_wrong_password_raises_not_found(
    session: AsyncSession,
) -> None:
    await _make(session, name="alice")

    with pytest.raises(UserNotFoundError):
        await User(session).get_by_credentials(
            UserCredentials(name="alice", password="wrong-password")
        )


async def test_get_by_credentials_unknown_user_raises_not_found(
    session: AsyncSession,
) -> None:
    with pytest.raises(UserNotFoundError):
        await User(session).get_by_credentials(
            UserCredentials(name="nobody", password=PASSWORD)
        )


async def test_get_by_credentials_inactive_user_raises_not_found(
    session: AsyncSession,
) -> None:
    user = await _make(session, name="alice")
    user.active = False
    await session.commit()

    with pytest.raises(UserNotFoundError):
        await User(session).get_by_credentials(
            UserCredentials(name="alice", password=PASSWORD)
        )


async def test_get_by_credentials_name_case_insensitive(
    session: AsyncSession,
) -> None:
    created = await _make(session, name="alice")

    found = await User(session).get_by_credentials(
        UserCredentials(name="  ALICE ", password=PASSWORD)
    )

    assert found.id == created.id


async def test_get_by_credentials_email_case_insensitive(session: AsyncSession) -> None:
    created = await _make(session, name="alice", email="alice@example.com")

    found = await User(session).get_by_credentials(
        UserCredentials(email="ALICE@Example.COM", password=PASSWORD)
    )

    assert found.id == created.id


async def test_check_credentials_valid_returns_true(session: AsyncSession) -> None:
    await _make(session, name="alice")

    result = await User(session).check_credentials(
        UserCredentials(name="alice", password=PASSWORD)
    )

    assert result is True


async def test_check_credentials_wrong_password_raises_not_found(
    session: AsyncSession,
) -> None:
    await _make(session, name="alice")

    with pytest.raises(UserNotFoundError):
        await User(session).check_credentials(
            UserCredentials(name="alice", password="wrong-password")
        )


async def test_check_credentials_unknown_user_raises_not_found(
    session: AsyncSession,
) -> None:
    with pytest.raises(UserNotFoundError):
        await User(session).check_credentials(
            UserCredentials(name="nobody", password=PASSWORD)
        )


async def test_check_credentials_inactive_user_raises_not_found(
    session: AsyncSession,
) -> None:
    user = await _make(session, name="alice")
    user.active = False
    await session.commit()

    with pytest.raises(UserNotFoundError):
        await User(session).check_credentials(
            UserCredentials(name="alice", password=PASSWORD)
        )


# --- delete -------------------------------------------------------------------


async def test_delete_existing_user_removes_row(session: AsyncSession) -> None:
    user = await _make(session, name="alice")

    await User(session).delete(user.id)

    with pytest.raises(UserNotFoundError):
        await User(session).get_by_credentials(
            UserCredentials(name="alice", password=PASSWORD)
        )


async def test_delete_missing_user_raises_not_found(session: AsyncSession) -> None:
    with pytest.raises(UserNotFoundError):
        await User(session).delete(uuid.uuid4())


async def test_delete_inactive_user_raises_not_found_and_keeps_row(
    session: AsyncSession,
) -> None:
    user = await _make(session, name="alice")
    user_id = user.id
    user.active = False
    await session.commit()

    with pytest.raises(UserNotFoundError):
        await User(session).delete(user_id)

    result = await session.execute(select(UserDB.id).where(UserDB.id == user_id))
    assert result.scalar_one_or_none() == user_id


# --- delete_with_credentials --------------------------------------------------


async def test_delete_with_credentials_valid_removes_row(session: AsyncSession) -> None:
    user = await _make(session, name="alice")
    user_id = user.id

    await User(session).delete_with_credentials(
        UserCredentials(name="alice", password=PASSWORD)
    )

    result = await session.execute(select(UserDB.id).where(UserDB.id == user_id))
    assert result.scalar_one_or_none() is None


async def test_delete_with_credentials_wrong_password_raises_and_keeps_row(
    session: AsyncSession,
) -> None:
    user = await _make(session, name="alice")
    user_id = user.id

    with pytest.raises(UserNotFoundError):
        await User(session).delete_with_credentials(
            UserCredentials(name="alice", password="wrong-password")
        )

    result = await session.execute(select(UserDB.id).where(UserDB.id == user_id))
    assert result.scalar_one_or_none() == user_id


async def test_delete_with_credentials_unknown_user_raises_not_found(
    session: AsyncSession,
) -> None:
    with pytest.raises(UserNotFoundError):
        await User(session).delete_with_credentials(
            UserCredentials(name="nobody", password=PASSWORD)
        )


async def test_delete_with_credentials_inactive_user_raises_and_keeps_row(
    session: AsyncSession,
) -> None:
    user = await _make(session, name="alice")
    user_id = user.id
    user.active = False
    await session.commit()

    with pytest.raises(UserNotFoundError):
        await User(session).delete_with_credentials(
            UserCredentials(name="alice", password=PASSWORD)
        )

    result = await session.execute(select(UserDB.id).where(UserDB.id == user_id))
    assert result.scalar_one_or_none() == user_id


# --- delete_user_with_credentials ---------------------------------------------


async def test_delete_user_with_credentials_expected_user_removes_row(
    session: AsyncSession,
) -> None:
    user = await _make(session, name="alice")
    user_id = user.id

    await User(session).delete_user_with_credentials(
        UserCredentials(name="alice", password=PASSWORD), user_id
    )

    result = await session.execute(select(UserDB.id).where(UserDB.id == user_id))
    assert result.scalar_one_or_none() is None


async def test_delete_user_with_other_users_credentials_raises_and_deletes_nothing(
    session: AsyncSession,
) -> None:
    alice = await _make(session, name="alice")
    bob = await _make(session, name="bob")
    alice_id = alice.id
    bob_id = bob.id

    with pytest.raises(UserNotFoundError):
        await User(session).delete_user_with_credentials(
            UserCredentials(name="bob", password=PASSWORD), alice_id
        )

    rows = await session.execute(
        select(UserDB.id).where(UserDB.id.in_([alice_id, bob_id]))
    )
    assert set(rows.scalars().all()) == {alice_id, bob_id}


async def test_delete_user_with_credentials_wrong_password_raises_and_keeps_row(
    session: AsyncSession,
) -> None:
    user = await _make(session, name="alice")
    user_id = user.id

    with pytest.raises(UserNotFoundError):
        await User(session).delete_user_with_credentials(
            UserCredentials(name="alice", password="wrong-password"), user_id
        )

    result = await session.execute(select(UserDB.id).where(UserDB.id == user_id))
    assert result.scalar_one_or_none() == user_id


async def test_delete_user_with_credentials_inactive_user_raises_and_keeps_row(
    session: AsyncSession,
) -> None:
    user = await _make(session, name="alice")
    user_id = user.id
    user.active = False
    await session.commit()

    with pytest.raises(UserNotFoundError):
        await User(session).delete_user_with_credentials(
            UserCredentials(name="alice", password=PASSWORD), user_id
        )

    result = await session.execute(select(UserDB.id).where(UserDB.id == user_id))
    assert result.scalar_one_or_none() == user_id


async def test_create_unknown_role_raises_invalid_reference_error(
    session: AsyncSession,
) -> None:
    with pytest.raises(InvalidReferenceError):
        await User(session).create(
            UserCreate(
                role=987654,
                organization_id=TEST_ORG_ID,
                name="alice",
                password=PASSWORD,
            )
        )
