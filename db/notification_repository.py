from sqlalchemy import func, insert, select, update

from db.models.notifications import Notifications
from db.postgres import async_session_maker


class NotificationRepository:
    def __init__(self, session_factory=async_session_maker):
        self._session_factory = session_factory

    async def create(self, **values):
        async with self._session_factory() as session:
            statement = (
                insert(Notifications).values(**values).returning(Notifications.id)
            )
            result = await session.execute(statement)
            await session.commit()
            return result.scalar_one()

    async def list_for_user(self, user_id):
        async with self._session_factory() as session:
            statement = (
                select(Notifications)
                .where(Notifications.user_id == user_id)
                .order_by(Notifications.time_created.desc())
            )
            result = await session.execute(statement)
            return list(result.scalars())

    async def count_unread(self, user_id) -> int:
        async with self._session_factory() as session:
            statement = (
                select(func.count())
                .select_from(Notifications)
                .where(
                    Notifications.user_id == user_id,
                    Notifications.is_readed.is_(False),
                )
            )
            result = await session.execute(statement)
            return result.scalar_one()

    async def mark_read(self, notification_id, user_id) -> bool:
        async with self._session_factory() as session:
            statement = (
                update(Notifications)
                .where(
                    Notifications.id == notification_id,
                    Notifications.user_id == user_id,
                    Notifications.is_readed.is_(False),
                )
                .values(is_readed=True)
                .returning(Notifications.id)
            )
            result = await session.execute(statement)
            changed = result.scalar_one_or_none() is not None
            await session.commit()
            return changed

    async def mark_all_read(self, user_id) -> int:
        async with self._session_factory() as session:
            statement = (
                update(Notifications)
                .where(
                    Notifications.user_id == user_id,
                    Notifications.is_readed.is_(False),
                )
                .values(is_readed=True)
                .returning(Notifications.id)
            )
            result = await session.execute(statement)
            changed = len(result.scalars().all())
            await session.commit()
            return changed
