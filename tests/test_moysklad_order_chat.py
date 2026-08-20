import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from db.moysklad_order_chat_repository import MoySkladFile
from manager.moysklad_order_chat import MoySkladOrderChatSynchronizer
from manager.order_chat_format import (
    CHAT_HEADER,
    PRIOR_COMMENT_FILENAME,
    REPLY_PROMPT,
    description_hash,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
CLIENT_ID = UUID("00000000-0000-0000-0000-000000000002")


class FakeStorage:
    async def read(self, key):
        return b"stored"


class FakeRepository:
    def __init__(self):
        self.state = SimpleNamespace(
            order_id=ORDER_ID,
            client_id=CLIENT_ID,
            initialized=False,
            prior_comment_file_id=None,
            history_file_id=None,
        )
        self.recorded = []
        self.updated = []
        self.message = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000010"),
            sender_kind="client",
            body="Где заказ?",
            created_at=datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc),
            attachments=(),
        )

    async def get_state(self, order_id):
        return self.state

    async def list_transcript(self, order_id):
        return [self.message]

    async def list_unmirrored_site_attachments(self, order_id):
        return []

    async def list_moysklad_files(self, order_id):
        return []

    async def record_moysklad_files(self, files):
        self.recorded.extend(files)

    async def update_state(self, order_id, **values):
        self.updated.append(values)
        for key, value in values.items():
            setattr(self.state, key, value)


class FakeMoySklad:
    def __init__(self):
        self.description = "Старый комментарий"
        self.files = [
            MoySkladFile(
                id=UUID("00000000-0000-0000-0000-000000000020"),
                filename="internal.pdf",
                size=10,
                download_href="https://api.moysklad.ru/file",
            )
        ]
        self.uploaded = []
        self.deleted = []

    async def get_order(self, order_id):
        return {"id": str(order_id), "description": self.description}

    async def list_files(self, order_id):
        return list(self.files)

    async def upload_files(self, order_id, uploads):
        result = []
        for index, upload in enumerate(uploads, start=30):
            self.uploaded.append(upload)
            result.append(
                MoySkladFile(
                    id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
                    filename=upload.filename,
                    size=len(upload.content),
                    download_href="https://api.moysklad.ru/file",
                )
            )
        self.files.extend(result)
        return result

    async def update_description(self, order_id, description):
        self.description = description
        return {"description": description}

    async def delete_file(self, order_id, file_id):
        self.deleted.append(file_id)


async def test_first_sync_backs_up_comment_baselines_files_and_projects_message():
    repository = FakeRepository()
    moysklad = FakeMoySklad()
    synchronizer = MoySkladOrderChatSynchronizer(
        repository=repository,
        moysklad=moysklad,
        storage=FakeStorage(),
    )

    await synchronizer.sync_order(ORDER_ID)

    assert moysklad.uploaded[0].filename == PRIOR_COMMENT_FILENAME
    assert moysklad.uploaded[0].content == "Старый комментарий".encode()
    assert moysklad.description.startswith(CHAT_HEADER)
    assert "Где заказ?" in moysklad.description
    assert repository.recorded[0].disposition == "baseline"
    assert repository.state.initialized is True


async def test_repeated_sync_does_not_duplicate_comment_backup():
    repository = FakeRepository()
    moysklad = FakeMoySklad()
    synchronizer = MoySkladOrderChatSynchronizer(
        repository=repository,
        moysklad=moysklad,
        storage=FakeStorage(),
    )

    await synchronizer.sync_order(ORDER_ID)
    await synchronizer.sync_order(ORDER_ID)

    assert [item.filename for item in moysklad.uploaded if item.filename == PRIOR_COMMENT_FILENAME] == [
        PRIOR_COMMENT_FILENAME
    ]


class InboundRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.state.initialized = True
        self.state.rendered_description_hash = None
        self.messages = [self.message]
        self.known_files = []
        self.events = []
        self.notifications = []

    async def get_state_client(self, order_id):
        return SimpleNamespace(
            id=CLIENT_ID,
            moysklad_counterparty_id=UUID("00000000-0000-0000-0000-000000000099"),
        )

    async def list_transcript(self, order_id):
        return self.messages

    async def list_moysklad_files(self, order_id):
        return self.known_files

    async def record_moysklad_files(self, files):
        self.recorded.extend(files)
        self.known_files.extend(files)

    async def get_message_by_external_key(self, external_key):
        return next(
            (item for item in self.messages if getattr(item, "external_key", None) == external_key),
            None,
        )

    async def create_manager_message_with_notification(self, **values):
        attachments = tuple(
            SimpleNamespace(
                id=item.id,
                original_filename=item.original_filename,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
            )
            for item in values["attachments"]
        )
        message = SimpleNamespace(
            id=values["message_id"],
            order_id=values["order_id"],
            sender_kind="manager",
            body=values["body"],
            created_at=datetime.now(timezone.utc),
            attachments=attachments,
            external_key=values["external_key"],
        )
        self.messages.append(message)
        self.events.extend(values["outbox_events"])
        self.notifications.append(message.id)
        self.recorded.extend(values.get("moysklad_files", ()))
        self.known_files.extend(values.get("moysklad_files", ()))
        return message

    async def enqueue_events(self, events):
        self.events.extend(events)


class InboundStorage(FakeStorage):
    def __init__(self):
        self.objects = {}

    async def put(self, key, content, content_type):
        self.objects[key] = content

    async def delete(self, key):
        self.objects.pop(key, None)


class InboundMoySklad(FakeMoySklad):
    def __init__(self, canonical):
        super().__init__()
        self.description = canonical
        self.files = []
        self.file_content = {}

    async def get_order(self, order_id):
        return {
            "id": str(order_id),
            "description": self.description,
            "agent": {
                "meta": {
                    "href": (
                        "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/00000000-0000-0000-0000-000000000099"
                    )
                }
            },
        }

    async def download_file(self, download_href):
        return self.file_content[download_href]


def inbound_event(audit="audit-1"):
    return SimpleNamespace(
        order_id=ORDER_ID,
        payload={
            "request_id": f"request-{audit}",
            "audit_href": f"https://api.moysklad.ru/audit/{audit}",
        },
    )


def inbound_fixture(notification_manager=None):
    repository = InboundRepository()
    canonical = f"{CHAT_HEADER}\n\n[10.08.2026 12:00] Клиент: Где заказ?\n\n{REPLY_PROMPT}"
    repository.state.rendered_description_hash = description_hash(canonical)
    moysklad = InboundMoySklad(canonical)
    storage = InboundStorage()
    notification_options = {}
    if notification_manager is not None:
        notification_options["notification_manager"] = notification_manager
    synchronizer = MoySkladOrderChatSynchronizer(
        repository=repository,
        moysklad=moysklad,
        storage=storage,
        attachment_max_count=10,
        attachment_max_bytes=20 * 1024 * 1024,
        **notification_options,
    )
    return synchronizer, repository, moysklad, storage, canonical


class RecordingNotificationManager:
    def __init__(self):
        self.user_ids = []

    async def notify_count_changed(self, user_id):
        self.user_ids.append(user_id)


async def test_manager_reply_publishes_notification_count_after_transaction():
    notification_manager = RecordingNotificationManager()
    synchronizer, repository, moysklad, _, canonical = inbound_fixture(
        notification_manager=notification_manager
    )
    moysklad.description = canonical + "\nПринято"

    await synchronizer.process_moysklad_update(inbound_event("count"))

    assert repository.notifications
    assert notification_manager.user_ids == [CLIENT_ID]


