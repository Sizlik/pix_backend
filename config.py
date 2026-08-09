from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from errors import IntegrationNotConfigured

LOCAL_POSTGRES_PASSWORD = "pix_local"
LOCAL_VERIFICATION_SECRET = "local-verification-secret"
LOCAL_RESET_SECRET = "local-reset-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: Literal["local", "test", "production"] = "local"
    postgres_driver: str = "postgresql+asyncpg"
    postgres_user: str = "pix"
    postgres_password: SecretStr = SecretStr(LOCAL_POSTGRES_PASSWORD)
    postgres_db: str = "pix"
    postgres_host: str = "localhost"
    db_port: int = 5431
    redis_url: str = "redis://localhost:6379/0"
    token_lifetime: int = 3600
    verification_token_secret: SecretStr = SecretStr(LOCAL_VERIFICATION_SECRET)
    reset_password_token_secret: SecretStr = SecretStr(LOCAL_RESET_SECRET)
    cors_origins: list[str] = ["http://localhost:3000"]
    enable_scheduler: bool = False

    bot_token: SecretStr | None = None
    chat_id: int | None = None
    help_chat_id: int | None = None
    bitrix_link: SecretStr | None = None
    moysklad_login: str | None = None
    moysklad_password: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MOYSKLAD_PASSWORD",
            "MOYSKLAD_PASWORD",
        ),
    )
    privoz_username: str | None = None
    privoz_password: SecretStr | None = None
    mailersend_token: SecretStr | None = None

    @property
    def database_url(self) -> str:
        password = quote_plus(self.postgres_password.get_secret_value())
        return (
            f"{self.postgres_driver}://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.db_port}/{self.postgres_db}"
        )

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env != "production":
            return self
        if self.postgres_password.get_secret_value() == LOCAL_POSTGRES_PASSWORD:
            raise ValueError("POSTGRES_PASSWORD must be set in production")
        if (
            self.verification_token_secret.get_secret_value()
            == LOCAL_VERIFICATION_SECRET
        ):
            raise ValueError("VERIFICATION_TOKEN_SECRET must be set in production")
        if self.reset_password_token_secret.get_secret_value() == LOCAL_RESET_SECRET:
            raise ValueError("RESET_PASSWORD_TOKEN_SECRET must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def require_value(value: str | None, integration: str) -> str:
    if value is None or not value.strip():
        raise IntegrationNotConfigured(integration)
    return value


def require_secret(value: SecretStr | None, integration: str) -> str:
    if value is None or not value.get_secret_value():
        raise IntegrationNotConfigured(integration)
    return value.get_secret_value()
