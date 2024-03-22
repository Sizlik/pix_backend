from manager.notifications import NotificationManager, NotificationRepository


async def get_notification_manager():
    yield NotificationManager(NotificationRepository())
