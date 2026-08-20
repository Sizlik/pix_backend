import re
import runpy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine


MIGRATION = Path("alembic/versions/d4e5f6a7b8c9_remove_telegram.py")
CLIENT_ID = UUID("00000000-0000-0000-0000-000000000101")
MANAGER_ID = UUID("00000000-0000-0000-0000-000000000102")
ORDER_ONE = UUID("00000000-0000-0000-0000-000000000201")
ORDER_TWO = UUID("00000000-0000-0000-0000-000000000202")
ORDER_THREE = UUID("00000000-0000-0000-0000-000000000203")
ROOM_ONE = UUID("00000000-0000-0000-0000-000000000301")
ROOM_TWO = UUID("00000000-0000-0000-0000-000000000302")
ROOM_THREE = UUID("00000000-0000-0000-0000-000000000303")
SUPPORT_ROOM = UUID("00000000-0000-0000-0000-000000000304")
MESSAGE_ONE = UUID("00000000-0000-0000-0000-000000000401")
MESSAGE_TWO = UUID("00000000-0000-0000-0000-000000000402")
MESSAGE_THREE = UUID("00000000-0000-0000-0000-000000000403")
SUPPORT_MESSAGE = UUID("00000000-0000-0000-0000-000000000404")
CREATED_ONE = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
CREATED_TWO = datetime(2026, 8, 1, 11, 0, tzinfo=timezone.utc)
CREATED_THREE = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def test_remove_telegram_revision_chain_and_destructive_order():
    module = runpy.run_path(str(MIGRATION))
    source = MIGRATION.read_text(encoding="utf-8")

    assert module["revision"] == "d4e5f6a7b8c9"
    assert module["down_revision"] == "b7e1d3a9f4c2"
    assert source.index("CREATE TEMP TABLE") < source.index(
        'op.drop_table("message")'
    )
    assert source.index("legacy_message_id") < source.index(
        'op.drop_table("message")'
    )
    assert source.index("ORDER_MESSAGE") < source.index(
        'op.drop_table("message")'
    )
    assert source.index("telegram_projection_error") < source.index(
        'op.drop_table("message")'
    )
    assert "bot@pixlogistic.com" in source
    assert 'op.delete("user")' not in source


def test_downgrade_recreates_legacy_schema_in_dependency_order():
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade") :]

    assert downgrade.index('op.create_table(\n        "chat_room"') < downgrade.index(
        'op.create_table(\n        "message"'
    )
    assert downgrade.index('op.add_column(\n        "user"') < downgrade.index(
        'op.create_table(\n        "chat_room"'
    )
    assert 'sa.Column("telegram_id", sa.Integer(), nullable=True)' in downgrade


def _validated_schema_name() -> str:
    schema = f"remove_telegram_test_{uuid4().hex}"
    assert re.fullmatch(r"remove_telegram_test_[0-9a-f]{32}", schema)
    return schema


async def _execute_all(connection, statements):
    for statement in statements:
        await connection.execute(sa.text(statement))


async def _create_schema(connection, schema: str) -> None:
    await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    await connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
    await _execute_all(
        connection,
        (
            'CREATE TABLE "user" (id uuid PRIMARY KEY, email text NOT NULL, telegram_id integer)',
            "CREATE TABLE chat_room (id uuid PRIMARY KEY, members json, client_id uuid, order_id uuid)",
            "CREATE TABLE message (id uuid PRIMARY KEY, message text NOT NULL, time_created timestamptz, time_updated timestamptz, from_user_id uuid, to_chat_room_id uuid)",
            "CREATE TABLE notifications (id uuid PRIMARY KEY, user_id uuid, is_readed boolean, type text, object_id uuid, time_created timestamptz)",
            "CREATE TABLE order_chat_message (id uuid PRIMARY KEY, order_id uuid NOT NULL, client_id uuid NOT NULL, sender_kind varchar(16) NOT NULL, source varchar(16) NOT NULL, body text NOT NULL, external_key varchar(255) UNIQUE, legacy_message_id uuid UNIQUE, created_at timestamptz NOT NULL DEFAULT now())",
            "CREATE TABLE chat_outbox_event (id uuid PRIMARY KEY, event_type varchar(64) NOT NULL, order_id uuid NOT NULL, dedup_key varchar(255) UNIQUE NOT NULL, payload json NOT NULL)",
        ),
    )
    await connection.execute(
        sa.text('INSERT INTO "user" (id, email, telegram_id) VALUES (:client, :client_email, 1001), (:manager, :manager_email, 1002)'),
        {
            "client": CLIENT_ID,
            "client_email": "client@example.test",
            "manager": MANAGER_ID,
            "manager_email": "bot@pixlogistic.com",
        },
    )


async def _set_schema(connection, schema: str) -> None:
    await connection.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))


