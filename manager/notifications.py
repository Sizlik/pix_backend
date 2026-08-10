from uuid import UUID

from db.schemas.notifications import NotificationCountEvent, NotificationCreate


class NotificationManager:
    def __init__(self, repo, realtime=None):
        self._repo = repo
        self._realtime = realtime

    async def create_notification(self, notification_data: NotificationCreate):
        notification_id = await self._repo.create(**notification_data.model_dump())
        await self.notify_count_changed(UUID(str(notification_data.user_id)))
        return notification_id

    async def get_notifications_by_user(self, user):
        return await self._repo.list_for_user(user.id)

    async def unread_count(self, user_id) -> int:
        return await self._repo.count_unread(user_id)

    async def _publish_value(self, user_id, count: int) -> None:
        if self._realtime is None:
            return
        try:
            payload = NotificationCountEvent(unread_count=count).model_dump()
            await self._realtime.publish(str(user_id), payload)
        except Exception:
            return

    async def notify_count_changed(self, user_id) -> None:
        try:
            count = await self.unread_count(user_id)
        except Exception:
            return
        await self._publish_value(user_id, count)

    async def read_notification(self, user_id, notification_id) -> int:
        await self._repo.mark_read(notification_id, user_id)
        count = await self.unread_count(user_id)
        await self._publish_value(user_id, count)
        return count

    async def read_all_notifications(self, user_id) -> int:
        await self._repo.mark_all_read(user_id)
        count = await self.unread_count(user_id)
        await self._publish_value(user_id, count)
        return count
