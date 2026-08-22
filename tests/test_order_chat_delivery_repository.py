from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

import db.order_chat_repository as repository_module
from db.models.notifications import Notifications
from db.models.order_chat import OrderChatEmailOutbox
from db.order_chat_repository import (
    NewAttachment,
    OrderChatNotFound,
    OrderChatRepository,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000002")
CLIENT_ID = UUID("00000000-0000-0000-0000-000000000003")
NEWER_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000099")


class DeliverySession:
    def __init__(self, state, *, latest_created_at=None):
        self.state = state
        self.latest_created_at = latest_created_at
        self.added = []
        self.begin_count = 0
        self.in_transaction = False
        self.execute_count = 0

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

    async def execute(self, statement):
        assert self.in_transaction
        self.execute_count += 1
        if self.execute_count > 1:
            row = (
                (self.latest_created_at, self.state.latest_message_id)
                if self.latest_created_at is not None
                else None
            )
            return SimpleNamespace(one_or_none=lambda: row)
        return SimpleNamespace(scalar_one_or_none=lambda: self.state)

    def add(self, model):
        assert self.in_transaction
        self.added.append(model)


class DeliveryRepository(OrderChatRepository):
    def __init__(self, session, *, inserted: bool = True):
        super().__init__(session_factory=lambda: session)
        self.inserted = inserted
        self.actions = []

    async def _insert_message(self, session, **values):
        assert session.in_transaction
        self.actions.append("message")
        return (
            SimpleNamespace(
                id=values["message_id"],
                order_id=values["order_id"],
                client_id=values["client_id"],
                sender_kind=values["sender_kind"],
                source=values["source"],
                body=values["body"],
                created_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
                external_key=values["external_key"],
            ),
            self.inserted,
        )

    async def _insert_attachments(self, session, message_id, attachments):
        assert session.in_transaction
        self.actions.append("attachments")
        return tuple(
            SimpleNamespace(
                id=item.id,
                original_filename=item.original_filename,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
            )
            for item in attachments
        )

    async def _load_attachments(self, session, message_id):
        self.actions.append("load_attachments")
        return ()


def chat_state(*, client_id=CLIENT_ID, unread=0, latest_message_id=None):
    return SimpleNamespace(
        order_id=ORDER_ID,
        client_id=client_id,
        order_name=None,
        latest_message_id=latest_message_id,
        operator_unread_count=unread,
        updated_at=None,
    )


def attachment() -> NewAttachment:
    return NewAttachment(
        id=UUID("00000000-0000-0000-0000-000000000004"),
        object_key=f"orders/{ORDER_ID}/messages/{MESSAGE_ID}/attachments/4",
        original_filename="invoice.pdf",
        mime_type="application/pdf",
        size_bytes=100,
        sha256="0" * 64,
        origin="site",
    )


def email_delivery(recipient_email: str, recipient_kind: str):
    assert hasattr(repository_module, "NewEmailDelivery")
    return repository_module.NewEmailDelivery(recipient_email, recipient_kind)


async def test_client_delivery_updates_projection_unread_and_manager_outbox_atomically():
    state = chat_state(unread=1)
    session = DeliverySession(state)
    repository = DeliveryRepository(session)

    result = await repository.create_client_message_with_delivery(
        message_id=MESSAGE_ID,
        order_id=ORDER_ID,
        client_id=CLIENT_ID,
        body="Проверьте документ",
        source="site",
        order_name="12345",
        email_delivery=email_delivery("manager@example.com", "manager"),
        attachments=(attachment(),),
    )

    assert result.id == MESSAGE_ID
    assert session.begin_count == 1
    assert repository.actions == ["message", "attachments"]
    assert state.latest_message_id == MESSAGE_ID
    assert state.order_name == "12345"
    assert state.operator_unread_count == 2
    assert len(session.added) == 1
    outbox = session.added[0]
    assert isinstance(outbox, OrderChatEmailOutbox)
    assert outbox.message_id == MESSAGE_ID
    assert outbox.recipient_email == "manager@example.com"
    assert outbox.recipient_kind == "manager"


async def test_manager_delivery_adds_customer_notification_without_incrementing_operator_unread():
    state = chat_state(unread=3)
    session = DeliverySession(state)
    repository = DeliveryRepository(session)

    await repository.create_manager_message_with_notification(
        message_id=MESSAGE_ID,
        order_id=ORDER_ID,
        client_id=CLIENT_ID,
        body="Готово",
        source="extension",
        order_name="12345",
        email_delivery=email_delivery("client@example.com", "client"),
    )

    assert state.latest_message_id == MESSAGE_ID
    assert state.order_name == "12345"
    assert state.operator_unread_count == 3
    assert len(session.added) == 2
    notification = next(item for item in session.added if isinstance(item, Notifications))
    outbox = next(item for item in session.added if isinstance(item, OrderChatEmailOutbox))
    assert notification.user_id == CLIENT_ID
    assert notification.type == "ORDER_MESSAGE"
    assert notification.object_id == MESSAGE_ID
    assert outbox.recipient_email == "client@example.com"
    assert outbox.recipient_kind == "client"


@pytest.mark.parametrize("sender_kind", ["client", "manager"])
async def test_duplicate_message_replay_does_not_repeat_delivery_side_effects(sender_kind):
    state = chat_state(unread=4)
    session = DeliverySession(state)
    repository = DeliveryRepository(session, inserted=False)
    common = dict(
        message_id=MESSAGE_ID,
        order_id=ORDER_ID,
        client_id=CLIENT_ID,
        body="Повтор",
        source="extension" if sender_kind == "manager" else "site",
        order_name="12345",
        email_delivery=email_delivery(
            "client@example.com" if sender_kind == "manager" else "manager@example.com",
            "client" if sender_kind == "manager" else "manager",
        ),
    )

    if sender_kind == "manager":
        await repository.create_manager_message_with_notification(**common)
    else:
        await repository.create_client_message_with_delivery(**common)

    assert repository.actions == ["message", "load_attachments"]
    assert state.latest_message_id is None
    assert state.operator_unread_count == 4
    assert session.added == []


async def test_state_client_mismatch_aborts_before_any_delivery_side_effect():
    state = chat_state(client_id=UUID(int=99), unread=2)
    session = DeliverySession(state)
    repository = DeliveryRepository(session)

    with pytest.raises(OrderChatNotFound):
        await repository.create_client_message_with_delivery(
            message_id=MESSAGE_ID,
            order_id=ORDER_ID,
            client_id=CLIENT_ID,
            body="Проверка",
            source="site",
            order_name="12345",
            email_delivery=email_delivery("manager@example.com", "manager"),
        )

    assert state.latest_message_id is None
    assert state.operator_unread_count == 2
    assert session.added == []


async def test_disabled_email_still_commits_manager_notification_and_projection():
    state = chat_state()
    session = DeliverySession(state)
    repository = DeliveryRepository(session)

    await repository.create_manager_message_with_notification(
        message_id=MESSAGE_ID,
        order_id=ORDER_ID,
        client_id=CLIENT_ID,
        body="Без письма",
        source="extension",
        order_name="12345",
        email_delivery=None,
    )

    assert state.latest_message_id == MESSAGE_ID
    assert [type(item) for item in session.added] == [Notifications]


async def test_late_older_message_cannot_move_latest_projection_backwards():
    state = chat_state(
        unread=2,
        latest_message_id=NEWER_MESSAGE_ID,
    )
    session = DeliverySession(
        state,
        latest_created_at=datetime(2026, 8, 22, 13, tzinfo=UTC),
    )
    repository = DeliveryRepository(session)

    await repository.create_client_message_with_delivery(
        message_id=MESSAGE_ID,
        order_id=ORDER_ID,
        client_id=CLIENT_ID,
        body="Запоздавшее сообщение",
        source="site",
    )

    assert state.latest_message_id == NEWER_MESSAGE_ID
    assert state.operator_unread_count == 3
