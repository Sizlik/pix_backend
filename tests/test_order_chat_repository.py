from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from db.models.notifications import Notifications
from db.order_chat_repository import NewAttachment, OrderChatRepository, object_key


def test_object_key_never_contains_client_filename():
    order_id = UUID("00000000-0000-0000-0000-000000000001")
    message_id = UUID("00000000-0000-0000-0000-000000000002")
    attachment_id = UUID("00000000-0000-0000-0000-000000000003")

    assert object_key(order_id, message_id, attachment_id) == (
        "orders/00000000-0000-0000-0000-000000000001/"
        "messages/00000000-0000-0000-0000-000000000002/"
        "attachments/00000000-0000-0000-0000-000000000003"
    )


class TransactionSpySession:
    def __init__(self):
        self.begin_count = 0
        self.in_transaction = False
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    @asynccontextmanager
    async def begin(self):
        self.begin_count += 1
        self.in_transaction = True
        try:
            yield
        finally:
            self.in_transaction = False

    def add(self, model):
        assert self.in_transaction
        self.added.append(model)

    async def execute(self, statement):
        assert self.in_transaction
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    async def flush(self):
        assert self.in_transaction


class TransactionSpyRepository(OrderChatRepository):
    def __init__(self, session):
        super().__init__(session_factory=lambda: session)
        self.actions = []

    async def _insert_message(self, session, **values):
        assert session.in_transaction
        self.actions.append(("message", values))
        return (
            SimpleNamespace(
                id=values["message_id"],
                order_id=values["order_id"],
                client_id=values["client_id"],
                sender_kind=values["sender_kind"],
                source=values["source"],
                body=values["body"],
                created_at=datetime.now(timezone.utc),
                external_key=values["external_key"],
            ),
            True,
        )

    async def _insert_attachments(self, session, message_id, attachments):
        assert session.in_transaction
        self.actions.append(("attachments", attachments))
        return tuple(
            SimpleNamespace(
                id=item.id,
                original_filename=item.original_filename,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
            )
            for item in attachments
        )

async def test_manager_message_and_notification_share_one_transaction():
    session = TransactionSpySession()
    repository = TransactionSpyRepository(session)
    order_id = UUID(int=1)
    message_id = UUID(int=2)
    client_id = UUID(int=3)
    attachment = NewAttachment(
        id=UUID(int=4),
        object_key="orders/1/messages/2/attachments/4",
        original_filename="note.txt",
        mime_type="text/plain",
        size_bytes=5,
        sha256="0" * 64,
        origin="extension",
    )

    result = await repository.create_manager_message_with_notification(
        message_id=message_id,
        order_id=order_id,
        client_id=client_id,
        body="Готово",
        source="extension",
        external_key=None,
        attachments=(attachment,),
    )

    assert result.id == message_id
    assert session.begin_count == 1
    assert [action for action, _ in repository.actions] == [
        "message",
        "attachments",
    ]
    assert len(session.added) == 1
    notification = session.added[0]
    assert isinstance(notification, Notifications)
    assert notification.user_id == client_id
    assert notification.type == "ORDER_MESSAGE"
    assert notification.object_id == message_id


async def test_ensure_state_does_not_create_projection_outbox_event():
    session = TransactionSpySession()
    repository = TransactionSpyRepository(session)

    state = await repository.ensure_state(UUID(int=10), UUID(int=11))

    assert state.order_id == UUID(int=10)
    assert session.begin_count == 1
    assert repository.actions == []


class UserQuerySession:
    def __init__(self, users):
        self.users = users
        self.statement = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(scalars=lambda: iter(self.users))


@pytest.mark.parametrize(
    ("users", "expected"),
    [
        ([], None),
        ([SimpleNamespace(id=UUID(int=20))], UUID(int=20)),
        ([SimpleNamespace(id=UUID(int=20)), SimpleNamespace(id=UUID(int=21))], None),
    ],
)
async def test_moysklad_counterparty_link_requires_exactly_one_user(users, expected):
    session = UserQuerySession(users)
    repository = OrderChatRepository(session_factory=lambda: session)

    result = await repository.get_user_by_moysklad_counterparty(UUID(int=22))

    assert getattr(result, "id", None) == expected
    assert session.statement._limit_clause.value == 2
