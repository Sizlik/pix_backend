from pathlib import Path

from dotenv import dotenv_values

from config import Settings
from manager.production_config import validate_production_settings
from scripts.check_production_config import main as production_preflight_main


def production_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "app_env": "production",
        "postgres_password": "database-secret-that-is-long-enough",
        "verification_token_secret": "verification-secret-that-is-long-enough",
        "reset_password_token_secret": "password-reset-secret-that-is-long-enough",
        "cors_origins": ["https://pixlogistic.com"],
        "next_public_backend_url": "https://pixlogistic.com/api_v1",
    }
    values.update(overrides)
    return Settings(**values)


def issue_names(settings: Settings, *, require_order_chat: bool = False) -> set[str]:
    return {
        issue.variable
        for issue in validate_production_settings(
            settings,
            require_order_chat=require_order_chat,
        )
    }


def test_base_preflight_accepts_safe_production_settings_with_chat_disabled():
    settings = production_settings(enable_moysklad_order_chat=False)

    assert validate_production_settings(settings, require_order_chat=False) == ()


def test_base_preflight_rejects_nonproduction_and_public_url_misconfiguration():
    settings = Settings(
        _env_file=None,
        app_env="local",
        cors_origins=["*", "http://pixlogistic.com"],
        next_public_backend_url="https://user:secret@pixlogistic.com/api_v1?token=x",
    )

    assert issue_names(settings) == {
        "APP_ENV",
        "POSTGRES_PASSWORD",
        "VERIFICATION_TOKEN_SECRET",
        "RESET_PASSWORD_TOKEN_SECRET",
        "CORS_ORIGINS",
        "NEXT_PUBLIC_BACKEND_URL",
    }


def test_base_preflight_rejects_unusable_database_redis_and_token_settings():
    settings = production_settings(
        postgres_driver="",
        postgres_user="",
        postgres_db="",
        postgres_host="",
        db_port=0,
        redis_url="https://redis.invalid",
        token_lifetime=0,
    )

    assert issue_names(settings) == {
        "POSTGRES_DRIVER",
        "POSTGRES_USER",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "DB_PORT",
        "REDIS_URL",
        "TOKEN_LIFETIME",
    }


def test_order_chat_preflight_names_every_missing_runtime_dependency():
    settings = production_settings(enable_moysklad_order_chat=False)

    assert issue_names(settings, require_order_chat=True) == {
        "ENABLE_MOYSKLAD_ORDER_CHAT",
        "MOYSKLAD_LOGIN",
        "MOYSKLAD_PASSWORD",
        "MOYSKLAD_CHAT_EXTENSION_SECRET",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
    }


def test_order_chat_preflight_accepts_complete_host_network_configuration():
    settings = production_settings(
        enable_moysklad_order_chat=True,
        moysklad_login="account@example.com",
        moysklad_password="moysklad-api-token",
        moysklad_chat_extension_secret="x" * 32,
        minio_endpoint="localhost:9000",
        minio_access_key="pix-order-chat",
        minio_secret_key="minio-secret-that-is-long-enough",
    )

    assert validate_production_settings(settings, require_order_chat=True) == ()


def test_email_preflight_requires_recipient_token_and_public_https_origin_when_enabled():
    settings = production_settings(
        enable_order_chat_email_notifications=True,
    )

    assert issue_names(settings) == {
        "ORDER_CHAT_MANAGER_EMAIL",
        "MAILERSEND_TOKEN",
        "PIX_PUBLIC_SITE_URL",
    }


def test_email_preflight_accepts_complete_configuration_without_scheduler():
    settings = production_settings(
        enable_scheduler=False,
        enable_order_chat_email_notifications=True,
        order_chat_manager_email="Pixtool22@gmail.com",
        mailersend_token="smtp-bz-token",
        pix_public_site_url="https://pixlogistic.com",
    )

    assert validate_production_settings(settings, require_order_chat=False) == ()


