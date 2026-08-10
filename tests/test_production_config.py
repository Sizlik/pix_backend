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


def test_order_chat_preflight_names_every_missing_runtime_dependency():
    settings = production_settings(enable_moysklad_order_chat=False)

    assert issue_names(settings, require_order_chat=True) == {
        "ENABLE_MOYSKLAD_ORDER_CHAT",
        "MOYSKLAD_LOGIN",
        "MOYSKLAD_PASSWORD",
        "BOT_TOKEN",
        "CHAT_ID",
        "HELP_CHAT_ID",
        "MOYSKLAD_ORDER_CHAT_WEBHOOK_SECRET",
        "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
    }


def test_order_chat_preflight_accepts_complete_host_network_configuration():
    settings = production_settings(
        enable_moysklad_order_chat=True,
        moysklad_login="account@example.com",
        moysklad_password="moysklad-api-token",
        bot_token="123456789:telegram-bot-token",
        chat_id=-1001234567890,
        help_chat_id=-1009876543210,
        moysklad_order_chat_webhook_secret=(
            "order_chat_webhook_secret_0123456789ABCDEF"
        ),
        minio_endpoint="localhost:9000",
        minio_access_key="pix-order-chat",
        minio_secret_key="minio-secret-that-is-long-enough",
    )

    assert validate_production_settings(settings, require_order_chat=True) == ()


def test_preflight_never_returns_secret_or_sensitive_values():
    sensitive_values = {
        "database-secret-value",
        "verification-secret-value",
        "reset-secret-value",
        "redis-secret-value",
        "moysklad-login-value",
        "moysklad-password-value",
        "telegram-token-value",
        "1234567890",
        "webhook/secret/value",
        "minio-access-value",
        "minio-secret-value",
    }
    settings = Settings(
        _env_file=None,
        app_env="local",
        postgres_password="database-secret-value",
        verification_token_secret="verification-secret-value",
        reset_password_token_secret="reset-secret-value",
        redis_url="redis://:redis-secret-value@localhost:6379/0",
        cors_origins=["http://pixlogistic.com"],
        next_public_backend_url="http://pixlogistic.com/api_v1",
        enable_moysklad_order_chat=True,
        moysklad_login="moysklad-login-value",
        moysklad_password="moysklad-password-value",
        bot_token="telegram-token-value",
        chat_id=1234567890,
        help_chat_id=1234567890,
        moysklad_order_chat_webhook_secret="webhook/secret/value",
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
