import redis.asyncio
from fastapi_cache.backends.redis import RedisBackend
from fastapi_users.authentication import RedisStrategy

from config import get_settings

settings = get_settings()
redis = redis.asyncio.from_url(settings.redis_url, decode_responses=True)


def get_redis_strategy() -> RedisStrategy:
    return RedisStrategy(redis, lifetime_seconds=settings.token_lifetime)


def get_redis_backend() -> RedisBackend:
    return RedisBackend(redis)