def _run_upgrade(sync_connection) -> None:
    module = runpy.run_path(str(MIGRATION))
    operations = Operations(MigrationContext.configure(sync_connection))
    module["upgrade"].__globals__["op"] = operations
    module["upgrade"]()


async def _scalar(connection, query: str):
    return await connection.scalar(sa.text(query))


async def _table_exists(connection, name: str) -> bool:
    return bool(
        await connection.scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :name)"
            ),
            {"name": name},
        )
    )


async def _column_exists(connection, table: str, column: str) -> bool:
    return bool(
        await connection.scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :table "
                "AND column_name = :column)"
            ),
            {"table": table, "column": column},
        )
    )


async def _drop_schema(engine, schema: str) -> None:
    if not re.fullmatch(r"remove_telegram_test_[0-9a-f]{32}", schema):
        raise AssertionError("refusing to drop an unexpected schema")
    async with engine.begin() as connection:
        await connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))


async def _seed_success(connection) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO chat_room (id, client_id, order_id) VALUES "
            "(:room_one, :client, :order_one), (:room_two, :client, :order_two), "
            "(:room_three, :client, :order_three), (:support_room, :client, NULL)"
        ),
        {
            "room_one": ROOM_ONE,
            "room_two": ROOM_TWO,
            "room_three": ROOM_THREE,
            "support_room": SUPPORT_ROOM,
            "client": CLIENT_ID,
            "order_one": ORDER_ONE,
            "order_two": ORDER_TWO,
            "order_three": ORDER_THREE,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO message (id, message, time_created, from_user_id, to_chat_room_id) VALUES "
            "(:message_one, 'client one', :created_one, :client, :room_one), "
            "(:message_two, 'manager two', :created_two, :manager, :order_two), "
            "(:message_three, 'client three', :created_three, :client, :room_three), "
            "(:support_message, 'support only', now(), :client, :support_room)"
        ),
        {
            "message_one": MESSAGE_ONE,
            "message_two": MESSAGE_TWO,
            "message_three": MESSAGE_THREE,
            "support_message": SUPPORT_MESSAGE,
            "created_one": CREATED_ONE,
            "created_two": CREATED_TWO,
            "created_three": CREATED_THREE,
            "client": CLIENT_ID,
            "manager": MANAGER_ID,
            "room_one": ROOM_ONE,
            "order_two": ORDER_TWO,
            "room_three": ROOM_THREE,
            "support_room": SUPPORT_ROOM,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO order_chat_message (id, order_id, client_id, sender_kind, source, body, legacy_message_id, created_at) "
            "VALUES (:id, :order_id, :client_id, 'client', 'legacy', 'client three', :legacy_id, :created_at)"
        ),
        {
            "id": UUID("00000000-0000-0000-0000-000000000501"),
            "order_id": ORDER_THREE,
            "client_id": CLIENT_ID,
            "legacy_id": MESSAGE_THREE,
            "created_at": CREATED_THREE,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO notifications (id, user_id, type, object_id) VALUES "
            "(:one, :client, 'ORDER_MESSAGE', :message_one), "
            "(:two, :client, 'ORDER_MESSAGE', :message_two), "
            "(:support, :client, 'MESSAGE', :support_message)"
        ),
        {
            "one": UUID("00000000-0000-0000-0000-000000000601"),
            "two": UUID("00000000-0000-0000-0000-000000000602"),
            "support": UUID("00000000-0000-0000-0000-000000000603"),
            "client": CLIENT_ID,
            "message_one": MESSAGE_ONE,
            "message_two": MESSAGE_TWO,
            "support_message": SUPPORT_MESSAGE,
        },
    )
    for index, event_type in enumerate(
        (
            "telegram_client_alert",
            "telegram_manager_alert",
            "telegram_projection_error",
            "sync_order",
        ),
        start=1,
    ):
        await connection.execute(
            sa.text(
                "INSERT INTO chat_outbox_event (id, event_type, order_id, dedup_key, payload) "
                "VALUES (:id, :event_type, :order_id, :dedup_key, CAST('{}' AS json))"
            ),
            {
                "id": UUID(f"00000000-0000-0000-0000-{700 + index:012d}"),
                "event_type": event_type,
                "order_id": ORDER_ONE,
                "dedup_key": f"event-{index}",
            },
        )


