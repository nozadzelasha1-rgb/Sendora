from typing import Final

# Role ids from dbo.dictionary (spec: role).
SUPER_ADMIN_ROLE_ID: Final[int] = 27
ADMIN_OPERATOR_ROLE_ID: Final[int] = 28

# Roles that manage zones and see every zone.
ZONE_ADMIN_ROLE_IDS: Final[tuple[int, ...]] = (
    SUPER_ADMIN_ROLE_ID,
    ADMIN_OPERATOR_ROLE_ID,
)

# Roles that see and change every order.
ORDER_ADMIN_ROLE_IDS: Final[tuple[int, ...]] = (
    SUPER_ADMIN_ROLE_ID,
    ADMIN_OPERATOR_ROLE_ID,
)

# Order statuses from dbo.dictionary (confirmed ids).
ORDER_STATUS_CANCELLED_ID: Final[int] = 1
ORDER_STATUS_CREATED_ID: Final[int] = 2

# Roles that manage dictionaries.
DICTIONARY_ADMIN_ROLE_IDS: Final[tuple[int, ...]] = (
    SUPER_ADMIN_ROLE_ID,
    ADMIN_OPERATOR_ROLE_ID,
)

# Dictionary items the code depends on by id: they cannot be deleted.
PROTECTED_DICTIONARY_ITEM_IDS: Final[frozenset[int]] = frozenset(
    {
        SUPER_ADMIN_ROLE_ID,
        ADMIN_OPERATOR_ROLE_ID,
        ORDER_STATUS_CANCELLED_ID,
        ORDER_STATUS_CREATED_ID,
    }
)
