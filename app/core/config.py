from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    APP_NAME: str = "Sendora-back"
    APP_VERSION: str = "v.0"
    ENVIRONMENT: Literal["development", "production"]

    API_PREFIX: str = "/v0"

    HOST: str = "localhost"
    PORT: int = 8020

    SECRET_KEY_PURPOSE: str = Field(default="secret-key-purpose")
    ALGORITHM_PURPOSE: str = Field(default="Example")

    CORS_ORIGINS: list[str] = Field(default=[], description="Allowed CORS origins")

    JWT_SECRET_KEY: str = Field(default="secret-key")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, gt=0)
    REFRESH_TOKEN_REUSE_GRACE_SECONDS: int = Field(default=10, ge=0)

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int

    REDIS_HOST: str = ""
    REDIS_PORT: int = 0
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_APP_KEY: str = "example-app"

    @model_validator(mode="after")
    def validate_jwt_secret_key(self) -> Self:
        """Reject a default or weak JWT secret outside development."""
        if self.ENVIRONMENT != "development" and (
            self.JWT_SECRET_KEY == "secret-key"
            or len(self.JWT_SECRET_KEY.encode("utf-8")) < 32
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be changed and at least 32 bytes "
                "outside development!"
            )
        return self

    @model_validator(mode="after")
    def validate_cors_origins(self) -> Self:
        """Reject a wildcard CORS origin in production."""
        if self.ENVIRONMENT == "production" and "*" in self.CORS_ORIGINS:
            raise ValueError('CORS_ORIGINS must not contain "*" in production!')
        return self

    # @validator('DATABASE_URL')
    # def validate_database_url(cls, value, values):
    #     if values.get('ENVIRONMENT') == 'production' \
    #             and not value.startswith('mssql'):
    #         raise ValueError(
    #             f'У production DATABASE_URL має вказувати на MSSQL, '
    #             f'а не на {value.split(":")[0]}'
    #         )
    #     return value

    # @property
    # def is_local_db(self) -> bool:
    #     return not self.DATABASE_URL.startswith('mssql')
    #
    # @property
    # def is_production(self) -> bool:
    #     return self.ENVIRONMENT == 'production'
    #
    # @property
    # def is_development(self) -> bool:
    #     return self.ENVIRONMENT == 'development'
    #
    # @property
    # def build_redis_url(self) -> str:
    #     pass

    @property
    def build_db_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@localhost:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


settings = Settings()
