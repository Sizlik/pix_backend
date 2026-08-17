import asyncio
import logging

import pytest

from manager.telegram_notifications import BestEffortGroupNotifier


class SuccessfulSender:
    def __init__(self):
        self.messages = []

    async def send_group_message(self, text):
        self.messages.append(text)


class BlockingSender:
    async def send_group_message(self, text):
        await asyncio.Event().wait()


class FailedSender:
    async def send_group_message(self, text):
        raise RuntimeError("network unavailable")


@pytest.mark.asyncio
async def test_best_effort_notifier_reports_success():
    sender = SuccessfulSender()
    notifier = BestEffortGroupNotifier(sender, timeout_seconds=0.1)

    assert await notifier.send_group_message("safe text") is True
    assert sender.messages == ["safe text"]


@pytest.mark.asyncio
async def test_best_effort_notifier_bounds_timeout_without_logging_message(caplog):
    caplog.set_level(logging.WARNING)
    notifier = BestEffortGroupNotifier(BlockingSender(), timeout_seconds=0.001)

    assert await notifier.send_group_message("secret message body") is False
    assert "secret message body" not in caplog.text
    assert "timed out" in caplog.text


@pytest.mark.asyncio
async def test_best_effort_notifier_swallows_transport_failure(caplog):
    caplog.set_level(logging.WARNING)
    notifier = BestEffortGroupNotifier(FailedSender(), timeout_seconds=0.1)

    assert await notifier.send_group_message("not logged") is False
    assert "not logged" not in caplog.text
    assert "failed" in caplog.text
