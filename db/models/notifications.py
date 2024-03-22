import uuid

from sqlalchemy import Column, UUID, ForeignKey, Boolean, String, func, DateTime

from db.postgres import Base


class Notifications(Base):
    __tablename__ = "notifications"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(ForeignKey("user.id"))
    is_readed = Column(Boolean, default=False)
    type = Column(String)
    object_id = Column(UUID)
    time_created = Column(DateTime(), server_default=func.now())




