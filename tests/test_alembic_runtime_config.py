import runpy
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.ext import asyncio as sqlalchemy_asyncio

from alembic import context
from db import postgres


def test_alembic_offline_mode_uses_runtime_database_url(monkeypatch):
    runtime_url = (
        "postgresql+asyncpg://runtime-user:runtime-password"
        "@database.example:5544/runtime-db"
    )
    configured: dict[str, object] = {}

    monkeypatch.setattr(postgres, "DATABASE_URL", runtime_url)
    monkeypatch.setattr(
        context,
        "config",
        SimpleNamespace(
            config_file_name=None,
            get_main_option=lambda _name: "postgresql+asyncpg://stale-config",
        ),
        raising=False,
    )
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    monkeypatch.setattr(context, "configure", lambda **kwargs: configured.update(kwargs))
    monkeypatch.setattr(context, "run_migrations", lambda: None)

    @contextmanager
    def begin_transaction():
        yield

    monkeypatch.setattr(context, "begin_transaction", begin_transaction)

    runpy.run_path(
        Path("alembic/env.py"),
        run_name="__test_alembic_runtime_config__",
    )

    assert configured["url"] == runtime_url


def test_alembic_online_mode_uses_runtime_database_url(monkeypatch):
    runtime_url = (
        "postgresql+asyncpg://runtime-user:runtime-password"
        "@database.example:5544/runtime-db"
    )
    configured: dict[str, object] = {}

    class FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def run_sync(self, callback):
            callback(self)

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        async def dispose(self):
            return None

    def create_async_engine(url, **_kwargs):
        configured["url"] = url
        return FakeEngine()

    def async_engine_from_config(_section, **_kwargs):
        configured["url"] = "postgresql+asyncpg://stale-config"
        return FakeEngine()

    monkeypatch.setattr(postgres, "DATABASE_URL", runtime_url)
    monkeypatch.setattr(
        context,
        "config",
        SimpleNamespace(
            config_file_name=None,
            config_ini_section="alembic",
            get_section=lambda *_args: {"sqlalchemy.url": "stale-config"},
        ),
        raising=False,
    )
    monkeypatch.setattr(context, "is_offline_mode", lambda: False)
    monkeypatch.setattr(context, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(context, "run_migrations", lambda: None)

    @contextmanager
    def begin_transaction():
        yield

    monkeypatch.setattr(context, "begin_transaction", begin_transaction)
    monkeypatch.setattr(
        sqlalchemy_asyncio,
        "create_async_engine",
        create_async_engine,
    )
    monkeypatch.setattr(
        sqlalchemy_asyncio,
        "async_engine_from_config",
        async_engine_from_config,
    )

    runpy.run_path(
        Path("alembic/env.py"),
        run_name="__test_alembic_runtime_config__",
    )

    assert configured["url"] == runtime_url
