from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from db.schemas.notifications import NotificationTypes
from routes.integration.webhooks import state_changed_webhook


ORDER_ID = UUID("00000000-0000-0000-0000-000000000101")
USER_ID = UUID("00000000-0000-0000-0000-000000000102")


class Orders:
    async def get_order_by_id(self, order_id):
        assert order_id == ORDER_ID
        return {
            "id": str(order_id),
            "agent": {"meta": {"href": "/counterparty/client-id"}},
            "state": {"name": "Готов к выдаче"},
        }


class Users:
    def __init__(self, user=SimpleNamespace(id=USER_ID)):
        self.user = user

    async def get_by_moysklad(self, counterparty_id):
        assert counterparty_id == "client-id"
        return self.user


class Notifications:
    def __init__(self):
        self.created = []

    async def create_notification(self, data):
        self.created.append(data)


@pytest.mark.asyncio
async def test_order_wait_creates_only_the_website_notification():
    notifications = Notifications()

    await state_changed_webhook(
        id=ORDER_ID,
        moysklad_order_manager=Orders(),
        notification_manager=notifications,
        user_db=Users(),
    )

    assert len(notifications.created) == 1
    assert notifications.created[0].type == NotificationTypes.ORDER_UPDATED
    assert notifications.created[0].user_id == str(USER_ID)
    assert notifications.created[0].object_id == str(ORDER_ID)


@pytest.mark.asyncio
async def test_order_wait_ignores_an_unmapped_counterparty():
    notifications = Notifications()

    result = await state_changed_webhook(
        id=ORDER_ID,
        moysklad_order_manager=Orders(),
        notification_manager=notifications,
        user_db=Users(user=None),
    )

    assert result is None
    assert notifications.created == []


def test_status_paths_do_not_import_or_call_telegram():
    for path in (
        Path("utils/celery_worker.py"),
        Path("routes/integration/webhooks.py"),
    ):
        source = path.read_text(encoding="utf-8").lower()
        assert "bot.sender" not in source
        assert "telegram" not in source
