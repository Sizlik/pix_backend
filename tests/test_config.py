import pytest
from pydantic import ValidationError

from config import Settings, require_value
from errors import IntegrationNotConfigured


def test_local_settings_have_offline_safe_defaults():
    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.enable_scheduler is False
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.redis_url == "redis://localhost:6379/0"


def test_legacy_moysklad_password_alias(monkeypatch):
    monkeypatch.delenv("MOYSKLAD_PASSWORD", raising=False)
    monkeypatch.setenv("MOYSKLAD_PASWORD", "legacy-value")

    settings = Settings(_env_file=None)

    assert settings.moysklad_password is not None
    assert settings.moysklad_password.get_secret_value() == "legacy-value"


def test_production_rejects_local_auth_secrets(monkeypatch):
    monkeypatch.delenv("VERIFICATION_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("RESET_PASSWORD_TOKEN_SECRET", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production")


def test_missing_integration_value_is_sanitized():
    with pytest.raises(
        IntegrationNotConfigured,
        match="moysklad is not configured",
    ):
        require_value(None, "moysklad")


def test_settings_have_no_telegram_fields():
    fields = Settings.model_fields

    assert "bot_token" not in fields
    assert "chat_id" not in fields
    assert "help_chat_id" not in fields
    assert "telegram_notification_timeout_seconds" not in fields
