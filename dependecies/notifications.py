from db.notification_repository import NotificationRepository
from manager.notifications import NotificationManager


async def get_notification_manager():
    yield NotificationManager(NotificationRepository())
