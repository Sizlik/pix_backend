from functools import lru_cache

from db.notification_repository import NotificationRepository
from db.redis import redis
from manager.chat_realtime import LocalChatHub
from manager.notification_realtime import NotificationRealtime
from manager.notifications import NotificationManager


@lru_cache
def get_notification_realtime():
    return NotificationRealtime(redis, LocalChatHub())


def build_notification_manager():
    return NotificationManager(
        NotificationRepository(),
        get_notification_realtime(),
    )


async def get_notification_manager():
    yield build_notification_manager()
