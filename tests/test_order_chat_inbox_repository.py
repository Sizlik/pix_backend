from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

import db.order_chat_repository as repository_module
from db.order_chat_repository import OrderChatNotFound, OrderChatRepository

ORDER_ONE = UUID("00000000-0000-0000-0000-000000000001")
ORDER_TWO = UUID("00000000-0000-0000-0000-000000000002")
ORDER_THREE = UUID("00000000-0000-0000-0000-000000000003")
MESSAGE_ONE = UUID("10000000-0000-0000-0000-000000000001")
MESSAGE_TWO = UUID("10000000-0000-0000-0000-000000000002")
MESSAGE_THREE = UUID("10000000-0000-0000-0000-000000000003")
CLIENT_ID = UUID("20000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)


class Result:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = [] if rows is None else rows

    def scalar_one_or_none(self):
        return self.scalar

    def scalar_one(self):
        return self.scalar

    def all(self):
        return self.rows


class InboxSession:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []
        self.begin_count = 0
        self.in_transaction = False

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
        self.statements.append(statement)
        return self.results.pop(0)


def state(order_id, message_id, *, name, unread):
    return SimpleNamespace(
        order_id=order_id,
        client_id=CLIENT_ID,
        order_name=name,
        latest_message_id=message_id,
        operator_unread_count=unread,
        updated_at=NOW,
    )


def message(message_id, order_id, created_at, *, body="Текст"):
    return SimpleNamespace(
        id=message_id,
        order_id=order_id,
        client_id=CLIENT_ID,
        sender_kind="client",
        source="site",
        body=body,
        created_at=created_at,
        external_key=None,
    )


def compiled(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


async def test_list_conversations_returns_newest_page_and_latest_message_cursor():
    rows = [
        (
            state(ORDER_ONE, MESSAGE_ONE, name="10001", unread=2),
            message(MESSAGE_ONE, ORDER_ONE, NOW),
            3,
        ),
        (
            state(ORDER_TWO, MESSAGE_TWO, name=None, unread=0),
            message(MESSAGE_TWO, ORDER_TWO, NOW - timedelta(minutes=1)),
            0,
        ),
        (
            state(ORDER_THREE, MESSAGE_THREE, name="10003", unread=1),
            message(MESSAGE_THREE, ORDER_THREE, NOW - timedelta(minutes=2)),
            1,
        ),
    ]
    session = InboxSession(Result(rows=rows))
    repository = OrderChatRepository(session_factory=lambda: session)

    items, next_before = await repository.list_conversations(None, 2)

    assert [item.order_id for item in items] == [ORDER_ONE, ORDER_TWO]
    assert items[0].order_name == "10001"
    assert items[0].attachment_count == 3
    assert items[0].last_message.id == MESSAGE_ONE
    assert items[0].unread_count == 2
    assert next_before == MESSAGE_TWO
    statement = session.statements[0]
    sql = compiled(statement)
    assert "JOIN order_chat_message ON order_chat_state.latest_message_id = order_chat_message.id" in sql
    assert "ORDER BY order_chat_message.created_at DESC, order_chat_message.id DESC" in sql
    assert statement._limit_clause.value == 3


async def test_list_conversations_applies_a_valid_latest_message_cursor():
    cursor = message(MESSAGE_ONE, ORDER_ONE, NOW)
    session = InboxSession(Result(scalar=cursor), Result(rows=[]))
    repository = OrderChatRepository(session_factory=lambda: session)

    items, next_before = await repository.list_conversations(MESSAGE_ONE, 50)

    assert items == []
    assert next_before is None
    cursor_sql = compiled(session.statements[0])
    page_sql = compiled(session.statements[1])
    assert "order_chat_state.latest_message_id" in cursor_sql
    assert "order_chat_message.created_at <" in page_sql
    assert "order_chat_message.id <" in page_sql


async def test_list_conversations_rejects_a_cursor_that_is_not_a_latest_message():
    session = InboxSession(Result(scalar=None))
    repository = OrderChatRepository(session_factory=lambda: session)

    with pytest.raises(OrderChatNotFound):
        await repository.list_conversations(MESSAGE_ONE, 50)


async def test_total_operator_unread_returns_zero_or_database_sum():
    empty_session = InboxSession(Result(scalar=0))
    populated_session = InboxSession(Result(scalar=7))

    assert await OrderChatRepository(
        session_factory=lambda: empty_session
    ).total_operator_unread() == 0
    assert await OrderChatRepository(
        session_factory=lambda: populated_session
    ).total_operator_unread() == 7


async def test_clear_operator_unread_is_idempotent_and_returns_new_global_total():
    locked_state = state(ORDER_ONE, MESSAGE_ONE, name="10001", unread=4)
    session = InboxSession(Result(scalar=locked_state), Result(scalar=6))
    repository = OrderChatRepository(session_factory=lambda: session)

    total = await repository.clear_operator_unread(ORDER_ONE)

    assert total == 6
    assert locked_state.operator_unread_count == 0
    assert session.begin_count == 1
    assert "FOR UPDATE" in compiled(session.statements[0])


async def test_clear_operator_unread_rejects_a_missing_or_empty_conversation():
    session = InboxSession(Result(scalar=None))
    repository = OrderChatRepository(session_factory=lambda: session)

    with pytest.raises(OrderChatNotFound):
        await repository.clear_operator_unread(ORDER_ONE)


async def test_cache_order_name_updates_only_the_requested_state():
    session = InboxSession(Result())
    repository = OrderChatRepository(session_factory=lambda: session)

    await repository.cache_order_name(ORDER_ONE, " 10001 ")

    statement = session.statements[0]
    params = statement.compile().params
    assert params["order_name"] == "10001"
    assert ORDER_ONE in params.values()
    assert session.begin_count == 1


async def test_conversation_returns_one_projection_or_none():
    row = (
        state(ORDER_ONE, MESSAGE_ONE, name="10001", unread=2),
        message(MESSAGE_ONE, ORDER_ONE, NOW),
        1,
    )
    found_session = InboxSession(Result(rows=[row]))
    missing_session = InboxSession(Result(rows=[]))

    found = await OrderChatRepository(
        session_factory=lambda: found_session
    ).conversation(ORDER_ONE)
    missing = await OrderChatRepository(
        session_factory=lambda: missing_session
    ).conversation(ORDER_TWO)

    assert found is not None
    assert found.order_name == "10001"
    assert found.attachment_count == 1
    assert missing is None


def test_stored_conversation_contract_is_available_to_service_layer():
    assert hasattr(repository_module, "StoredConversation")
