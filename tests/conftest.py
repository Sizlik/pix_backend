from urllib.parse import urlsplit

import pytest

from db import postgres


def pytest_addoption(parser):
    parser.addoption(
        "--migration-database-url",
        action="store",
        default=None,
        help="Loopback PostgreSQL URL for destructive migration tests",
    )


@pytest.fixture
def migration_database_url(request):
    value = request.config.getoption("--migration-database-url")
    if value is None:
        pytest.skip("requires --migration-database-url")
    host = urlsplit(value).hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("migration test database must use a loopback host")
    return value


class TrackedSessionFactory:
    def __init__(self):
        self.active = 0
        self.peak = 0

    def __call__(self):
        factory = self

        class SessionContext:
            async def __aenter__(self):
                factory.active += 1
                factory.peak = max(factory.peak, factory.active)
                return object()

            async def __aexit__(self, exc_type, exc_value, traceback):
                factory.active -= 1

        return SessionContext()


@pytest.fixture
def tracked_session_factory(monkeypatch):
    factory = TrackedSessionFactory()
    monkeypatch.setattr(postgres, "async_session_maker", factory)
    return factory
