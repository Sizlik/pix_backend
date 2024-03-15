import uuid

from sqlalchemy import Column, UUID, JSON, String, ForeignKey, select, DateTime, func, desc
from sqlalchemy.orm import column_property, relationship

from db.models.users import User
from db.postgres import Base


class Message(Base):
    __tablename__ = "message"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    message = Column(String, nullable=False)

    time_created = Column(DateTime(), server_default=func.now())
    time_updated = Column(DateTime(), onupdate=func.now())

    from_user_id = Column(ForeignKey("user.id"))
    to_chat_room_id = Column(UUID)

    first_name = column_property(
        select(User.first_name).where(User.id == from_user_id).limit(1).as_scalar()
    )


class ChatRoom(Base):
    __tablename__ = "chat_room"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    members = Column(JSON)
    client_id = Column(ForeignKey("user.id"))
    order_id = Column(UUID)

    last_message = column_property(
        select(Message.message).order_by(desc(Message.time_created)).limit(1).as_scalar()
    )


