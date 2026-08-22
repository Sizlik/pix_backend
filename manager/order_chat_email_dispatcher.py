import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from db.order_chat_email_repository import (
    ClaimedOrderChatEmail,
    OrderChatEmailOutboxRepository,
)
from manager.order_chat_email import (
    OrderChatEmailSender,
    OrderChatEmailSendError,
    render_order_chat_email,
)

RETRY_DELAYS_SECONDS = (60, 300, 900, 3600, 21600)
MAX_ATTEMPTS = 10
CLAIM_LIMIT = 20
LEASE_DURATION = timedelta(minutes=5)


def retry_delay_seconds(attempt: int) -> int:
    index = min(max(attempt, 1) - 1, len(RETRY_DELAYS_SECONDS) - 1)
    return RETRY_DELAYS_SECONDS[index]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OrderChatEmailDispatcher:
    def __init__(
        self,
        *,
        repository: OrderChatEmailOutboxRepository,
        sender: OrderChatEmailSender,
        public_site_url: str,
        clock: Callable[[], datetime] = _utcnow,
        poll_interval_seconds: float = 5,
    ):
        self._repository = repository
        self._sender = sender
        self._public_site_url = public_site_url
        self._clock = clock
        self._poll_interval_seconds = poll_interval_seconds
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping = False
        self._task = asyncio.create_task(
            self._run(),
            name="order-chat-email-dispatcher",
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping = True
        self._wakeup.set()
        await self._task
        self._task = None

    def wakeup(self) -> None:
        self._wakeup.set()

    async def process_once(self) -> int:
        now = self._clock()
        jobs = await self._repository.claim_due(
            now=now,
            limit=CLAIM_LIMIT,
            lease_before=now - LEASE_DURATION,
        )
        for job in jobs:
            await self._deliver(job, now)
        return len(jobs)

    async def _deliver(
        self,
        job: ClaimedOrderChatEmail,
        now: datetime,
    ) -> None:
        envelope = render_order_chat_email(
            job.content,
            self._public_site_url,
        )
        try:
            await asyncio.to_thread(self._sender.send, envelope)
        except OrderChatEmailSendError as error:
            await self._mark_failed(job, now, error.category)
        except Exception:
            await self._mark_failed(job, now, "unexpected")
        else:
            await self._repository.mark_sent(job.outbox_id, sent_at=now)

    async def _mark_failed(
        self,
        job: ClaimedOrderChatEmail,
        now: datetime,
        category: str,
    ) -> None:
        dead = job.attempts >= MAX_ATTEMPTS
        available_at = (
            None
            if dead
            else now + timedelta(seconds=retry_delay_seconds(job.attempts))
        )
        await self._repository.mark_failed(
            job.outbox_id,
            category=category,
            available_at=available_at,
            dead=dead,
        )

    async def _run(self) -> None:
        while not self._stopping:
            processed = await self.process_once()
            if self._stopping or processed:
                continue
            try:
                await asyncio.wait_for(
                    self._wakeup.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                pass
            finally:
                self._wakeup.clear()