async def test_failed_manager_message_transaction_does_not_publish_count():
    notification_manager = RecordingNotificationManager()
    synchronizer, repository, moysklad, _, canonical = inbound_fixture(
        notification_manager=notification_manager
    )
    moysklad.description = canonical + "\nПринято"

    async def fail(**values):
        raise RuntimeError("transaction failed")

    repository.create_manager_message_with_notification = fail
    with pytest.raises(RuntimeError, match="transaction failed"):
        await synchronizer.process_moysklad_update(inbound_event("failure"))

    assert notification_manager.user_ids == []


async def test_manager_reply_and_prefixed_file_create_one_immutable_message():
    synchronizer, repository, moysklad, storage, canonical = inbound_fixture()
    public_id = UUID("00000000-0000-0000-0000-000000000201")
    href = "https://api.moysklad.ru/api/remap/1.2/download/public"
    moysklad.description = canonical + "\nОтправили ваш заказ"
    moysklad.files = [MoySkladFile(public_id, "[КЛИЕНТ] фото.jpg", 10, href)]
    moysklad.file_content[href] = b"\xff\xd8\xffimage"

    await synchronizer.process_moysklad_update(inbound_event())

    message = repository.messages[-1]
    assert message.sender_kind == "manager"
    assert message.body == "Отправили ваш заказ"
    assert message.attachments[0].original_filename == "фото.jpg"
    assert repository.notifications == [message.id]
    assert repository.events == []
    assert len(storage.objects) == 1
    assert moysklad.description.endswith(REPLY_PROMPT)


async def test_missing_reply_marker_logs_code_and_restores_description(caplog):
    synchronizer, repository, moysklad, _, _ = inbound_fixture()
    moysklad.description = "случайно переписанный комментарий"

    with caplog.at_level(logging.WARNING):
        await synchronizer.process_moysklad_update(inbound_event("bad-marker"))

    assert len(repository.messages) == 1
    assert repository.events == []
    assert "order_chat_projection_rejected" in caplog.text
    assert str(ORDER_ID) in caplog.text
    assert "malformed_comment" in caplog.text
    assert "случайно переписанный комментарий" not in caplog.text
    assert moysklad.description.endswith(REPLY_PROMPT)


async def test_unprefixed_new_file_remains_internal():
    synchronizer, repository, moysklad, _, _ = inbound_fixture()
    moysklad.files = [
        MoySkladFile(
            UUID("00000000-0000-0000-0000-000000000202"),
            "warehouse.pdf",
            10,
            "https://api.moysklad.ru/internal",
        )
    ]

    await synchronizer.process_moysklad_update(inbound_event("internal"))

    assert len(repository.messages) == 1
    assert repository.recorded[-1].disposition == "internal"


async def test_replayed_audit_does_not_duplicate_manager_message():
    synchronizer, repository, moysklad, _, canonical = inbound_fixture()
    moysklad.description = canonical + "\nПринято"

    event = inbound_event("replay")
    await synchronizer.process_moysklad_update(event)
    await synchronizer.process_moysklad_update(event)

    assert [item.body for item in repository.messages[1:]] == ["Принято"]


async def test_invalid_public_batch_is_all_or_nothing_and_keeps_reply(caplog):
    synchronizer, repository, moysklad, storage, canonical = inbound_fixture()
    moysklad.description = canonical + "\nФайлы"
    moysklad.files = [
        MoySkladFile(
            UUID(f"00000000-0000-0000-0000-{index:012d}"),
            f"[КЛИЕНТ] {index}.jpg",
            10,
            f"https://api.moysklad.ru/download/{index}",
        )
        for index in range(1, 12)
    ]

    with caplog.at_level(logging.WARNING):
        await synchronizer.process_moysklad_update(inbound_event("too-many"))

    assert len(repository.messages) == 1
    assert storage.objects == {}
    assert repository.events == []
    assert "order_chat_projection_rejected" in caplog.text
    assert "manager_file_count" in caplog.text
    assert moysklad.description.endswith("Файлы")
