"""Reference rows (dictionary, organization) that users depend on in tests."""

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TEST_SPEC_ID = 9001
TEST_ROLE_ID = 9001
TEST_ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000009001")

# Extra fields a test POST to /users needs to pass validation.
REF_PAYLOAD: dict[str, Any] = {
    "role": TEST_ROLE_ID,
    "organization_id": str(TEST_ORG_ID),
}


async def seed_references(session: AsyncSession) -> None:
    """Insert the test spec, role and organization rows with fixed ids (idempotent)."""
    await session.execute(
        text(
            "INSERT INTO dbo.dictionary_spec (id, name) OVERRIDING SYSTEM VALUE "
            "VALUES (:id, 'test_user_role') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": TEST_SPEC_ID},
    )
    await session.execute(
        text(
            "INSERT INTO dbo.dictionary (id, spec_id, name) OVERRIDING SYSTEM VALUE "
            "VALUES (:id, :id, 'test_user') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": TEST_ROLE_ID},
    )
    await session.execute(
        text(
            "INSERT INTO dbo.organizations (id, name, type) "
            "VALUES (:org_id, 'test_org', :type_id) ON CONFLICT (id) DO NOTHING"
        ),
        {"org_id": TEST_ORG_ID, "type_id": TEST_ROLE_ID},
    )
