import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from config import OrderChatEmailSettings
from manager.order_chat_email import (
    OrderChatEmailContent,
    OrderChatEmailSendError,
)

try:
    import manager.order_chat_email_dispatcher as dispatcher_module
except ModuleNotFoundError:
    dispatcher_module = SimpleNamespace()


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
OUTBOX_ID = UUID("00000000-0000-0000-0000-000000000010")
ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")


def claimed_job(*, attempts=1):
    claimed_type = getattr(dispatcher_module, "ClaimedOrderChatEmail", None)
    if claimed_type is None:
        from db import order_chat_email_repository

        claimed_type = order_chat_email_repository.ClaimedOrderChatEmail
    return claimed_type(
        outbox_id=OUTBOX_ID,
        attempts=attempts,
        content=OrderChatEmailContent(
            recipient_email="recipient@example.com",
            recipient_kind="manager",
            order_id=ORDER_ID,
            order_name="12345",
            sender_label="Клиент",
            message="Проверка",
            attachment_count=0,
        ),
    )


class FakeRepository:
    def __init__(self, jobs):
        self.jobs = list(jobs)
        self.claims = []
        self.sent = []
        self.failed = []
        self.claimed_event = asyncio.Event()

    async def claim_due(self, **values):
        self.claims.append(values)
        self.claimed_event.set()
        jobs, self.jobs = self.jobs, []
        return jobs

    async def mark_sent(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    async def mark_failed(self, *args, **kwargs):
        self.failed.append((args, kwargs))


class RecordingSender:
    def __init__(self, error=None):
        self.error = error
        self.thread_ids = []
        self.envelopes = []

    def send(self, envelope):
        self.thread_ids.append(threading.get_ident())
        self.envelopes.append(envelope)
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize(
    ("attempt", "seconds"),
    [(1, 60), (2, 300), (3, 900), (4, 3600), (5, 21600), (9, 21600)],
)
def test_retry_delay_is_capped(attempt, seconds):
    assert dispatcher_module.retry_delay_seconds(attempt) == seconds


async def test_process_once_sends_off_event_loop_and_marks_success():
    repository = FakeRepository([claimed_job(attempts=1)])
    sender = RecordingSender()
    dispatcher = dispatcher_module.OrderChatEmailDispatcher(
        repository=repository,
        sender=sender,
        public_site_url="https://pixlogistic.com",
        clock=lambda: NOW,
    )
    event_loop_thread = threading.get_ident()

    processed = await dispatcher.process_once()

    assert processed == 1
    assert sender.thread_ids[0] != event_loop_thread
    assert sender.envelopes[0].recipient_email == "recipient@example.com"
    assert repository.sent == [((OUTBOX_ID,), {"sent_at": NOW})]
    assert repository.failed == []
    assert repository.claims[0]["lease_before"] == NOW - timedelta(minutes=5)
    assert repository.claims[0]["limit"] == 20


@pytest.mark.parametrize(
    ("attempts", "dead", "available_at"),
    [
        (1, False, NOW + timedelta(seconds=60)),
        (4, False, NOW + timedelta(hours=1)),
        (10, True, None),
    ],
)
async def test_process_once_retries_safe_sender_failure_or_marks_dead(
    attempts,
    dead,
    available_at,
):
    repository = FakeRepository([claimed_job(attempts=attempts)])
    sender = RecordingSender(OrderChatEmailSendError("provider_5xx"))
    dispatcher = dispatcher_module.OrderChatEmailDispatcher(
        repository=repository,
        sender=sender,
        public_site_url="https://pixlogistic.com",
        clock=lambda: NOW,
    )

    processed = await dispatcher.process_once()

    assert processed == 1
    assert repository.sent == []
    assert repository.failed == [
        (
            (OUTBOX_ID,),
            {
                "category": "provider_5xx",
                "available_at": available_at,
                "dead": dead,
            },
        )
    ]


async def test_start_and_stop_wake_the_poll_loop_without_claiming_after_stop():
    repository = FakeRepository([])
    dispatcher = dispatcher_module.OrderChatEmailDispatcher(
        repository=repository,
        sender=RecordingSender(),
        public_site_url="https://pixlogistic.com",
        clock=lambda: NOW,
        poll_interval_seconds=60,
    )

    await dispatcher.start()
    await asyncio.wait_for(repository.claimed_event.wait(), timeout=1)
    await dispatcher.stop()
    calls_after_stop = len(repository.claims)
    dispatcher.wakeup()
    await asyncio.sleep(0)

    assert len(repository.claims) == calls_after_stop


def test_dependency_builder_constructs_dispatcher_without_network_access():
    from dependecies.order_chat_email import build_order_chat_email_dispatcher

    dispatcher = build_order_chat_email_dispatcher(
        OrderChatEmailSettings(
            manager_email="manager@example.com",
            public_site_url="https://pixlogistic.com",
            smtp_bz_token="private-token",
        )
    )

    assert isinstance(dispatcher, dispatcher_module.OrderChatEmailDispatcher)
