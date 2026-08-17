import asyncio
import logging
from typing import Protocol


class GroupMessageSender(Protocol):
    async def send_group_message(self, text: str) -> None: ...


class BestEffortGroupNotifier:
    def __init__(
        self,
        sender: GroupMessageSender,
        timeout_seconds: float,
        logger: logging.Logger | None = None,
    ) -> None:
        self._sender = sender
        self._timeout_seconds = timeout_seconds
        self._logger = logger or logging.getLogger(__name__)

    async def send_group_message(self, text: str) -> bool:
        try:
            await asyncio.wait_for(
                self._sender.send_group_message(text),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            self._logger.warning("Telegram group notification timed out")
            return False
        except Exception:
            self._logger.warning(
                "Telegram group notification failed",
                exc_info=True,
            )
            return False
        return True
