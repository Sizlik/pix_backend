import asyncio
from contextlib import asynccontextmanager

from manager.chat_realtime import RedisChatRealtime


class NotificationCountLockUnavailable(RuntimeError):
    pass


class NotificationRealtime(RedisChatRealtime):
    channel_prefix = "notifications:user:"

    @asynccontextmanager
    async def count_lock(self, user_id):
        lock = self._redis.lock(
            f"notifications:count-lock:{user_id}",
            timeout=30,
            blocking_timeout=35,
        )
        try:
            acquired = await lock.acquire()
        except Exception as error:
            raise NotificationCountLockUnavailable from error
        if not acquired:
            raise NotificationCountLockUnavailable
        try:
            async with asyncio.timeout(20):
                yield
        finally:
            try:
                await lock.release()
            except Exception:
                pass

    async def next_count_version(self, user_id) -> int:
        return await self._redis.incr(f"notifications:count-version:{user_id}")
