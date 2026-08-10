import pytest

from config import Settings
from errors import IntegrationNotConfigured


def test_order_chat_is_off_and_uses_exact_safe_limits_by_default():
    settings = Settings(_env_file=None)

    assert settings.enable_moysklad_order_chat is False
    assert settings.minio_bucket == "pix-order-chat"
    assert settings.minio_secure is False
    assert settings.chat_attachment_max_bytes == 20 * 1024 * 1024
    assert settings.chat_attachment_max_count == 10
    assert settings.chat_outbox_max_attempts == 8
    assert settings.chat_outbox_base_delay_seconds == 5


def test_enabled_order_chat_requires_storage_and_webhook_secrets():
    settings = Settings(
        _env_file=None,
        enable_moysklad_order_chat=True,
    )

    with pytest.raises(IntegrationNotConfigured, match="moysklad order chat"):
        settings.require_order_chat()


def test_enabled_order_chat_returns_secret_values_only_at_call_time():
    settings = Settings(
        _env_file=None,
        enable_moysklad_order_chat=True,
        moysklad_order_chat_webhook_secret="webhook-secret",
        minio_endpoint="localhost:9000",
        minio_access_key="pix-local",
        minio_secret_key="pix-local-secret",
    )

    resolved = settings.require_order_chat()

    assert resolved.endpoint == "localhost:9000"
    assert resolved.access_key == "pix-local"
    assert resolved.secret_key == "pix-local-secret"
    assert resolved.webhook_secret == "webhook-secret"


def test_order_chat_limits_must_be_positive():
    with pytest.raises(ValueError):
        Settings(_env_file=None, chat_attachment_max_count=0)
