from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from db.moysklad_order_chat_repository import MoySkladFile
from manager.moysklad_order_chat import MoySkladOrderChatSynchronizer
from manager.order_chat_format import CHAT_HEADER, PRIOR_COMMENT_FILENAME

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
