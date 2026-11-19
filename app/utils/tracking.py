import secrets

TRACKING_PREFIX = "SND"
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_BODY_LENGTH = 8
_GROUP_SIZE = 4
_SEPARATOR = "-"


def compute_check_char(body: str) -> str:
    """Return the check character for a body made of alphabet characters.

    A weighted sum modulo the alphabet size detects single-character typos and
    adjacent transpositions.
    """
    total = sum((index + 1) * _ALPHABET.index(char) for index, char in enumerate(body))
    return _ALPHABET[total % len(_ALPHABET)]


def generate_tracking_number() -> str:
    """Return a tracking number formatted as SND-XXXX-XXXX-C (random, with a check character)."""
    body = "".join(secrets.choice(_ALPHABET) for _ in range(_BODY_LENGTH))
    check = compute_check_char(body)
    first, second = body[:_GROUP_SIZE], body[_GROUP_SIZE:]
    return _SEPARATOR.join([TRACKING_PREFIX, first, second, check])


def normalize_tracking_number(value: str) -> str:
    """Upper-case the value and drop whitespace and hyphens."""
    return "".join(value.split()).replace(_SEPARATOR, "").upper()


def is_valid_tracking_number(value: str) -> bool:
    """Return True when the value is a well-formed tracking number with a matching check character."""
    normalized = normalize_tracking_number(value)
    if not normalized.startswith(TRACKING_PREFIX):
        return False
    rest = normalized[len(TRACKING_PREFIX) :]
    if len(rest) != _BODY_LENGTH + 1:
        return False
    body, check = rest[:-1], rest[-1]
    if not all(char in _ALPHABET for char in body):
        return False
    return compute_check_char(body) == check
