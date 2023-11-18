import os

import redis.asyncio
from fastapi_users.authentication import RedisStrategy

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
TOKEN_LIFETIME = os.getenv("TOKEN_LIFETIME", 3600)

redis = redis.asyncio.from_url(REDIS_URL, decode_responses=True)


def get_redis_strategy() -> RedisStrategy:
    return RedisStrategy(redis, lifetime_seconds=TOKEN_LIFETIME)

