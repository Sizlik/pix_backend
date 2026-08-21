from dataclasses import dataclass
from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from errors import IntegrationNotConfigured

LOCAL_POSTGRES_PASSWORD = "pix_local"
LOCAL_VERIFICATION_SECRET = "local-verification-secret"
LOCAL_RESET_SECRET = "local-reset-secret"


@dataclass(frozen=True, slots=True)
class OrderChatSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool
    webhook_secret: str
    attachment_max_bytes: int
    attachment_max_count: int
    outbox_max_attempts: int
    outbox_base_delay_seconds: int


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
    enable_moysklad_order_chat: bool = False

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
    next_public_backend_url: str | None = None
    pgadmin_default_email: str | None = None
    pgadmin_default_password: SecretStr | None = None
    moysklad_chat_extension_secret: SecretStr | None = None
    moysklad_order_chat_webhook_secret: SecretStr | None = None
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: SecretStr | None = None
    minio_bucket: str = "pix-order-chat"
    minio_secure: bool = False
    chat_attachment_max_bytes: int = Field(20 * 1024 * 1024, gt=0)
    chat_attachment_max_count: int = Field(10, gt=0)
    chat_outbox_max_attempts: int = Field(8, gt=0)
    chat_outbox_base_delay_seconds: int = Field(5, gt=0)

    @property
    def database_url(self) -> str:
        password = quote_plus(self.postgres_password.get_secret_value())
        return (
            f"{self.postgres_driver}://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.db_port}/{self.postgres_db}"
        )

    def require_order_chat(self) -> OrderChatSettings:
        if not self.enable_moysklad_order_chat:
            raise IntegrationNotConfigured("moysklad order chat")
        endpoint = require_value(self.minio_endpoint, "moysklad order chat")
        access_key = require_value(self.minio_access_key, "moysklad order chat")
        secret_key = require_secret(self.minio_secret_key, "moysklad order chat")
        webhook_secret = require_secret(
            self.moysklad_order_chat_webhook_secret,
            "moysklad order chat",
        )
        return OrderChatSettings(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            bucket=self.minio_bucket,
            secure=self.minio_secure,
            webhook_secret=webhook_secret,
            attachment_max_bytes=self.chat_attachment_max_bytes,
            attachment_max_count=self.chat_attachment_max_count,
            outbox_max_attempts=self.chat_outbox_max_attempts,
            outbox_base_delay_seconds=self.chat_outbox_base_delay_seconds,
        )

    def require_chat_extension_secret(self) -> str:
        return require_secret(
            self.moysklad_chat_extension_secret,
            "moysklad chat extension",
        )

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env != "production":
            return self
        if self.postgres_password.get_secret_value() == LOCAL_POSTGRES_PASSWORD:
            raise ValueError("POSTGRES_PASSWORD must be set in production")
        if self.verification_token_secret.get_secret_value() == LOCAL_VERIFICATION_SECRET:
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