def test_email_preflight_rejects_malformed_address_and_non_origin_site_url():
    settings = production_settings(
        enable_order_chat_email_notifications=True,
        order_chat_manager_email="Bcc: victim@example.com\r\n",
        mailersend_token="smtp-bz-token",
        pix_public_site_url="https://pixlogistic.com/dashboard?token=private",
    )

    assert issue_names(settings) == {
        "ORDER_CHAT_MANAGER_EMAIL",
        "PIX_PUBLIC_SITE_URL",
    }


def test_email_preflight_is_not_required_when_delivery_is_disabled():
    settings = production_settings(
        enable_order_chat_email_notifications=False,
        order_chat_manager_email=None,
        mailersend_token=None,
        pix_public_site_url=None,
    )

    assert validate_production_settings(settings, require_order_chat=False) == ()


def test_order_chat_preflight_rejects_short_extension_secret():
    settings = production_settings(
        enable_moysklad_order_chat=True,
        moysklad_login="account@example.com",
        moysklad_password="moysklad-api-token",
        moysklad_chat_extension_secret="x" * 31,
        minio_endpoint="localhost:9000",
        minio_access_key="pix-order-chat",
        minio_secret_key="minio-secret-that-is-long-enough",
    )

    assert issue_names(settings, require_order_chat=True) == {
        "MOYSKLAD_CHAT_EXTENSION_SECRET"
    }


def test_preflight_never_returns_secret_or_sensitive_values():
    sensitive_values = {
        "database-secret-value",
        "verification-secret-value",
        "reset-secret-value",
        "redis-secret-value",
        "moysklad-login-value",
        "moysklad-password-value",
        "extension-secret-value",
        "minio-access-value",
        "minio-secret-value",
    }
    settings = Settings(
        _env_file=None,
        app_env="local",
        postgres_password="database-secret-value",
        verification_token_secret="verification-secret-value",
        reset_password_token_secret="reset-secret-value",
        redis_url="https://:redis-secret-value@localhost:6379/0",
        cors_origins=["http://pixlogistic.com"],
        next_public_backend_url="http://pixlogistic.com/api_v1",
        enable_moysklad_order_chat=True,
        moysklad_login="moysklad-login-value",
        moysklad_password="moysklad-password-value",
        moysklad_chat_extension_secret="extension-secret-value",
        minio_endpoint="https://minio.invalid/path",
        minio_access_key="minio-access-value",
        minio_secret_key="minio-secret-value",
    )

    rendered = "\n".join(
        f"{issue.variable}: {issue.reason}"
        for issue in validate_production_settings(
            settings,
            require_order_chat=True,
        )
    )

    assert rendered
    assert "MOYSKLAD_PASWORD" not in rendered
    for sensitive_value in sensitive_values:
        assert sensitive_value not in rendered


def test_preflight_cli_accepts_safe_base_environment(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "POSTGRES_PASSWORD",
        "database-secret-that-is-long-enough",
    )
    monkeypatch.setenv(
        "VERIFICATION_TOKEN_SECRET",
        "verification-secret-that-is-long-enough",
    )
    monkeypatch.setenv(
        "RESET_PASSWORD_TOKEN_SECRET",
        "password-reset-secret-that-is-long-enough",
    )
    monkeypatch.setenv("CORS_ORIGINS", '["https://pixlogistic.com"]')
    monkeypatch.setenv(
        "NEXT_PUBLIC_BACKEND_URL",
        "https://pixlogistic.com/api_v1",
    )

    result = production_preflight_main([])

    assert result == 0
    assert capsys.readouterr().out == "Production configuration is valid.\n"