async def test_upgrade_backfills_order_history_and_removes_only_obsolete_data(
    migration_database_url,
):
    engine = create_async_engine(migration_database_url)
    schema = _validated_schema_name()
    try:
        async with engine.begin() as connection:
            await _create_schema(connection, schema)
            await _seed_success(connection)

        async with engine.begin() as connection:
            await _set_schema(connection, schema)
            await connection.run_sync(_run_upgrade)

        async with engine.begin() as connection:
            await _set_schema(connection, schema)
            assert await _scalar(connection, "SELECT count(*) FROM order_chat_message") == 3
            assert await _scalar(
                connection,
                "SELECT count(*) FROM order_chat_message WHERE source = 'legacy'",
            ) == 3
            assert await _scalar(
                connection,
                "SELECT count(*) FROM notifications WHERE type = 'ORDER_MESSAGE'",
            ) == 2
            assert await _scalar(
                connection,
                "SELECT count(*) FROM notifications WHERE type = 'MESSAGE'",
            ) == 0
            assert await _scalar(connection, "SELECT count(*) FROM chat_outbox_event") == 1
            assert await _scalar(
                connection,
                "SELECT count(*) FROM chat_outbox_event WHERE event_type = 'sync_order'",
            ) == 1
            assert await _scalar(
                connection,
                "SELECT count(*) FROM notifications AS n JOIN order_chat_message AS m ON m.id = n.object_id WHERE n.type = 'ORDER_MESSAGE'",
            ) == 2
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT legacy_message_id, created_at FROM order_chat_message "
                        "ORDER BY legacy_message_id"
                    )
                )
            ).all()
            assert rows == [
                (MESSAGE_ONE, CREATED_ONE),
                (MESSAGE_TWO, CREATED_TWO),
                (MESSAGE_THREE, CREATED_THREE),
            ]
            assert not await _table_exists(connection, "message")
            assert not await _table_exists(connection, "chat_room")
            assert not await _column_exists(connection, "user", "telegram_id")
    finally:
        await _drop_schema(engine, schema)
        await engine.dispose()


async def _assert_failed_upgrade_preserves_source_data(
    migration_database_url,
    seed,
    expected_error: str,
):
    engine = create_async_engine(migration_database_url)
    schema = _validated_schema_name()
    try:
        async with engine.begin() as connection:
            await _create_schema(connection, schema)
            await seed(connection)

        with pytest.raises(Exception, match=expected_error):
            async with engine.begin() as connection:
                await _set_schema(connection, schema)
                await connection.run_sync(_run_upgrade)

        async with engine.begin() as connection:
            await _set_schema(connection, schema)
            assert await _table_exists(connection, "message")
            assert await _table_exists(connection, "chat_room")
            assert await _column_exists(connection, "user", "telegram_id")
            assert await _scalar(connection, "SELECT count(*) FROM message") > 0
    finally:
        await _drop_schema(engine, schema)
        await engine.dispose()


async def _seed_ambiguous(connection) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO chat_room (id, client_id, order_id) VALUES "
            "(:one, :client, :order_id), (:two, :client, :order_id)"
        ),
        {"one": ROOM_ONE, "two": ROOM_TWO, "client": CLIENT_ID, "order_id": ORDER_ONE},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO message (id, message, from_user_id, to_chat_room_id) "
            "VALUES (:id, 'ambiguous', :client, :order_id)"
        ),
        {"id": MESSAGE_ONE, "client": CLIENT_ID, "order_id": ORDER_ONE},
    )


async def test_upgrade_rejects_ambiguous_order_mapping(migration_database_url):
    await _assert_failed_upgrade_preserves_source_data(
        migration_database_url,
        _seed_ambiguous,
        "legacy order message mapping is ambiguous",
    )


async def _seed_missing_client(connection) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO chat_room (id, client_id, order_id) VALUES (:room, NULL, :order_id)"
        ),
        {"room": ROOM_ONE, "order_id": ORDER_ONE},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO message (id, message, from_user_id, to_chat_room_id) "
            "VALUES (:id, 'missing client', :manager, :room)"
        ),
        {"id": MESSAGE_ONE, "manager": MANAGER_ID, "room": ROOM_ONE},
    )


async def test_upgrade_rejects_order_message_without_client(migration_database_url):
    await _assert_failed_upgrade_preserves_source_data(
        migration_database_url,
        _seed_missing_client,
        "legacy order message has no client",
    )


async def _seed_unmapped_notification(connection) -> None:
    await connection.execute(
        sa.text(
            "INSERT INTO chat_room (id, client_id, order_id) VALUES (:room, :client, NULL)"
        ),
        {"room": SUPPORT_ROOM, "client": CLIENT_ID},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO message (id, message, from_user_id, to_chat_room_id) "
            "VALUES (:id, 'support only', :client, :room)"
        ),
        {"id": SUPPORT_MESSAGE, "client": CLIENT_ID, "room": SUPPORT_ROOM},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO notifications (id, user_id, type, object_id) "
            "VALUES (:id, :client, 'ORDER_MESSAGE', :message_id)"
        ),
        {
            "id": UUID("00000000-0000-0000-0000-000000000601"),
            "client": CLIENT_ID,
            "message_id": SUPPORT_MESSAGE,
        },
    )


async def test_upgrade_rejects_unmapped_order_message_notification(
    migration_database_url,
):
    await _assert_failed_upgrade_preserves_source_data(
        migration_database_url,
        _seed_unmapped_notification,
        "ORDER_MESSAGE notification has no order mapping",
    )
