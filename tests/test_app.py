import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import Settings
from errors import IntegrationNotConfigured


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
