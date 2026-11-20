class UserAlreadyExistsError(Exception):
    """A user with the same name, phone or email already exists."""


class InvalidReferenceError(Exception):
    """The role or organization referenced by the user does not exist."""


class UserNotFoundError(Exception):
    """User not found, inactive, or credentials are invalid."""


class AuthError(Exception):
    """Base class for authentication failures."""


class TokenExpiredError(AuthError):
    """The access token has expired."""


class InvalidTokenError(AuthError):
    """The access token is missing, malformed, tampered or not usable."""


class RefreshTokenError(AuthError):
    """The refresh token is invalid, expired, revoked or reused."""


class RefreshRetryError(AuthError):
    """A parallel refresh is in progress inside the grace window; retry."""


class OrganizationNotFoundError(Exception):
    """Organization not found."""


class InvalidOrganizationTypeError(Exception):
    """The organization type does not exist in the dictionary."""


class SessionInvalidError(Exception):
    """The session is missing, invalid, expired, revoked or the token mismatches."""


class SessionRetryError(Exception):
    """Parallel refresh inside the grace window; the session is NOT revoked."""


class ZoneNotFoundError(Exception):
    """Zone not found."""


class InvalidZoneReferenceError(Exception):
    """A status, assignment rule or manager referenced by the zone does not exist."""


class NoDataError(Exception):
    """No zone is available for the requesting user."""


class OrderNotFoundError(Exception):
    """Order not found or not visible to the requesting user."""


class OrderForbiddenError(Exception):
    """The requesting user may not perform this action on the order."""


class InvalidOrderReferenceError(Exception):
    """A dictionary, zone, organization or user referenced by the order does not exist."""


class OrderConflictError(Exception):
    """An order with the same external_order_id already exists for the partner."""
