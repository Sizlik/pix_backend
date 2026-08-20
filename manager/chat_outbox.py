import asyncio
import inspect
from collections.abc import Callable


class OrderChatOutboxWorker:
    def __init__(
        self,
        *,
        repository,
        order_lock,
        handlers: dict[str, Callable],
        max_attempts: int,
        base_delay_seconds: int,
        realtime=None,
    ):
        self._repository = repository
        self._order_lock = order_lock
        self._handlers = handlers
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._realtime = realtime
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def handler_names(self) -> frozenset[str]:
        return frozenset(self._handlers)

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
                status = await self._repository.retry_event(
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
                status = await self._repository.retry_event(
                    event,
                    error,
                    self._max_attempts,
                    self._base_delay_seconds,
                )
                if status == "dead":
                    await self._publish_delivery(event, "failed")
            else:
                await self._repository.complete_event(event.id)
                await self._publish_delivery(event, "synced")
        return True

    async def _publish_delivery(self, event, state: str) -> None:
        if self._realtime is None or event.event_type != "sync_order" or not event.payload.get("message_id"):
            return
        try:
            await self._realtime.publish(
                str(event.order_id),
                {
                    "type": "order_chat_delivery",
                    "message_id": event.payload["message_id"],
                    "delivery_state": state,
                },
            )
        except Exception:
            pass

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
