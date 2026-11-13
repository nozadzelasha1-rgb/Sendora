from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

DEFAULT_JWT_SECRET = "secret-key"
STRONG_JWT_SECRET = "s" * 32
BASE_VALUES: dict[str, Any] = {
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "POSTGRES_DB": "sendora_test",
    "POSTGRES_PORT": 5432,
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the process environment from leaking into Settings under test."""
    for name in (
        "ENVIRONMENT",
        "JWT_SECRET_KEY",
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
        "REFRESH_TOKEN_REUSE_GRACE_SECONDS",
        "CORS_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _settings(**overrides: Any) -> Settings:
    """Build Settings from explicit values only; never read a .env file."""
    values: dict[str, Any] = {**BASE_VALUES, "ENVIRONMENT": "development", **overrides}
    return Settings(_env_file=None, **values)


def test_settings_production_default_secret_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _settings(ENVIRONMENT="production", JWT_SECRET_KEY=DEFAULT_JWT_SECRET)


def test_settings_production_short_secret_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _settings(ENVIRONMENT="production", JWT_SECRET_KEY="s" * 31)


def test_settings_production_secret_counts_utf8_bytes_not_characters() -> None:
    """Each Georgian letter is 3 bytes: 10 letters (30 bytes) fail, 11 (33 bytes) pass."""
    too_short = "ყ" * 10
    long_enough = "ყ" * 11
    assert len(too_short.encode("utf-8")) < 32
    assert len(long_enough.encode("utf-8")) >= 32

    with pytest.raises(ValidationError):
        _settings(ENVIRONMENT="production", JWT_SECRET_KEY=too_short)

    assert _settings(ENVIRONMENT="production", JWT_SECRET_KEY=long_enough)


def test_settings_production_strong_secret_is_accepted() -> None:
    settings = _settings(ENVIRONMENT="production", JWT_SECRET_KEY=STRONG_JWT_SECRET)

    assert settings.ENVIRONMENT == "production"
    assert settings.JWT_SECRET_KEY == STRONG_JWT_SECRET


def test_settings_development_default_secret_is_accepted() -> None:
    settings = _settings(ENVIRONMENT="development", JWT_SECRET_KEY=DEFAULT_JWT_SECRET)

    assert settings.JWT_SECRET_KEY == DEFAULT_JWT_SECRET


def test_settings_missing_environment_raises_validation_error() -> None:
    """ENVIRONMENT has no default: omitting it must fail instead of guessing."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **BASE_VALUES)


def test_settings_missing_environment_with_weak_secret_raises_validation_error() -> (
    None
):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **BASE_VALUES, JWT_SECRET_KEY=DEFAULT_JWT_SECRET)


def test_settings_expiry_default_is_thirty_minutes() -> None:
    assert _settings().JWT_ACCESS_TOKEN_EXPIRE_MINUTES == 30


@pytest.mark.parametrize("minutes", [0, -1])
def test_settings_expiry_not_positive_raises_validation_error(minutes: int) -> None:
    with pytest.raises(ValidationError):
        _settings(JWT_ACCESS_TOKEN_EXPIRE_MINUTES=minutes)


# --- secret validation by environment -----------------------------------------


@pytest.mark.parametrize("environment", ["development", "production"])
def test_settings_strong_secret_accepted_in_every_environment(environment: str) -> None:
    settings = _settings(ENVIRONMENT=environment, JWT_SECRET_KEY=STRONG_JWT_SECRET)

    assert settings.ENVIRONMENT == environment


@pytest.mark.parametrize(
    "secret", [DEFAULT_JWT_SECRET, "s" * 31], ids=["default", "short"]
)
def test_settings_development_weak_secret_accepted(secret: str) -> None:
    assert _settings(ENVIRONMENT="development", JWT_SECRET_KEY=secret)


@pytest.mark.parametrize(
    "secret", [DEFAULT_JWT_SECRET, "s" * 31], ids=["default", "short"]
)
def test_settings_production_weak_secret_raises_validation_error(secret: str) -> None:
    with pytest.raises(ValidationError):
        _settings(ENVIRONMENT="production", JWT_SECRET_KEY=secret)


def test_settings_unknown_environment_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _settings(ENVIRONMENT="staging", JWT_SECRET_KEY=STRONG_JWT_SECRET)


# --- CORS_ORIGINS -------------------------------------------------------------


def test_settings_cors_origins_default_is_empty_list() -> None:
    assert _settings().CORS_ORIGINS == []


def test_settings_production_wildcard_cors_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY=STRONG_JWT_SECRET,
            CORS_ORIGINS=["*"],
        )


def test_settings_development_wildcard_cors_is_accepted() -> None:
    settings = _settings(CORS_ORIGINS=["*"])

    assert settings.CORS_ORIGINS == ["*"]


def test_settings_production_explicit_origins_are_accepted() -> None:
    origins = ["https://app.example.com"]

    settings = _settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY=STRONG_JWT_SECRET,
        CORS_ORIGINS=origins,
    )

    assert settings.CORS_ORIGINS == origins


# --- refresh token settings ---------------------------------------------------


def test_settings_refresh_lifetime_default_is_seven_days() -> None:
    assert _settings().JWT_REFRESH_TOKEN_EXPIRE_DAYS == 7


def test_settings_reuse_grace_default_is_ten_seconds() -> None:
    assert _settings().REFRESH_TOKEN_REUSE_GRACE_SECONDS == 10


@pytest.mark.parametrize("days", [0, -1])
def test_settings_refresh_lifetime_not_positive_raises_validation_error(
    days: int,
) -> None:
    with pytest.raises(ValidationError):
        _settings(JWT_REFRESH_TOKEN_EXPIRE_DAYS=days)


def test_settings_reuse_grace_negative_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        _settings(REFRESH_TOKEN_REUSE_GRACE_SECONDS=-1)


def test_settings_reuse_grace_zero_is_accepted() -> None:
    assert (
        _settings(REFRESH_TOKEN_REUSE_GRACE_SECONDS=0).REFRESH_TOKEN_REUSE_GRACE_SECONDS
        == 0
    )
