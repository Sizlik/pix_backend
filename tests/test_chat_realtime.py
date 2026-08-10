import json
from types import SimpleNamespace
from uuid import UUID

from manager.chat_outbox import OrderChatOutboxWorker
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


class WorkerRepository:
    def __init__(self, event):
        self.event = event

    async def claim_due_event(self):
        event, self.event = self.event, None
        return event

    async def complete_event(self, event_id):
        return None


class Lock:
    async def __aenter__(self):
        return True

    async def __aexit__(self, *args):
        return False


class FakeRealtime:
    def __init__(self):
        self.events = []

    async def publish(self, room, message):
        self.events.append((room, message))


async def test_completed_order_sync_publishes_durable_delivery_state():
    order_id = UUID("00000000-0000-0000-0000-000000000001")
    message_id = UUID("00000000-0000-0000-0000-000000000002")
    event = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        event_type="sync_order",
        order_id=order_id,
        payload={"message_id": str(message_id)},
        attempts=1,
    )
    realtime = FakeRealtime()
    worker = OrderChatOutboxWorker(
        repository=WorkerRepository(event),
        order_lock=lambda _: Lock(),
        handlers={"sync_order": lambda _: None},
        max_attempts=8,
        base_delay_seconds=5,
        realtime=realtime,
    )

    await worker.run_once()

    assert realtime.events == [
        (
            str(order_id),
            {
                "type": "order_chat_delivery",
                "message_id": str(message_id),
                "delivery_state": "synced",
            },
        )
    ]
