from functools import lru_cache

from db.redis import redis
from manager.chat_realtime import LocalChatHub, RedisChatRealtime


@lru_cache
def get_chat_realtime():
    return RedisChatRealtime(redis, LocalChatHub())
