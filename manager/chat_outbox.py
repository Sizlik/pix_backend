import asyncio
import inspect
from collections.abc import Callable
from uuid import UUID


class OrderChatOutboxWorker:
    def __init__(
        self,
        *,
        repository,
        order_lock,
        handlers: dict[str, Callable],
        max_attempts: int,
        base_delay_seconds: int,
    ):
        self._repository = repository
        self._order_lock = order_lock
        self._handlers = handlers
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._repository.recover_stale_events()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="order-chat-outbox")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def run_once(self) -> bool:
        event = await self._repository.claim_due_event()
        if event is None:
            return False
        async with self._order_lock(event.order_id) as acquired:
            if not acquired:
                await self._repository.release_claim(event.id, delay_seconds=1)
                return True
            handler = self._handlers.get(event.event_type)
            if handler is None:
                await self._repository.retry_event(
                    event,
                    RuntimeError("Unknown event type"),
                    max_attempts=0,
                    base_seconds=self._base_delay_seconds,
                )
                return True
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as error:
                await self._repository.retry_event(
                    event,
                    error,
                    self._max_attempts,
                    self._base_delay_seconds,
                )
            else:
                await self._repository.complete_event(event.id)
        return True

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            handled = await self.run_once()
            if not handled:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=1)
                except TimeoutError:
                    pass
            else:
                await asyncio.sleep(0)


class OrderChatTelegramHandlers:
    def __init__(self, repository, sender):
        self._repository = repository
        self._sender = sender

    async def client_alert(self, event) -> None:
        message = await self._repository.get_message(UUID(event.payload["message_id"]))
        if message is None:
            return
        await self._sender.send_order_client_alert(
            order_id=str(event.order_id),
            order_name=str(event.payload.get("order_name", event.order_id)),
            client_name=str(event.payload.get("client_name", "Клиент")),
            client_number=int(event.payload.get("client_number", 0)),
            text=message.body,
            filenames=[attachment.original_filename for attachment in message.attachments],
        )
