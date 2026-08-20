import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

from db.schemas.notifications import NotificationCreate, NotificationTypes
from manager.notifications import NotificationManager
from routes.notifications import get_user_notifications

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000002")
NOTIFICATION_ID = UUID("00000000-0000-0000-0000-000000000010")


class MemoryNotificationRepository:
    def __init__(self):
        self.rows = {
            NOTIFICATION_ID: SimpleNamespace(
                id=NOTIFICATION_ID,
                user_id=USER_ID,
                is_readed=False,
                time_created="2026-08-11T00:00:00Z",
            )
        }
        self.mark_all_calls = 0

    async def create(self, **values):
        values["user_id"] = UUID(str(values["user_id"]))
        self.rows[NOTIFICATION_ID] = SimpleNamespace(
            id=NOTIFICATION_ID,
            is_readed=False,
            time_created="2026-08-11T00:00:00Z",
            **values,
        )
        return NOTIFICATION_ID

    async def list_for_user(self, user_id):
        return [row for row in self.rows.values() if row.user_id == user_id]

    async def count_unread(self, user_id):
        return sum(
            row.user_id == user_id and not row.is_readed
            for row in self.rows.values()
        )

    async def mark_read(self, notification_id, user_id):
        row = self.rows.get(notification_id)
        if row is None or row.user_id != user_id or row.is_readed:
            return False
        row.is_readed = True
        return True

    async def mark_all_read(self, user_id):
        self.mark_all_calls += 1
        changed = 0
        for row in self.rows.values():
            if row.user_id == user_id and not row.is_readed:
                row.is_readed = True
                changed += 1
        return changed


class RecordingRealtime:
    def __init__(self, error=None):
        self.events = []
        self.error = error

    async def publish(self, user_id, payload):
        if self.error:
            raise self.error
        self.events.append((str(user_id), payload))


class SerializedRecordingRealtime(RecordingRealtime):
    def __init__(self):
        super().__init__()
        self._count_lock = asyncio.Lock()

    @asynccontextmanager
    async def count_lock(self, user_id):
        async with self._count_lock:
            yield


class TimedOutRealtime(RecordingRealtime):
    @asynccontextmanager
    async def count_lock(self, user_id):
        raise TimeoutError
        yield


class BlockingCountRepository(MemoryNotificationRepository):
    def __init__(self):
        super().__init__()
        self.count_calls = 0
        self.first_count_started = asyncio.Event()
        self.release_first_count = asyncio.Event()

    async def count_unread(self, user_id):
        self.count_calls += 1
        if self.count_calls == 1:
            self.first_count_started.set()
            await self.release_first_count.wait()
            return 1
        return 0


async def test_read_one_cannot_change_another_users_notification():
    repository = MemoryNotificationRepository()
    realtime = RecordingRealtime()
    manager = NotificationManager(repository, realtime)

    count = await manager.read_notification(OTHER_ID, NOTIFICATION_ID)

    assert count == 0
    assert repository.rows[NOTIFICATION_ID].is_readed is False
    assert realtime.events[-1] == (
        str(OTHER_ID),
        {"type": "notification_count", "unread_count": 0},
    )


async def test_read_one_and_read_all_publish_absolute_counts_idempotently():
    repository = MemoryNotificationRepository()
    realtime = RecordingRealtime()
    manager = NotificationManager(repository, realtime)

    assert await manager.read_notification(USER_ID, NOTIFICATION_ID) == 0
    assert await manager.read_notification(USER_ID, NOTIFICATION_ID) == 0
    assert await manager.read_all_notifications(USER_ID) == 0

    assert repository.mark_all_calls == 1
    assert [event[1]["unread_count"] for event in realtime.events] == [0, 0, 0]


async def test_create_publishes_count_and_survives_realtime_failure():
    successful_repository = MemoryNotificationRepository()
    successful_realtime = RecordingRealtime()
    successful_manager = NotificationManager(
        successful_repository, successful_realtime
    )
    data = NotificationCreate(
        user_id=str(USER_ID),
        type=NotificationTypes.ORDER_MESSAGE,
        object_id=str(NOTIFICATION_ID),
    )

    assert await successful_manager.create_notification(data) == NOTIFICATION_ID
    assert successful_realtime.events == [
        (
            str(USER_ID),
            {"type": "notification_count", "unread_count": 1},
        )
    ]

    failing_repository = MemoryNotificationRepository()
    failing_manager = NotificationManager(
        failing_repository,
        RecordingRealtime(RuntimeError("redis unavailable")),
    )
    assert await failing_manager.create_notification(data) == NOTIFICATION_ID
    assert await failing_repository.count_unread(USER_ID) == 1


async def test_list_and_count_are_scoped_to_requested_user():
    repository = MemoryNotificationRepository()
    repository.rows[UUID("00000000-0000-0000-0000-000000000011")] = (
        SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000011"),
            user_id=OTHER_ID,
            is_readed=False,
            time_created="2026-08-11T00:01:00Z",
        )
    )
    manager = NotificationManager(repository)

    rows = await manager.get_notifications_by_user(SimpleNamespace(id=USER_ID))

    assert [row.id for row in rows] == [NOTIFICATION_ID]
    assert await manager.unread_count(USER_ID) == 1


async def test_concurrent_count_publications_are_serialized_per_user():
    repository = BlockingCountRepository()
    realtime = SerializedRecordingRealtime()
    manager = NotificationManager(repository, realtime)

    first = asyncio.create_task(manager.notify_count_changed(USER_ID))
    await repository.first_count_started.wait()
    second = asyncio.create_task(manager.notify_count_changed(USER_ID))
    await asyncio.sleep(0)
    repository.release_first_count.set()
    await asyncio.gather(first, second)

    assert [event[1]["unread_count"] for event in realtime.events] == [1, 0]


async def test_read_returns_fresh_count_when_realtime_lock_times_out():
    repository = MemoryNotificationRepository()
    realtime = TimedOutRealtime()
    manager = NotificationManager(repository, realtime)

    count = await manager.read_notification(USER_ID, NOTIFICATION_ID)

    assert count == 0
    assert repository.rows[NOTIFICATION_ID].is_readed is True
    assert realtime.events == []


def test_notification_types_exclude_legacy_support_message():
    assert {item.value for item in NotificationTypes} == {
        "ORDER_MESSAGE",
        "ORDER_UPDATED",
    }


async def test_missing_order_chat_message_notification_is_omitted():
    notification = SimpleNamespace(
        id=NOTIFICATION_ID,
        user_id=USER_ID,
        type=NotificationTypes.ORDER_MESSAGE.value,
        object_id=UUID("00000000-0000-0000-0000-000000000099"),
    )

    class Notifications:
        async def get_notifications_by_user(self, user):
            return [notification]

    class OrderChat:
        async def get_message(self, message_id):
            assert message_id == notification.object_id
            return None

    response = await get_user_notifications(
        user=SimpleNamespace(id=USER_ID),
        notification_manager=Notifications(),
        order_manager=SimpleNamespace(),
        order_chat_repository=OrderChat(),
    )

    assert response == []
