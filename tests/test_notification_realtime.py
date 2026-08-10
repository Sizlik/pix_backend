import json

from manager.chat_realtime import LocalChatHub
from manager.notification_realtime import NotificationRealtime


class FakeRedis:
    def __init__(self):
        self.published = []

    async def publish(self, channel, payload):
        self.published.append((channel, payload))


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
