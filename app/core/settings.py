from imaplib import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'
        case_sensitive = True

    APP_NAME: str = 'Sendora-back'
    APP_VERSION: str = 'v.0'
    ENVIRONMENT: Literal['development', 'production'] = 'development'

    API_PREFIX: str = '/sendora/api'

    HOST: str = 'localhost'
    PORT: int = 8020

    SECRET_KEY_PURPOSE: str = Field(default='secret-key-purpose')
    ALGORITHM_PURPOSE: str = Field(default='Example')

    CORS_ORIGINS: list[str] = Field(default=['*'], description='Allowed CORS origins')

    JWT_SECRET_KEY: str = Field(default='secret-key')
    JWT_ALGORITHM: str = 'HS256'

    DATABASE_URL: str = Field(
        default='mssql+pyodbc://sqlbot:9"BgB4J2@10.11.33.56/SDSD' '?driver=ODBC+Driver+17+for+SQL+Server', )

    REDIS_HOST: str = ""
    REDIS_PORT: int = 0
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_APP_KEY: str = "example-app"

    @validator('JWT_SECRET_KEY')
    def validate_jwt_secret_key(cls, value, values):
        if values.get('ENVIRONMENT') == 'production' and value == 'secret-key':
            raise ValueError('JWT_SECRET_KEY must be changed in production!')
        return value

    @validator('DATABASE_URL')
    def validate_database_url(cls, value, values):
        if values.get('ENVIRONMENT') == 'production' \
                and not value.startswith('mssql'):
            raise ValueError(
                f'У production DATABASE_URL має вказувати на MSSQL, '
                f'а не на {value.split(":")[0]}'
            )
        return value

    @property
    def is_local_db(self) -> bool:
        return not self.DATABASE_URL.startswith('mssql')

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == 'production'

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == 'development'

    @property
    def build_redis_url(self) -> str:
        pass


settings = Settings()
