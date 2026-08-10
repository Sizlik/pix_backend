from functools import lru_cache

from db.redis import redis
from manager.chat import ChatManager, ChatRoomManager, ChatRoomRepository, MessageManager, MessageRepository
from manager.chat_realtime import LocalChatHub, RedisChatRealtime


@lru_cache
def get_chat_realtime():
    return RedisChatRealtime(redis, LocalChatHub())


def get_chat_manager():
    return ChatManager(get_message_manager(), get_chat_realtime())


def get_chat_room_manager():
    return ChatRoomManager(ChatRoomRepository())


def get_message_manager():
    return MessageManager(MessageRepository())
