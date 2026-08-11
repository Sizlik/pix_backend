from contextlib import asynccontextmanager
from uuid import UUID

from db.schemas.notifications import NotificationCountEvent, NotificationCreate
from manager.notification_realtime import NotificationCountLockUnavailable


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

    @asynccontextmanager
    async def _count_lock(self, user_id):
        lock_factory = getattr(self._realtime, "count_lock", None)
        if lock_factory is None:
            yield
            return
        async with lock_factory(str(user_id)):
            yield

    async def unread_count(self, user_id) -> int:
        try:
            async with self._count_lock(user_id):
                return await self._repo.count_unread(user_id)
        except NotificationCountLockUnavailable:
            return await self._repo.count_unread(user_id)

    async def _publish_value(self, user_id, count: int) -> None:
        if self._realtime is None:
            return
        try:
            version_factory = getattr(
                self._realtime,
                "next_count_version",
                None,
            )
            version = (
                await version_factory(str(user_id))
                if version_factory is not None
                else None
            )
            payload = NotificationCountEvent(
                unread_count=count,
                version=version,
            ).model_dump(exclude_none=True)
            await self._realtime.publish(str(user_id), payload)
        except Exception:
            return

    async def notify_count_changed(self, user_id) -> None:
        try:
            await self._count_and_publish(user_id)
        except Exception:
            return

    async def _count_and_publish(self, user_id) -> int:
        try:
            async with self._count_lock(user_id):
                count = await self._repo.count_unread(user_id)
                await self._publish_value(user_id, count)
                return count
        except NotificationCountLockUnavailable:
            return await self._repo.count_unread(user_id)

    async def read_notification(self, user_id, notification_id) -> int:
        await self._repo.mark_read(notification_id, user_id)
        return await self._count_and_publish(user_id)

    async def read_all_notifications(self, user_id) -> int:
        await self._repo.mark_all_read(user_id)
        return await self._count_and_publish(user_id)
