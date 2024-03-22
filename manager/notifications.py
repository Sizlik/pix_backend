from sqlalchemy import and_

from db.models.notifications import Notifications
from db.repository import SQLAlchemyRepository, AbstractRepository
from db.schemas.notifications import NotificationCreate


class NotificationRepository(SQLAlchemyRepository):
    model = Notifications


class NotificationManager:

    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_notification(self, notification_data: NotificationCreate):
        return await self.__repo.create(**notification_data.model_dump())

    async def get_notifications_by_user(self, user):
        return await self.__repo.read_all(Notifications.user_id == user.id, Notifications.time_created.desc())

    async def read_notification(self, id):
        return await self.__repo.update(id, is_readed=True)

    async def get_unreaded_notifications_by_user(self, user):
        return await self.__repo.read_all(and_(Notifications.user_id == user.id, Notifications.is_readed == False))
