import json
from collections.abc import Awaitable, Callable
from uuid import UUID

from errors import (
    IdempotencyKeyReused,
    OrderCreationIdempotencyUnavailable,
    OrderCreationInProgress,
)

RESULT_TTL_SECONDS = 86_400
LOCK_TIMEOUT_SECONDS = 300
LOCK_BLOCKING_TIMEOUT_SECONDS = 35


class RedisOrderCreationIdempotency:
    def __init__(
        self,
        redis_client,
        *,
        result_ttl_seconds=RESULT_TTL_SECONDS,
        lock_timeout_seconds=LOCK_TIMEOUT_SECONDS,
        blocking_timeout_seconds=LOCK_BLOCKING_TIMEOUT_SECONDS,
    ):
        self._redis = redis_client
        self._result_ttl = result_ttl_seconds
        self._lock_timeout = lock_timeout_seconds
        self._blocking_timeout = blocking_timeout_seconds

    @staticmethod
    def _base_key(user_id: UUID, key: UUID) -> str:
        return f"orders:create:idempotency:{user_id}:{key}"

    async def _read(self, record_key: str):
        try:
            raw = await self._redis.get(record_key)
            return json.loads(raw) if raw is not None else None
        except Exception as error:
            raise OrderCreationIdempotencyUnavailable from error

    async def _write(self, record_key: str, record: dict) -> None:
        try:
            await self._redis.set(
                record_key,
                json.dumps(record, separators=(",", ":")),
                ex=self._result_ttl,
            )
        except Exception as error:
            raise OrderCreationIdempotencyUnavailable from error

    @staticmethod
    def _resolve(record, fingerprint):
        if record is None:
            return None
        if record["fingerprint"] != fingerprint:
            raise IdempotencyKeyReused
        if record["state"] == "completed":
            return record["result"]
        return None

    async def run(
        self,
        user_id: UUID,
        key: UUID,
        fingerprint: str,
        operation: Callable[[], Awaitable[dict]],
    ) -> tuple[dict, bool]:
        record_key = self._base_key(user_id, key)
        cached = self._resolve(await self._read(record_key), fingerprint)
        if cached is not None:
            return cached, False

        try:
            lock = self._redis.lock(
                f"{record_key}:lock",
                timeout=self._lock_timeout,
                blocking_timeout=self._blocking_timeout,
            )
            acquired = await lock.acquire()
        except Exception as error:
            raise OrderCreationIdempotencyUnavailable from error
        if not acquired:
            cached = self._resolve(await self._read(record_key), fingerprint)
            if cached is not None:
                return cached, False
            raise OrderCreationInProgress

        try:
            record = await self._read(record_key)
            cached = self._resolve(record, fingerprint)
            if cached is not None:
                return cached, False
            if record is None:
                await self._write(
                    record_key,
                    {"state": "processing", "fingerprint": fingerprint},
                )
            result = await operation()
            await self._write(
                record_key,
                {
                    "state": "completed",
                    "fingerprint": fingerprint,
                    "result": result,
                },
            )
            return result, True
        finally:
            try:
                await lock.release()
            except Exception:
                pass
