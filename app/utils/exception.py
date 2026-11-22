class UserAlreadyExistsError(Exception):
    """A user with the same name, phone or email already exists."""


class InvalidReferenceError(Exception):
    """The role referenced by the user does not exist."""


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
    """A status or assignment rule referenced by the zone does not exist."""


class NoDataError(Exception):
    """No zone is available for the requesting user."""


class OrderNotFoundError(Exception):
    """Order not found or not visible to the requesting user."""


class OrderForbiddenError(Exception):
    """The requesting user may not perform this action on the order."""


class OrganizationChoiceRequiredError(Exception):
    """The order needs an explicit organization: the user has several, or is an admin."""


class InvalidOrderReferenceError(Exception):
    """A dictionary, zone, organization or user referenced by the order does not exist."""


class OrderConflictError(Exception):
    """The order cannot be stored because of a conflict, e.g. no free tracking number."""


class MembershipAlreadyExistsError(Exception):
    """The user is already a member of the organization or zone."""


class MembershipNotFoundError(Exception):
    """The user is not a member of the organization or zone."""


class DictionarySpecNotFoundError(Exception):
    """The dictionary spec does not exist."""


class DictionaryItemNotFoundError(Exception):
    """The dictionary item does not exist inside the given spec."""


class DictionaryItemInUseError(Exception):
    """The dictionary item is referenced by other records or is protected from deletion."""
