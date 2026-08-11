import json

import pytest

from manager.chat_realtime import LocalChatHub
from manager.notification_realtime import (
    NotificationCountLockUnavailable,
    NotificationRealtime,
)


class FakeRedis:
    def __init__(self, lock_acquired=True):
        self.published = []
        self.locks = []
        self.lock_acquired = lock_acquired
        self.values = {}

    async def publish(self, channel, payload):
        self.published.append((channel, payload))

    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def lock(self, name, **options):
        lock = FakeLock(name, options, self.lock_acquired)
        self.locks.append(lock)
        return lock


class FakeLock:
    def __init__(self, name, options, should_acquire):
        self.name = name
        self.options = options
        self.should_acquire = should_acquire
        self.acquired = False
        self.released = False

    async def acquire(self):
        self.acquired = self.should_acquire
        return self.should_acquire

    async def release(self):
        self.released = True


class RecordingHub:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, room, message):
        self.broadcasts.append((room, message))


class FakeSocket:
    def __init__(self, closed=False):
        self.accepted = False
        self.closed = closed
        self.messages = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        if self.closed:
            raise RuntimeError("closed")
        self.messages.append(message)


async def test_notification_bridge_uses_isolated_user_channel():
    redis = FakeRedis()
    hub = RecordingHub()
    bridge = NotificationRealtime(redis, hub)

    event = {"type": "notification_count", "unread_count": 5}
    await bridge.publish("user-1", event)
    channel, payload = redis.published[-1]
    await bridge.dispatch_for_test(channel, payload)

    assert channel == "notifications:user:user-1"
    assert json.loads(payload) == event
    assert hub.broadcasts == [("user-1", event)]


async def test_notification_hub_updates_all_live_tabs_and_drops_dead_one():
    hub = LocalChatHub()
    first = FakeSocket()
    second = FakeSocket()
    dead = FakeSocket(closed=True)
    for socket in (first, second, dead):
        await hub.connect("user-1", socket)

    event = {"type": "notification_count", "unread_count": 2}
    await hub.broadcast("user-1", event)

    assert first.messages == [event]
    assert second.messages == [event]
    assert dead not in hub.connections["user-1"]


async def test_notification_count_lock_is_scoped_to_one_user():
    redis = FakeRedis()
    bridge = NotificationRealtime(redis, RecordingHub())

    async with bridge.count_lock("user-1"):
        assert redis.locks[-1].acquired is True

    lock = redis.locks[-1]
    assert lock.name == "notifications:count-lock:user-1"
    assert lock.options == {"timeout": 30, "blocking_timeout": 35}
    assert lock.released is True


async def test_notification_count_lock_never_enters_unlocked():
    redis = FakeRedis(lock_acquired=False)
    bridge = NotificationRealtime(redis, RecordingHub())
    entered = False

    with pytest.raises(NotificationCountLockUnavailable):
        async with bridge.count_lock("user-1"):
            entered = True

    assert entered is False


async def test_notification_versions_increase_per_user():
    redis = FakeRedis()
    bridge = NotificationRealtime(redis, RecordingHub())

    assert await bridge.next_count_version("user-1") == 1
    assert await bridge.next_count_version("user-1") == 2
    assert await bridge.next_count_version("user-2") == 1
