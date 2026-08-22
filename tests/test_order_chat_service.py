from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from manager.order_chat import (
    OrderChatAccessPolicy,
    OrderChatNotFound,
    OrderChatService,
    PendingUpload,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
CLIENT_ID = UUID("00000000-0000-0000-0000-000000000002")


@dataclass
class UserStub:
    id: UUID = CLIENT_ID
    moysklad_counterparty_id: UUID = UUID("00000000-0000-0000-0000-000000000003")
    first_name: str = "Анна"
    name_id: int = 42
    email: str = "client@example.com"


class FakeMoySklad:
    async def get_order(self, order_id):
        return {
            "id": str(order_id),
            "name": "101",
            "agent": {
                "meta": {
                    "href": (
                        f"https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{UserStub.moysklad_counterparty_id}"
                    )
                }
            },
        }


class FakeStorage:
    def __init__(self):
        self.objects = {}

    async def put(self, key, content, content_type):
        self.objects[key] = content

    async def read(self, key):
        return self.objects[key]

    async def delete(self, key):
        self.objects.pop(key, None)


class FakeRepository:
    def __init__(self, fail=False):
        self.created = None
        self.fail = fail

    async def ensure_state(self, order_id, client_id):
        return None

    async def create_client_message_with_delivery(self, **values):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.created = values
        attachments = tuple(
            SimpleNamespace(
                id=item.id,
                original_filename=item.original_filename,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
            )
            for item in values["attachments"]
        )
        return SimpleNamespace(
            id=values["message_id"],
            order_id=values["order_id"],
            client_id=values["client_id"],
            sender_kind="client",
            source=values["source"],
            body=values["body"],
            created_at=datetime.now(timezone.utc),
            attachments=attachments,
        )


def make_service(*, moysklad=None, repository=None, storage=None):
    moysklad = moysklad or FakeMoySklad()
    repository = repository or FakeRepository()
    storage = storage or FakeStorage()
    return (
        OrderChatService(
            repository=repository,
            storage=storage,
            access_policy=OrderChatAccessPolicy(moysklad),
            attachment_max_count=10,
            attachment_max_bytes=20 * 1024 * 1024,
            manager_email="manager@example.com",
        ),
        repository,
        storage,
    )


async def test_access_policy_hides_another_clients_order():
    moysklad = FakeMoySklad()

    async def another_order(order_id):
        order = await FakeMoySklad().get_order(order_id)
        order["agent"]["meta"]["href"] = (
            order["agent"]["meta"]["href"].rsplit("/", 1)[0] + "/00000000-0000-0000-0000-000000000099"
        )
        return order

    moysklad.get_order = another_order
    service, _, _ = make_service(moysklad=moysklad)

    with pytest.raises(OrderChatNotFound):
        await service.list_messages(UserStub(), ORDER_ID, before=None, limit=50)


async def test_file_only_message_has_no_projection_event_or_delivery_state():
    service, repository, storage = make_service()

    result = await service.create_client_message(
        UserStub(),
        ORDER_ID,
        body="  ",
        uploads=[PendingUpload(filename="note.txt", content=b"hello")],
    )

    assert result.message == ""
    assert result.sender_label == "Клиент"
    assert len(result.attachments) == 1
    assert "outbox_events" not in repository.created
    assert repository.created["order_name"] == "101"
    assert repository.created["email_delivery"].recipient_email == (
        "manager@example.com"
    )
    assert not hasattr(result, "delivery_state")
    assert len(storage.objects) == 1


async def test_database_failure_removes_new_storage_objects():
    repository = FakeRepository(fail=True)
    service, _, storage = make_service(repository=repository)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.create_client_message(
            UserStub(),
            ORDER_ID,
            body="file",
            uploads=[PendingUpload(filename="note.txt", content=b"hello")],
        )

    assert storage.objects == {}
