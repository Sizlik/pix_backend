import json

from manager.chat_realtime import LocalChatHub, RedisChatRealtime


class FakeSocket:
    def __init__(self):
        self.accepted = False
        self.messages = []
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, value):
        if self.closed:
            raise RuntimeError("closed")
        self.messages.append(value)


async def test_hub_keeps_multiple_connections_and_removes_only_dead_socket():
    hub = LocalChatHub()
    first = FakeSocket()
    second = FakeSocket()

    await hub.connect("room", first)
    await hub.connect("room", second)
    first.closed = True
    await hub.broadcast("room", {"id": "message"})

    assert second.messages == [{"id": "message"}]
    assert first not in hub.connections["room"]
    assert second in hub.connections["room"]


async def test_register_adds_an_already_accepted_socket_without_accepting_again():
    hub = LocalChatHub()
    socket = FakeSocket()

    await hub.register("room", socket)

    assert socket.accepted is False
    assert socket in hub.connections["room"]

    bridge = RedisChatRealtime(FakeRedis(), hub)
    second = FakeSocket()
    await bridge.register("room", second)
    assert second.accepted is False
    assert second in hub.connections["room"]


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


async def test_redis_bridge_serializes_one_room_event():
    redis = FakeRedis()
    hub = RecordingHub()
    bridge = RedisChatRealtime(redis, hub)

    await bridge.publish("room", {"id": "message"})
    channel, payload = redis.published[-1]
    await bridge.dispatch_for_test(channel, payload)

    assert channel == "order-chat:room:room"
    assert json.loads(payload) == {"id": "message"}
    assert hub.broadcasts == [("room", {"id": "message"})]
