import asyncio
import importlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from db.order_chat_repository import StoredConversation, StoredMessage
from errors import MoySkladOrderLookupUnavailable
from manager.order_chat import OrderChatService

CLIENT_ID = UUID("00000000-0000-0000-0000-000000000099")
BASE_TIME = datetime(2026, 8, 22, 12, tzinfo=UTC)


class FakeStorage:
    async def put(self, key, content, content_type):
        raise AssertionError("no attachments expected")

    async def read(self, key):
        raise AssertionError("no downloads expected")

    async def delete(self, key):
        raise AssertionError("no stored objects expected")


class FakeClientAccess:
    async def assert_client_access(self, user, order_id):
        return {"id": str(order_id), "name": "10001"}


class FakeOperatorAccess:
    def __init__(self, names=None, failing=None):
        self.names = names or {}
        self.failing = set() if failing is None else set(failing)
        self.active = 0
        self.max_active = 0

    async def resolve_client(self, order_id):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.001)
            if order_id in self.failing:
                raise MoySkladOrderLookupUnavailable()
            return SimpleNamespace(
                client=SimpleNamespace(
                    id=CLIENT_ID,
                    email="client@example.com",
                ),
                order_name=self.names.get(order_id, "10001"),
            )
        finally:
            self.active -= 1


class FakeRepository:
    def __init__(self):
        self.client_created = None
        self.manager_created = None
        self.items = []
        self.next_before = None
        self.total_unread = 0
        self.cached_names = []
        self.conversations = {}
        self.cleared = []

    async def ensure_state(self, order_id, client_id):
        return None

    async def create_client_message_with_delivery(self, **values):
        self.client_created = values
        stored = stored_message(
            values["order_id"],
            values["message_id"],
            "client",
            values["body"],
        )
        self.total_unread = 1
        self.conversations[values["order_id"]] = StoredConversation(
            order_id=values["order_id"],
            order_name=values["order_name"],
            last_message=stored,
            attachment_count=0,
            unread_count=1,
        )
        return stored

    async def create_manager_message_with_notification(self, **values):
        self.manager_created = values
        stored = stored_message(
            values["order_id"],
            values["message_id"],
            "manager",
            values["body"],
        )
        self.conversations[values["order_id"]] = StoredConversation(
            order_id=values["order_id"],
            order_name=values["order_name"],
            last_message=stored,
            attachment_count=0,
            unread_count=0,
        )
        return stored

    async def list_conversations(self, before, limit):
        return self.items, self.next_before

    async def total_operator_unread(self):
        return self.total_unread

    async def cache_order_name(self, order_id, order_name):
        self.cached_names.append((order_id, order_name))

    async def conversation(self, order_id):
        return self.conversations.get(order_id)

    async def clear_operator_unread(self, order_id):
        self.cleared.append(order_id)
        item = self.conversations[order_id]
        self.conversations[order_id] = StoredConversation(
            order_id=item.order_id,
            order_name=item.order_name,
            last_message=item.last_message,
            attachment_count=item.attachment_count,
            unread_count=0,
        )
        self.total_unread -= item.unread_count
        return self.total_unread


class FakeRealtime:
    def __init__(self, failure=None):
        self.events = []
        self.failure = failure

    async def publish(self, room, payload):
        self.events.append((room, payload))
        if self.failure is not None:
            raise self.failure


class FakeNotifications:
    def __init__(self):
        self.changed = []

    async def notify_count_changed(self, user_id):
        self.changed.append(user_id)


def stored_message(order_id, message_id, sender_kind, body):
    return StoredMessage(
        id=message_id,
        order_id=order_id,
        client_id=CLIENT_ID,
        sender_kind=sender_kind,
        source="site" if sender_kind == "client" else "extension",
        body=body,
        created_at=BASE_TIME,
        attachments=(),
    )


def stored_conversation(index, *, name=None, unread=0):
    order_id = UUID(int=index)
    return StoredConversation(
        order_id=order_id,
        order_name=name,
        last_message=stored_message(
            order_id,
            UUID(int=100 + index),
            "client",
            f"Сообщение {index}",
        ),
        attachment_count=index % 2,
        unread_count=unread,
    )


def make_service(
    *,
    repository=None,
    operator_access=None,
    room_realtime=None,
    inbox_realtime=None,
    manager_email="manager@example.com",
):
    repository = repository or FakeRepository()
    notifications = FakeNotifications()
    service = OrderChatService(
        repository=repository,
        storage=FakeStorage(),
        access_policy=FakeClientAccess(),
        operator_access_policy=operator_access or FakeOperatorAccess(),
        notification_manager=notifications,
        attachment_max_count=10,
        attachment_max_bytes=1024,
        realtime=room_realtime or FakeRealtime(),
        inbox_realtime=inbox_realtime or FakeRealtime(),
        manager_email=manager_email,
    )
    return service, repository, notifications


