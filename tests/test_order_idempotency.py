import asyncio
import json
from uuid import UUID

import pytest
from redis.exceptions import LockNotOwnedError

from errors import (
    IdempotencyKeyReused,
    OrderCreationIdempotencyUnavailable,
    OrderCreationInProgress,
)
from manager.order_idempotency import RedisOrderCreationIdempotency

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
KEY = UUID("00000000-0000-0000-0000-000000000020")


class FakeLock:
    def __init__(
        self,
        lock,
        options,
        force_unavailable=False,
        lose_before_reacquire=False,
    ):
        self._lock = lock
        self.options = options
        self.force_unavailable = force_unavailable
        self.lose_before_reacquire = lose_before_reacquire

    async def acquire(self):
        if self.force_unavailable:
            return False
        try:
            await asyncio.wait_for(
                self._lock.acquire(),
                timeout=self.options["blocking_timeout"],
            )
        except TimeoutError:
            return False
        return True

    async def release(self):
        if self._lock.locked():
            self._lock.release()

    async def reacquire(self):
        if self.lose_before_reacquire:
            raise LockNotOwnedError("lease expired")
        return True


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.locks = {}
        self.lock_calls = []
        self.get_error = None
        self.set_error = None
        self.set_calls = 0
        self.fail_set_call = None
        self.force_lock_unavailable = False
        self.lock_error = None
        self.lose_lock_before_reacquire = False

    async def get(self, key):
        if self.get_error:
            raise self.get_error
        return self.values.get(key)

    async def set(self, key, value, ex):
        self.set_calls += 1
        if self.set_error or self.fail_set_call == self.set_calls:
            raise self.set_error or RuntimeError("redis unavailable")
        self.values[key] = value
        self.values[f"{key}:ttl"] = ex
        return True

    def lock(self, name, **options):
        if self.lock_error:
            raise self.lock_error
        self.lock_calls.append((name, options))
        shared = self.locks.setdefault(name, asyncio.Lock())
        return FakeLock(
            shared,
            options,
            force_unavailable=self.force_lock_unavailable,
            lose_before_reacquire=self.lose_lock_before_reacquire,
        )


@pytest.mark.asyncio
async def test_completed_attempt_replays_result_without_running_operation_twice():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        return {"id": "order"}

    first = await coordinator.run(USER_ID, KEY, "fingerprint", operation)
    retry = await coordinator.run(USER_ID, KEY, "fingerprint", operation)

    assert first == ({"id": "order"}, True)
    assert retry == ({"id": "order"}, False)
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_attempts_run_operation_once_and_both_get_result():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(
        redis,
        blocking_timeout_seconds=1,
    )
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        return {"id": "order"}

    first = asyncio.create_task(
        coordinator.run(USER_ID, KEY, "fingerprint", operation)
    )
    await started.wait()
    second = asyncio.create_task(
        coordinator.run(USER_ID, KEY, "fingerprint", operation)
    )
    finish.set()

    assert await asyncio.gather(first, second) == [
        ({"id": "order"}, True),
        ({"id": "order"}, False),
    ]
    assert calls == 1


async def _return_order():
    return {"id": "order"}


@pytest.mark.asyncio
async def test_reused_key_with_another_fingerprint_conflicts():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)
    await coordinator.run(USER_ID, KEY, "first", _return_order)

    with pytest.raises(IdempotencyKeyReused):
        await coordinator.run(USER_ID, KEY, "second", _return_order)


@pytest.mark.asyncio
async def test_user_and_key_scope_allow_intentional_separate_orders():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        return {"id": f"order-{calls}"}

    other_user = UUID("00000000-0000-0000-0000-000000000002")
    other_key = UUID("00000000-0000-0000-0000-000000000021")

    assert await coordinator.run(
        USER_ID, KEY, "same-payload", operation
    ) == ({"id": "order-1"}, True)
    assert await coordinator.run(
        USER_ID, other_key, "same-payload", operation
    ) == ({"id": "order-2"}, True)
    assert await coordinator.run(
        other_user, KEY, "same-payload", operation
    ) == ({"id": "order-3"}, True)


@pytest.mark.asyncio
async def test_failed_operation_keeps_fingerprint_and_allows_same_retry():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)

    async def fail():
        raise RuntimeError("MoySklad unavailable")

    with pytest.raises(RuntimeError):
        await coordinator.run(USER_ID, KEY, "fingerprint", fail)

    assert await coordinator.run(
        USER_ID, KEY, "fingerprint", _return_order
    ) == ({"id": "order"}, True)
    with pytest.raises(IdempotencyKeyReused):
        await coordinator.run(USER_ID, KEY, "changed", _return_order)


