from uuid import UUID

from sqlalchemy import and_

from bot.sender import telegram_sender
from db.models.chat import ChatRoom, Message
from db.models.users import User
from db.repository import AbstractRepository, SQLAlchemyRepository


class ChatRoomRepository(SQLAlchemyRepository):
    model = ChatRoom


class MessageRepository(SQLAlchemyRepository):
    model = Message


class ChatRoomManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_order_chat(self, user, order_id):
        chat = await self.get_order_chat(user, order_id)
        if not chat:
            return await self.__repo.create(client_id=user.id, order_id=order_id)
        return chat.id

    async def get_all(self):
        return await self.__repo.read_all()

    async def get_order_chat(self, user: User, order_id):
        return await self.__repo.search_one(and_(ChatRoom.order_id == order_id, ChatRoom.client_id == user.id))


class MessageManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_one(self, data):
        return await self.__repo.create(**data)

    async def get_messages_by_chat_id(self, chat_id: UUID):
        return await self.__repo.read_all(Message.to_chat_room_id == chat_id, Message.time_created.desc())

    async def get_messages_by_user_id(self, user_id: UUID):
        return await self.__repo.read_all(Message.to_chat_room_id == user_id, Message.time_created.desc())

    async def get_message_by_id(self, id):
        return await self.__repo.read_one(id)


class ChatManager:
    def __init__(self, message_manager: MessageManager, realtime):
        self.message_manager = message_manager
        self.realtime = realtime

    async def connect(self, room_id, websocket):
        await self.realtime.connect(str(room_id), websocket)

    async def disconnect(self, room_id, websocket):
        await self.realtime.disconnect(str(room_id), websocket)

    async def send_message_from_client(self, data, room_id, user):
        message = await self.message_manager.create_one(data)
        data["id"] = str(message)
        data["first_name"] = user.first_name
        if user.email != "bot@pixlogistic.com":
            await telegram_sender.send_chat_message(data["message"], user, data["to_chat_room_id"])
        await self.realtime.publish(str(room_id), data)
        return message