async def test_client_message_captures_order_name_and_only_manager_email_delivery():
    room_realtime = FakeRealtime()
    inbox_realtime = FakeRealtime()
    service, repository, notifications = make_service(
        room_realtime=room_realtime,
        inbox_realtime=inbox_realtime,
    )
    user = SimpleNamespace(id=CLIENT_ID, email="client@example.com")
    order_id = UUID(int=1)

    response = await service.create_client_message(user, order_id, " Привет ", [])

    created = repository.client_created
    assert created["order_name"] == "10001"
    assert created["email_delivery"].recipient_email == "manager@example.com"
    assert created["email_delivery"].recipient_kind == "manager"
    assert response.message == "Привет"
    assert notifications.changed == []
    assert room_realtime.events[0][0] == str(order_id)
    room, event = inbox_realtime.events[0]
    assert room == "global"
    assert event["type"] == "conversation_updated"
    assert event["item"]["unread_count"] == 1
    assert event["total_unread"] == 1


async def test_manager_message_queues_only_client_email_and_notifies_website_count():
    inbox_realtime = FakeRealtime()
    service, repository, notifications = make_service(
        inbox_realtime=inbox_realtime
    )
    order_id = UUID(int=2)

    response = await service.create_manager_message(order_id, " Готово ", [])

    created = repository.manager_created
    assert created["order_name"] == "10001"
    assert created["email_delivery"].recipient_email == "client@example.com"
    assert created["email_delivery"].recipient_kind == "client"
    assert response.message == "Готово"
    assert notifications.changed == [CLIENT_ID]
    assert inbox_realtime.events[0][1]["item"]["unread_count"] == 0


async def test_email_disabled_commits_messages_without_delivery_rows():
    service, repository, _ = make_service(manager_email=None)
    user = SimpleNamespace(id=CLIENT_ID, email="client@example.com")

    await service.create_client_message(user, UUID(int=3), "Клиент", [])
    assert repository.client_created["email_delivery"] is None

    await service.create_manager_message(UUID(int=4), "Менеджер", [])
    assert repository.manager_created["email_delivery"] is None


async def test_inbox_hydrates_missing_names_with_bounded_concurrency_and_fallback():
    repository = FakeRepository()
    repository.items = [stored_conversation(index, unread=1) for index in range(1, 8)]
    repository.total_unread = 7
    failing_order = UUID(int=7)
    names = {UUID(int=index): f"10{index:03d}" for index in range(1, 7)}
    operator_access = FakeOperatorAccess(names=names, failing={failing_order})
    service, _, _ = make_service(
        repository=repository,
        operator_access=operator_access,
    )

    page = await service.list_operator_conversations(None, 50)

    assert [item.order_id for item in page.items] == [UUID(int=index) for index in range(1, 8)]
    assert [item.order_name for item in page.items[:6]] == [
        f"10{index:03d}" for index in range(1, 7)
    ]
    assert page.items[-1].order_name == "…00000007"
    assert page.total_unread == 7
    assert sorted(repository.cached_names) == [
        (UUID(int=index), f"10{index:03d}") for index in range(1, 7)
    ]
    assert operator_access.max_active == 5


async def test_mark_read_clears_global_count_and_publishes_zero_unread_summary():
    repository = FakeRepository()
    order_id = UUID(int=8)
    repository.total_unread = 5
    repository.conversations[order_id] = stored_conversation(8, name="10008", unread=2)
    inbox_realtime = FakeRealtime()
    service, _, _ = make_service(
        repository=repository,
        inbox_realtime=inbox_realtime,
    )

    response = await service.mark_operator_read(order_id)

    assert response.order_id == order_id
    assert response.unread_count == 0
    assert response.total_unread == 3
    assert repository.cleared == [order_id]
    assert inbox_realtime.events[0][1]["item"]["unread_count"] == 0
    assert inbox_realtime.events[0][1]["total_unread"] == 3


async def test_committed_message_survives_inbox_redis_failure():
    service, repository, _ = make_service(
        inbox_realtime=FakeRealtime(RuntimeError("redis unavailable"))
    )
    user = SimpleNamespace(id=CLIENT_ID, email="client@example.com")

    response = await service.create_client_message(user, UUID(int=9), "Есть", [])

    assert response.message == "Есть"
    assert repository.client_created is not None


def test_operator_inbox_realtime_uses_a_separate_global_redis_namespace():
    realtime_module = importlib.import_module("manager.operator_inbox_realtime")
    dependency_module = importlib.import_module("dependecies.operator_inbox")

    assert realtime_module.OperatorInboxRealtime.channel_prefix == (
        "order-chat:operator-inbox:"
    )
    assert dependency_module.get_operator_inbox_realtime() is (
        dependency_module.get_operator_inbox_realtime()
    )
