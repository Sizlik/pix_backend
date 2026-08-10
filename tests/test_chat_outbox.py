from dataclasses import dataclass
from uuid import UUID

from manager.chat_outbox import OrderChatOutboxWorker

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")


@dataclass
class Event:
    id: UUID
    event_type: str
    order_id: UUID
    payload: dict
    attempts: int = 1


class FakeRepository:
    def __init__(self, event):
        self.event = event
        self.completed = []
        self.retried = []
        self.released = []

    async def claim_due_event(self):
        event, self.event = self.event, None
        return event

    async def complete_event(self, event_id):
        self.completed.append(event_id)

    async def retry_event(self, event, error, max_attempts, base_seconds):
        self.retried.append((event.id, type(error).__name__, max_attempts, base_seconds))
        return "pending"

    async def release_claim(self, event_id, delay_seconds):
        self.released.append((event_id, delay_seconds))


class FakeLock:
    def __init__(self, acquired=True):
        self.acquired = acquired

    async def __aenter__(self):
        return self.acquired

    async def __aexit__(self, exc_type, exc, traceback):
        return False


async def test_worker_completes_a_registered_handler():
    event = Event(
        UUID("00000000-0000-0000-0000-000000000002"),
        "sync_order",
        ORDER_ID,
        {},
    )
    repository = FakeRepository(event)
    calls = []
    worker = OrderChatOutboxWorker(
        repository=repository,
        order_lock=lambda order_id: FakeLock(),
        handlers={"sync_order": lambda item: calls.append(item.order_id)},
        max_attempts=8,
        base_delay_seconds=5,
    )

    assert await worker.run_once() is True

    assert calls == [ORDER_ID]
    assert repository.completed == [event.id]
    assert repository.retried == []


async def test_worker_retries_failure_without_exposing_payload():
    event = Event(
        UUID("00000000-0000-0000-0000-000000000002"),
        "sync_order",
        ORDER_ID,
        {"secret": "hidden"},
    )
    repository = FakeRepository(event)

    async def fail(item):
        raise RuntimeError("temporary")

    worker = OrderChatOutboxWorker(
        repository=repository,
        order_lock=lambda order_id: FakeLock(),
        handlers={"sync_order": fail},
        max_attempts=8,
        base_delay_seconds=5,
    )

    await worker.run_once()

    assert repository.retried == [(event.id, "RuntimeError", 8, 5)]


async def test_lock_contention_releases_claim_without_business_attempt():
    event = Event(
        UUID("00000000-0000-0000-0000-000000000002"),
        "sync_order",
        ORDER_ID,
        {},
    )
    repository = FakeRepository(event)
    worker = OrderChatOutboxWorker(
        repository=repository,
        order_lock=lambda order_id: FakeLock(acquired=False),
        handlers={"sync_order": lambda item: None},
        max_attempts=8,
        base_delay_seconds=5,
    )

    await worker.run_once()

    assert repository.released == [(event.id, 1)]
    assert repository.completed == []
