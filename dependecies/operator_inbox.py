from functools import lru_cache

from db.redis import redis
from manager.chat_realtime import LocalChatHub
from manager.operator_inbox_realtime import OperatorInboxRealtime


@lru_cache
def get_operator_inbox_realtime():
    return OperatorInboxRealtime(redis, LocalChatHub())
