from pathlib import Path

SOURCE_ROOTS = (
    Path("config.py"),
    Path("main.py"),
    Path("bot"),
    Path("db"),
    Path("dependecies"),
    Path("manager"),
    Path("routes"),
    Path("utils"),
)
CONFIG_FILES = (
    Path(".env.example"),
    Path(".env.production.example"),
    Path("docker-compose.yml"),
    Path("requirements.txt"),
)
FORBIDDEN = (
    "telegram",
    "aiogram",
    "bot_token",
    "help_chat_id",
    "telegram_notification_timeout_seconds",
    "telegram_client_alert",
    "telegram_manager_alert",
    "telegram_projection_error",
)


def active_files():
    for root in SOURCE_ROOTS:
        if root.is_file():
            yield root
        elif root.exists():
            yield from (
                path
                for path in root.rglob("*.py")
                if "__pycache__" not in path.parts
            )
    yield from CONFIG_FILES


def test_active_backend_has_no_telegram_runtime_reference():
    violations = {}
    for path in active_files():
        source = path.read_text(encoding="utf-8").lower()
        matched = [term for term in FORBIDDEN if term in source]
        if matched:
            violations[str(path)] = matched

    assert violations == {}
