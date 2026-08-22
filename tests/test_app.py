import importlib
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import Settings
from errors import IntegrationNotConfigured


class LifecycleComponent:
    def __init__(self, name, events):
        self.name = name
        self.events = events

    async def start(self):
        self.events.append(f"start:{self.name}")

    async def stop(self):
        self.events.append(f"stop:{self.name}")


def lifecycle_settings(**overrides):
    values = {
        "_env_file": None,
        "app_env": "local",
        "enable_moysklad_order_chat": True,
        "minio_endpoint": "localhost:9000",
        "minio_access_key": "test",
        "minio_secret_key": "test-secret",
        "enable_order_chat_email_notifications": True,
        "order_chat_manager_email": "manager@example.com",
        "pix_public_site_url": "https://pixlogistic.com",
        "mailersend_token": "smtp-token",
        "enable_scheduler": False,
    }
    values.update(overrides)
    return Settings(**values)


@contextmanager
def patched_lifecycle(monkeypatch, *, storage_failure=None):
    events = []
    chat = LifecycleComponent("chat", events)
    notifications = LifecycleComponent("notifications", events)
    inbox = LifecycleComponent("inbox", events)
    dispatcher = LifecycleComponent("dispatcher", events)

    class Storage:
        async def ensure_bucket(self):
            events.append("ensure:storage")
            if storage_failure is not None:
                raise storage_failure

    monkeypatch.setattr("main.get_chat_realtime", lambda: chat)
    monkeypatch.setattr("main.get_notification_realtime", lambda: notifications)
    monkeypatch.setattr("main.get_operator_inbox_realtime", lambda: inbox)
    monkeypatch.setattr(
        "main.build_order_chat_email_dispatcher",
        lambda settings: dispatcher,
    )
    monkeypatch.setattr("main.build_order_chat_storage", lambda settings: Storage())
    yield events


def test_import_does_not_call_external_http(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("external HTTP was called during import")

    monkeypatch.setattr(requests, "get", fail)
    monkeypatch.setattr(requests, "post", fail)

    module = importlib.import_module("main")

    assert isinstance(module.app, FastAPI)


def test_health_is_offline_and_stable():
    from main import create_app

    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.get("/api_v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_integration_configuration_error_maps_to_503():
    from main import create_app

    app = create_app(Settings(_env_file=None, app_env="test"))

    @app.get("/_integration-test")
    async def integration_test():
        raise IntegrationNotConfigured("moysklad")

    with TestClient(app) as client:
        response = client.get("/_integration-test")

    assert response.status_code == 503
    assert response.json() == {"detail": "moysklad is not configured"}


def test_telegram_and_bot_routes_are_not_mounted():
    from main import create_app

    app = create_app(Settings(_env_file=None, app_env="test"))
    paths = {route.path for route in app.routes}

    assert "/api_v1/users/telegram/{telegram_id}" not in paths
    assert not any(path.startswith("/api_v1/bot") for path in paths)


def test_capabilities_report_the_app_settings_feature_flag(monkeypatch):
    from main import create_app

    storage = SimpleNamespace(ensure_bucket=AsyncMock())
    built_from = []

    def build_storage(chat_settings):
        built_from.append(chat_settings)
        return storage

    monkeypatch.setattr("main.build_order_chat_storage", build_storage)
    app = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            enable_moysklad_order_chat=True,
            minio_endpoint="localhost:9000",
            minio_access_key="test",
            minio_secret_key="test-secret",
        )
    )

    with TestClient(app) as client:
        response = client.get("/api_v1/capabilities")

    assert response.status_code == 200
    assert response.json() == {"moysklad_order_chat": True}
    assert built_from[0].endpoint == "localhost:9000"
    assert built_from[0].access_key == "test"


def test_lifespan_starts_inbox_and_email_independently_of_scheduler(monkeypatch):
    from main import create_app

    with patched_lifecycle(monkeypatch) as events:
        with TestClient(create_app(lifecycle_settings())) as client:
            assert client.get("/api_v1/health").status_code == 200
            assert events == [
                "start:chat",
                "start:notifications",
                "start:inbox",
                "start:dispatcher",
                "ensure:storage",
            ]

    assert events == [
        "start:chat",
        "start:notifications",
        "start:inbox",
        "start:dispatcher",
        "ensure:storage",
        "stop:dispatcher",
        "stop:inbox",
        "stop:notifications",
        "stop:chat",
    ]


def test_lifespan_cleans_started_components_when_storage_startup_fails(monkeypatch):
    from main import create_app

    with patched_lifecycle(
        monkeypatch,
        storage_failure=RuntimeError("storage unavailable"),
    ) as events:
        with pytest.raises(RuntimeError, match="storage unavailable"):
            with TestClient(create_app(lifecycle_settings())):
                pass

    assert events == [
        "start:chat",
        "start:notifications",
        "start:inbox",
        "start:dispatcher",
        "ensure:storage",
        "stop:dispatcher",
        "stop:inbox",
        "stop:notifications",
        "stop:chat",
    ]


def test_disabled_email_does_not_build_or_start_dispatcher(monkeypatch):
    from main import create_app

    built = []
    monkeypatch.setattr(
        "main.build_order_chat_email_dispatcher",
        lambda settings: built.append(settings),
    )
    app = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            enable_order_chat_email_notifications=False,
        )
    )

    with TestClient(app) as client:
        assert client.get("/api_v1/health").status_code == 200

    assert built == []