@pytest.mark.asyncio
async def test_lock_timeout_reports_in_progress_with_exact_options():
    redis = FakeRedis()
    redis.force_lock_unavailable = True
    coordinator = RedisOrderCreationIdempotency(redis)

    with pytest.raises(OrderCreationInProgress):
        await coordinator.run(USER_ID, KEY, "fingerprint", _return_order)

    _, options = redis.lock_calls[-1]
    assert options == {"timeout": 300, "blocking_timeout": 35}


@pytest.mark.asyncio
async def test_lost_lease_cannot_complete_attempt_or_claim_external_effects():
    redis = FakeRedis()
    redis.lose_lock_before_reacquire = True
    coordinator = RedisOrderCreationIdempotency(redis)

    with pytest.raises(OrderCreationInProgress):
        await coordinator.run(USER_ID, KEY, "fingerprint", _return_order)

    record_key = coordinator._base_key(USER_ID, KEY)
    assert json.loads(redis.values[record_key]) == {
        "state": "processing",
        "fingerprint": "fingerprint",
    }


@pytest.mark.asyncio
async def test_redis_read_failure_never_runs_external_operation():
    redis = FakeRedis()
    redis.get_error = RuntimeError("redis unavailable")
    coordinator = RedisOrderCreationIdempotency(redis)
    called = False

    async def operation():
        nonlocal called
        called = True
        return {"id": "order"}

    with pytest.raises(OrderCreationIdempotencyUnavailable):
        await coordinator.run(USER_ID, KEY, "fingerprint", operation)
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record",
    [
        {},
        [],
        {"state": "unknown", "fingerprint": "fingerprint"},
        {"state": "completed", "fingerprint": "fingerprint"},
    ],
)
async def test_malformed_redis_record_uses_domain_error_without_external_call(
    record,
):
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)
    record_key = coordinator._base_key(USER_ID, KEY)
    redis.values[record_key] = json.dumps(record)
    called = False

    async def operation():
        nonlocal called
        called = True
        return {"id": "order"}

    with pytest.raises(OrderCreationIdempotencyUnavailable):
        await coordinator.run(USER_ID, KEY, "fingerprint", operation)
    assert called is False


@pytest.mark.asyncio
async def test_redis_lock_creation_failure_uses_domain_error():
    redis = FakeRedis()
    redis.lock_error = RuntimeError("redis unavailable")
    coordinator = RedisOrderCreationIdempotency(redis)

    with pytest.raises(OrderCreationIdempotencyUnavailable):
        await coordinator.run(USER_ID, KEY, "fingerprint", _return_order)


@pytest.mark.asyncio
async def test_initial_record_write_failure_never_runs_external_operation():
    redis = FakeRedis()
    redis.set_error = RuntimeError("redis unavailable")
    coordinator = RedisOrderCreationIdempotency(redis)
    called = False

    async def operation():
        nonlocal called
        called = True
        return {"id": "order"}

    with pytest.raises(OrderCreationIdempotencyUnavailable):
        await coordinator.run(USER_ID, KEY, "fingerprint", operation)
    assert called is False


@pytest.mark.asyncio
async def test_completion_write_failure_leaves_attempt_retryable():
    redis = FakeRedis()
    redis.fail_set_call = 2
    coordinator = RedisOrderCreationIdempotency(redis)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        return {"id": "order"}

    with pytest.raises(OrderCreationIdempotencyUnavailable):
        await coordinator.run(USER_ID, KEY, "fingerprint", operation)

    record_key = coordinator._base_key(USER_ID, KEY)
    assert json.loads(redis.values[record_key])["state"] == "processing"
    redis.fail_set_call = None
    assert await coordinator.run(
        USER_ID, KEY, "fingerprint", operation
    ) == ({"id": "order"}, True)
    assert calls == 2


@pytest.mark.asyncio
async def test_completed_record_uses_24_hour_ttl():
    redis = FakeRedis()
    coordinator = RedisOrderCreationIdempotency(redis)
    await coordinator.run(USER_ID, KEY, "fingerprint", _return_order)

    record_key = coordinator._base_key(USER_ID, KEY)
    assert redis.values[f"{record_key}:ttl"] == 86_400
    assert json.loads(redis.values[record_key])["state"] == "completed"
