from contextlib import asynccontextmanager

from manager.chat_realtime import RedisChatRealtime


class NotificationRealtime(RedisChatRealtime):
    channel_prefix = "notifications:user:"

    @asynccontextmanager
    async def count_lock(self, user_id):
        lock = self._redis.lock(
            f"notifications:count-lock:{user_id}",
            timeout=10,
            blocking_timeout=5,
        )
        acquired = False
        try:
            acquired = await lock.acquire()
        except Exception:
            pass
        try:
            yield
        finally:
            if acquired:
                try:
                    await lock.release()
                except Exception:
                    pass
