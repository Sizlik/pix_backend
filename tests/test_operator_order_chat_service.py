from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from errors import MoySkladOrderLookupUnavailable
from manager.chat_files import ChatFileRejected
from manager.order_chat import (
    OperatorOrderChatAccessPolicy,
    OrderChatNotFound,
    OrderChatService,
    PendingUpload,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_ORDER_ID = UUID("00000000-0000-0000-0000-000000000002")
CLIENT_ID = UUID("00000000-0000-0000-0000-000000000003")
COUNTERPARTY_ID = UUID("00000000-0000-0000-0000-000000000004")
ATTACHMENT_ID = UUID("00000000-0000-0000-0000-000000000005")
DEFAULT_ORDER = object()


@dataclass
class ClientStub:
    id: UUID = CLIENT_ID


class FakeMoySklad:
    def __init__(self, order=DEFAULT_ORDER, failure=None):
        self.order = linked_order() if order is DEFAULT_ORDER else order
        self.failure = failure

    async def get_order(self, order_id):
        if self.failure is not None:
            raise self.failure
        return self.order


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.read_keys = []

    async def put(self, key, content, content_type):
        self.objects[key] = content

    async def read(self, key):
        self.read_keys.append(key)
        return self.objects[key]

    async def delete(self, key):
        self.objects.pop(key, None)


class FakeRepository:
    def __init__(self):
        self.user = ClientStub()
        self.ensured = []
        self.ensure_failure = None
        self.created = None
        self.failure = None
        self.messages = []
        self.next_before = None
        self.listed = []
        self.attachment = None

    async def get_user_by_moysklad_counterparty(self, counterparty_id):
        assert counterparty_id == COUNTERPARTY_ID
        return self.user

    async def ensure_state(self, order_id, client_id):
        if self.ensure_failure is not None:
            raise self.ensure_failure
        self.ensured.append((order_id, client_id))

    async def create_manager_message_with_notification(self, **values):
        if self.failure is not None:
            raise self.failure
        self.created = values
        attachments = tuple(
            SimpleNamespace(
                id=item.id,
                original_filename=item.original_filename,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
                object_key=item.object_key,
            )
            for item in values["attachments"]
        )
        return stored_message(
            message_id=values["message_id"],
            body=values["body"],
            attachments=attachments,
        )

    async def list_messages(self, order_id, before, limit):
        self.listed.append((order_id, before, limit))
        return self.messages, self.next_before

    async def get_attachment_for_order(self, order_id, attachment_id):
        assert attachment_id == ATTACHMENT_ID
        if self.attachment is None:
            return None
        attachment, message = self.attachment
        if message.order_id != order_id:
            return None
        return attachment, message


class FakeRealtime:
    def __init__(self):
        self.rooms = []
        self.failure = None

    async def publish(self, room, payload):
        self.rooms.append(room)
        if self.failure is not None:
            raise self.failure


class FakeNotifications:
    def __init__(self):
        self.changed = []
        self.failure = None

    async def notify_count_changed(self, user_id):
        self.changed.append(user_id)
        if self.failure is not None:
            raise self.failure


def linked_order():
    return {
        "agent": {
            "meta": {
                "href": (
                    "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/"
                    f"{COUNTERPARTY_ID}"
                )
            }
        }
    }


def stored_message(*, message_id=UUID(int=30), body="Готово", attachments=()):
    return SimpleNamespace(
        id=message_id,
        order_id=ORDER_ID,
        client_id=CLIENT_ID,
        sender_kind="manager",
        source="extension",
        body=body,
        created_at=datetime.now(timezone.utc),
        attachments=attachments,
    )


def zip_bytes(member: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(member, "content")
    return output.getvalue()


def make_policy(*, moysklad=None, repository=None):
    repository = repository or FakeRepository()
    return OperatorOrderChatAccessPolicy(moysklad or FakeMoySklad(), repository), repository


def make_service():
    repository = FakeRepository()
    storage = FakeStorage()
    realtime = FakeRealtime()
    notifications = FakeNotifications()
    policy = OperatorOrderChatAccessPolicy(FakeMoySklad(), repository)
    service = OrderChatService(
        repository=repository,
        storage=storage,
        access_policy=SimpleNamespace(),
        operator_access_policy=policy,
        notification_manager=notifications,
        attachment_max_count=10,
        attachment_max_bytes=20 * 1024 * 1024,
        realtime=realtime,
    )
    return service, repository, storage, realtime, notifications


async def test_operator_policy_resolves_linked_counterparty_and_pins_state():
    policy, repository = make_policy()

    client = await policy.resolve_client(ORDER_ID)

    assert client.id == CLIENT_ID
    assert repository.ensured == [(ORDER_ID, CLIENT_ID)]


@pytest.mark.parametrize(
    "order",
    [
        None,
        {},
        {"agent": {}},
        {"agent": {"meta": {}}},
        {"agent": {"meta": {"href": "https://example.test/not-a-uuid"}}},
    ],
)
async def test_operator_policy_hides_missing_or_malformed_orders(order):
    policy, _ = make_policy(moysklad=FakeMoySklad(order=order))

    with pytest.raises(OrderChatNotFound):
        await policy.resolve_client(ORDER_ID)


async def test_operator_policy_hides_unlinked_order():
    policy, repository = make_policy()
    repository.user = None

    with pytest.raises(OrderChatNotFound):
        await policy.resolve_client(ORDER_ID)


async def test_operator_policy_hides_order_state_conflict():
    policy, repository = make_policy()
    repository.ensure_failure = LookupError("different client")

    with pytest.raises(OrderChatNotFound):
        await policy.resolve_client(ORDER_ID)


async def test_operator_policy_propagates_generic_lookup_outage():
    outage = MoySkladOrderLookupUnavailable()
    policy, _ = make_policy(moysklad=FakeMoySklad(failure=outage))

    with pytest.raises(MoySkladOrderLookupUnavailable) as raised:
        await policy.resolve_client(ORDER_ID)

    assert raised.value is outage


@pytest.mark.parametrize(
    ("body", "uploads", "expected_body", "attachment_count"),
    [
        ("  Документы готовы  ", [], "Документы готовы", 0),
        ("  ", [PendingUpload("note.txt", b"hello")], "", 1),
        (
            "  Документы готовы  ",
            [PendingUpload("invoice.pdf", b"%PDF-1.7")],
            "Документы готовы",
            1,
        ),
    ],
)
async def test_manager_message_supports_text_file_only_and_mixed_messages(
    body,
    uploads,
    expected_body,
    attachment_count,
):
    service, repository, _, realtime, notifications = make_service()

    result = await service.create_manager_message(ORDER_ID, body, uploads)

    assert repository.created["source"] == "extension"
    assert repository.created["external_key"] is None
    assert repository.created["outbox_events"] == ()
    assert repository.created["moysklad_files"] == ()
    assert all(item.origin == "extension" for item in repository.created["attachments"])
    assert len(repository.created["attachments"]) == attachment_count
    assert result.sender_kind.value == "manager"
    assert result.message == expected_body
    assert not hasattr(result, "delivery_state")
    assert notifications.changed == [CLIENT_ID]
    assert realtime.rooms == [str(ORDER_ID)]


async def test_manager_database_failure_removes_new_minio_objects():
    service, repository, storage, _, _ = make_service()
    repository.failure = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.create_manager_message(
            ORDER_ID,
            "file",
            [PendingUpload("note.txt", b"hello")],
        )

    assert storage.objects == {}


async def test_committed_manager_message_survives_realtime_failure_and_still_notifies():
    service, repository, _, realtime, notifications = make_service()
    realtime.failure = RuntimeError("redis unavailable")

    result = await service.create_manager_message(ORDER_ID, "Готово", [])

    assert result.message == "Готово"
    assert repository.created["source"] == "extension"
    assert notifications.changed == [CLIENT_ID]


async def test_committed_manager_message_survives_notification_publish_failure():
    service, repository, _, _, notifications = make_service()
    notifications.failure = RuntimeError("redis unavailable")

    result = await service.create_manager_message(ORDER_ID, "Готово", [])

    assert result.message == "Готово"
    assert repository.created["source"] == "extension"
    assert notifications.changed == [CLIENT_ID]


@pytest.mark.parametrize(
    "uploads",
    [
        [PendingUpload("a.txt", b"a")] * 11,
        [PendingUpload("large.txt", b"a" * (20 * 1024 * 1024 + 1))],
        [PendingUpload("program.exe", b"MZ")],
        [PendingUpload("fake.pdf", b"not a pdf")],
        [PendingUpload("unsafe.zip", zip_bytes("../escape.txt"))],
    ],
)
async def test_manager_message_rejects_invalid_files_before_commit(uploads):
    service, repository, storage, _, _ = make_service()

    with pytest.raises(ChatFileRejected):
        await service.create_manager_message(ORDER_ID, "file", uploads)

    assert repository.created is None
    assert storage.objects == {}


async def test_operator_history_preserves_pagination_contract():
    service, repository, _, _, _ = make_service()
    before = UUID(int=40)
    repository.messages = [stored_message(message_id=UUID(int=41))]
    repository.next_before = UUID(int=42)

    page = await service.list_operator_messages(ORDER_ID, before=before, limit=25)

    assert repository.listed == [(ORDER_ID, before, 25)]
    assert [item.id for item in page.items] == [UUID(int=41)]
    assert page.next_before == UUID(int=42)


async def test_cross_order_attachment_is_not_read_from_minio():
    service, repository, storage, _, _ = make_service()
    attachment = SimpleNamespace(
        original_filename="secret.txt",
        mime_type="text/plain",
        object_key="other-order/secret",
    )
    repository.attachment = (attachment, stored_message())
    repository.attachment[1].order_id = OTHER_ORDER_ID
    storage.objects[attachment.object_key] = b"secret"

    with pytest.raises(OrderChatNotFound):
        await service.get_operator_attachment(ORDER_ID, ATTACHMENT_ID)

    assert storage.read_keys == []
