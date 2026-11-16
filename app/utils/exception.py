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