def test_preflight_cli_reports_only_safe_issue_metadata(
    monkeypatch,
    capsys,
):
    database_secret = "short-database-secret"
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("POSTGRES_PASSWORD", database_secret)
    monkeypatch.setenv("NEXT_PUBLIC_BACKEND_URL", "http://invalid.example/api_v1")

    result = production_preflight_main([])
    output = capsys.readouterr().out

    assert result == 1
    assert "APP_ENV: must be production" in output
    assert "NEXT_PUBLIC_BACKEND_URL" in output
    assert database_secret not in output


def test_preflight_cli_sanitizes_settings_parse_errors(monkeypatch, capsys):
    leaked_value = "value-that-must-not-appear"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("POSTGRES_PASSWORD", leaked_value)
    monkeypatch.setenv("DB_PORT", leaked_value)

    result = production_preflight_main([])

    assert result == 1
    assert capsys.readouterr().out == "Production configuration could not be parsed.\n"


def test_production_environment_template_is_complete_and_copy_safe():
    template_path = Path(".env.production.example")
    values = dotenv_values(template_path)
    expected_keys = {
        "APP_ENV",
        "POSTGRES_DRIVER",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "DB_PORT",
        "REDIS_URL",
        "TOKEN_LIFETIME",
        "VERIFICATION_TOKEN_SECRET",
        "RESET_PASSWORD_TOKEN_SECRET",
        "CORS_ORIGINS",
        "ENABLE_SCHEDULER",
        "ENABLE_MOYSKLAD_ORDER_CHAT",
        "ENABLE_ORDER_CHAT_EMAIL_NOTIFICATIONS",
        "ORDER_CHAT_MANAGER_EMAIL",
        "PIX_PUBLIC_SITE_URL",
        "BITRIX_LINK",
        "MOYSKLAD_LOGIN",
        "MOYSKLAD_PASSWORD",
        "MOYSKLAD_CHAT_EXTENSION_SECRET",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINIO_BUCKET",
        "MINIO_SECURE",
        "CHAT_ATTACHMENT_MAX_BYTES",
        "CHAT_ATTACHMENT_MAX_COUNT",
        "PRIVOZ_USERNAME",
        "PRIVOZ_PASSWORD",
        "MAILERSEND_TOKEN",
        "NEXT_PUBLIC_BACKEND_URL",
        "NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT",
        "PGADMIN_DEFAULT_EMAIL",
        "PGADMIN_DEFAULT_PASSWORD",
    }
    blank_sensitive_keys = {
        "POSTGRES_PASSWORD",
        "VERIFICATION_TOKEN_SECRET",
        "RESET_PASSWORD_TOKEN_SECRET",
        "BITRIX_LINK",
        "MOYSKLAD_LOGIN",
        "MOYSKLAD_PASSWORD",
        "MOYSKLAD_CHAT_EXTENSION_SECRET",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "PRIVOZ_USERNAME",
        "PRIVOZ_PASSWORD",
        "MAILERSEND_TOKEN",
        "ORDER_CHAT_MANAGER_EMAIL",
        "PGADMIN_DEFAULT_EMAIL",
        "PGADMIN_DEFAULT_PASSWORD",
    }

    assert set(values) == expected_keys
    assert values["APP_ENV"] == "production"
    assert values["ENABLE_MOYSKLAD_ORDER_CHAT"] == "false"
    assert values["ENABLE_ORDER_CHAT_EMAIL_NOTIFICATIONS"] == "false"
    assert values["PIX_PUBLIC_SITE_URL"] == "https://pixlogistic.com"
    assert values["MINIO_ENDPOINT"] == "localhost:9000"
    assert values["MINIO_BUCKET"] == "pix-order-chat"
    assert values["NEXT_PUBLIC_BACKEND_URL"] == (
        "https://pixlogistic.com/api_v1"
    )
    assert values["NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT"] == "false"
    assert all(values[key] == "" for key in blank_sensitive_keys)
    assert "MOYSKLAD_PASWORD" not in values

    parsed = Settings(_env_file=template_path)
    assert parsed.app_env == "production"
    assert parsed.enable_moysklad_order_chat is False
