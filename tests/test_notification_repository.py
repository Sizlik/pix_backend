from types import SimpleNamespace
from uuid import UUID

from sqlalchemy.dialects import postgresql

from db.notification_repository import NotificationRepository

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
NOTIFICATION_ID = UUID("00000000-0000-0000-0000-000000000010")
SECOND_ID = UUID("00000000-0000-0000-0000-000000000011")


class FakeResult:
    def __init__(self, scalar=None, items=()):
        self.scalar = scalar
        self.items = list(items)

    def scalar_one(self):
        return self.scalar

    def scalar_one_or_none(self):
        return self.scalar

    def scalars(self):
        return self

    def all(self):
        return self.items

    def __iter__(self):
        return iter(self.items)


class RecordingSession:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    async def commit(self):
        self.commit_count += 1


def compiled(statement):
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


async def test_count_unread_filters_by_user_and_unread_state():
    session = RecordingSession([FakeResult(scalar=3)])
    repository = NotificationRepository(lambda: session)

    assert await repository.count_unread(USER_ID) == 3

    statement = compiled(session.statements[0])
    assert "notifications.user_id" in statement
    assert "notifications.is_readed is false" in statement
    assert str(USER_ID) in statement


async def test_mark_operations_are_user_scoped_and_bulk_read_is_one_update():
    session = RecordingSession(
        [
            FakeResult(scalar=NOTIFICATION_ID),
            FakeResult(items=[NOTIFICATION_ID, SECOND_ID]),
        ]
    )
    repository = NotificationRepository(lambda: session)

    assert await repository.mark_read(NOTIFICATION_ID, USER_ID) is True
    assert await repository.mark_all_read(USER_ID) == 2

    mark_one = compiled(session.statements[0])
    mark_all = compiled(session.statements[1])
    assert "notifications.id" in mark_one
    assert "notifications.user_id" in mark_one
    assert "notifications.is_readed is false" in mark_one
    assert "notifications.user_id" in mark_all
    assert "notifications.is_readed is false" in mark_all
    assert session.commit_count == 2


async def test_create_and_list_keep_existing_notification_contract():
    rows = [
        SimpleNamespace(id=NOTIFICATION_ID),
        SimpleNamespace(id=SECOND_ID),
    ]
    session = RecordingSession(
        [FakeResult(scalar=NOTIFICATION_ID), FakeResult(items=rows)]
    )
    repository = NotificationRepository(lambda: session)

    created = await repository.create(
        user_id=USER_ID,
        type="MESSAGE",
        object_id=SECOND_ID,
    )
    listed = await repository.list_for_user(USER_ID)

    assert created == NOTIFICATION_ID
    assert listed == rows
    assert session.commit_count == 1
    list_statement = compiled(session.statements[1])
    assert "notifications.user_id" in list_statement
    assert "notifications.time_created desc" in list_statement
