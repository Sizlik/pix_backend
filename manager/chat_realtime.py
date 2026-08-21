import asyncio
import json
from collections import defaultdict


class LocalChatHub:
    def __init__(self):
        self.connections = defaultdict(set)

    async def register(self, room_id: str, websocket) -> None:
        self.connections[str(room_id)].add(websocket)

    async def connect(self, room_id: str, websocket) -> None:
        await websocket.accept()
        await self.register(room_id, websocket)

    async def disconnect(self, room_id: str, websocket) -> None:
        room = self.connections.get(str(room_id))
        if room is None:
            return
        room.discard(websocket)
        if not room:
            self.connections.pop(str(room_id), None)

    async def broadcast(self, room_id: str, message: dict) -> None:
        room_key = str(room_id)
        room = self.connections.get(room_key)
        if not room:
            return
        for websocket in tuple(room):
            try:
                await websocket.send_json(message)
            except Exception:
                room.discard(websocket)
        if not room:
            self.connections.pop(room_key, None)


class RedisChatRealtime:
    channel_prefix = "order-chat:room:"

    def __init__(self, redis_client, local_hub: LocalChatHub):
        self._redis = redis_client
        self._local_hub = local_hub
        self._pubsub = None
        self._listener_task: asyncio.Task | None = None

    async def register(self, room_id: str, websocket) -> None:
        await self._local_hub.register(str(room_id), websocket)

    async def connect(self, room_id: str, websocket) -> None:
        await self._local_hub.connect(str(room_id), websocket)

    async def disconnect(self, room_id: str, websocket) -> None:
        await self._local_hub.disconnect(str(room_id), websocket)

    async def start(self) -> None:
        if self._listener_task is not None:
            return
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(f"{self.channel_prefix}*")
        self._listener_task = asyncio.create_task(self._listen(), name="chat-redis-listener")

    async def stop(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
        if self._pubsub is not None:
            close = getattr(self._pubsub, "aclose", None)
            if close is None:
                close = self._pubsub.close
            result = close()
            if hasattr(result, "__await__"):
                await result
            self._pubsub = None

    async def publish(self, room_id: str, message: dict) -> None:
        await self._redis.publish(
            f"{self.channel_prefix}{room_id}",
            json.dumps(message, ensure_ascii=False),
        )

    async def dispatch_for_test(self, channel, payload) -> None:
        if isinstance(channel, bytes):
            channel = channel.decode("utf-8")
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        if not channel.startswith(self.channel_prefix):
            return
        room_id = channel[len(self.channel_prefix) :]
        await self._local_hub.broadcast(room_id, json.loads(payload))

    async def _listen(self) -> None:
        while True:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
            if message is not None and message.get("type") in {
                "message",
                "pmessage",
            }:
                await self.dispatch_for_test(message["channel"], message["data"])
            await asyncio.sleep(0.01)
