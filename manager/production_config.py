import re
from dataclasses import dataclass
from urllib.parse import urlparse

from pydantic import SecretStr

from config import (
    LOCAL_POSTGRES_PASSWORD,
    LOCAL_RESET_SECRET,
    LOCAL_VERIFICATION_SECRET,
    Settings,
)

MINIMUM_SECRET_LENGTH = 32
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True, slots=True)
class ProductionConfigIssue:
    variable: str
    reason: str


def validate_production_settings(
    settings: Settings,
    *,
    require_order_chat: bool,
) -> tuple[ProductionConfigIssue, ...]:
    issues: list[ProductionConfigIssue] = []

    if settings.app_env != "production":
        _add(issues, "APP_ENV", "must be production")
    _require_text(issues, "POSTGRES_DRIVER", settings.postgres_driver)
    _require_text(issues, "POSTGRES_USER", settings.postgres_user)
    _require_text(issues, "POSTGRES_DB", settings.postgres_db)
    _require_text(issues, "POSTGRES_HOST", settings.postgres_host)
    if not 1 <= settings.db_port <= 65535:
        _add(issues, "DB_PORT", "must be a valid TCP port")
    _require_strong_secret(
        issues,
        "POSTGRES_PASSWORD",
        settings.postgres_password,
        forbidden=LOCAL_POSTGRES_PASSWORD,
    )
    _require_strong_secret(
        issues,
        "VERIFICATION_TOKEN_SECRET",
        settings.verification_token_secret,
        forbidden=LOCAL_VERIFICATION_SECRET,
    )
    _require_strong_secret(
        issues,
        "RESET_PASSWORD_TOKEN_SECRET",
        settings.reset_password_token_secret,
        forbidden=LOCAL_RESET_SECRET,
    )
    if not _is_redis_url(settings.redis_url):
        _add(issues, "REDIS_URL", "must be a Redis URL")
    if settings.token_lifetime <= 0:
        _add(issues, "TOKEN_LIFETIME", "must be positive")
    if not settings.cors_origins or not all(
        _is_https_origin(origin) for origin in settings.cors_origins
    ):
        _add(issues, "CORS_ORIGINS", "must contain only HTTPS origins")
    if not _is_public_api_url(settings.next_public_backend_url):
        _add(
            issues,
            "NEXT_PUBLIC_BACKEND_URL",
            "must be an HTTPS origin ending in /api_v1",
        )

    if require_order_chat:
        _validate_order_chat(settings, issues)
    if settings.enable_order_chat_email_notifications:
        _validate_order_chat_email(settings, issues)

    return tuple(issues)


def _validate_order_chat(
    settings: Settings,
    issues: list[ProductionConfigIssue],
) -> None:
    if not settings.enable_moysklad_order_chat:
        _add(issues, "ENABLE_MOYSKLAD_ORDER_CHAT", "must be enabled")
    _require_text(issues, "MOYSKLAD_LOGIN", settings.moysklad_login)
    _require_secret(issues, "MOYSKLAD_PASSWORD", settings.moysklad_password)
    _require_strong_secret(
        issues,
        "MOYSKLAD_CHAT_EXTENSION_SECRET",
        settings.moysklad_chat_extension_secret,
    )

    if not _is_minio_endpoint(settings.minio_endpoint):
        _add(issues, "MINIO_ENDPOINT", "must be host:port without a URL scheme")
    _require_text(issues, "MINIO_ACCESS_KEY", settings.minio_access_key)
    _require_strong_secret(
        issues,
        "MINIO_SECRET_KEY",
        settings.minio_secret_key,
    )
    if not BUCKET_PATTERN.fullmatch(settings.minio_bucket):
        _add(issues, "MINIO_BUCKET", "must be a valid S3 bucket name")


def _validate_order_chat_email(
    settings: Settings,
    issues: list[ProductionConfigIssue],
) -> None:
    if not _is_email_address(settings.order_chat_manager_email):
        _add(issues, "ORDER_CHAT_MANAGER_EMAIL", "must be a valid email address")
    _require_secret(issues, "MAILERSEND_TOKEN", settings.mailersend_token)
    if settings.pix_public_site_url is None or not _is_https_origin(
        settings.pix_public_site_url
    ):
        _add(issues, "PIX_PUBLIC_SITE_URL", "must be an HTTPS origin")


def _add(
    issues: list[ProductionConfigIssue],
    variable: str,
    reason: str,
) -> None:
    issues.append(ProductionConfigIssue(variable=variable, reason=reason))


def _secret_value(value: SecretStr | None) -> str:
    return "" if value is None else value.get_secret_value()


def _require_text(
    issues: list[ProductionConfigIssue],
    variable: str,
    value: str | None,
) -> None:
    if value is None or not value.strip():
        _add(issues, variable, "is required")


def _require_secret(
    issues: list[ProductionConfigIssue],
    variable: str,
    value: SecretStr | None,
) -> None:
    if not _secret_value(value):
        _add(issues, variable, "is required")


def _require_strong_secret(
    issues: list[ProductionConfigIssue],
    variable: str,
    value: SecretStr | None,
    *,
    forbidden: str | None = None,
) -> None:
    secret = _secret_value(value)
    if len(secret) < MINIMUM_SECRET_LENGTH or secret == forbidden:
        _add(issues, variable, "must be replaced with a strong secret")


def _is_https_origin(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in ("", "/")
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _is_email_address(value: str | None) -> bool:
    return (
        value is not None
        and value == value.strip()
        and len(value) <= 320
        and "\r" not in value
        and "\n" not in value
        and EMAIL_PATTERN.fullmatch(value) is not None
    )


def _is_public_api_url(value: str | None) -> bool:
    if value is None:
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and parsed.path == "/api_v1"
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _is_redis_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme in {"redis", "rediss"}
        and bool(parsed.hostname)
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _is_minio_endpoint(value: str | None) -> bool:
    if value is None or "://" in value or "/" in value:
        return False
    try:
        parsed = urlparse(f"//{value}")
        return (
            bool(parsed.hostname)
            and parsed.port is not None
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False
