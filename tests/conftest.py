import pytest

from db import postgres


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
