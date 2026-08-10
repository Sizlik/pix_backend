import runpy
from pathlib import Path

from db.models.order_chat import (
    ChatOutboxEvent,
    MoySkladOrderFile,
    OrderChatAttachment,
    OrderChatMessage,
    OrderChatState,
)


def test_order_chat_tables_and_unique_idempotency_keys_are_declared():
    assert OrderChatMessage.__tablename__ == "order_chat_message"
    assert OrderChatAttachment.__tablename__ == "order_chat_attachment"
    assert OrderChatState.__tablename__ == "order_chat_state"
    assert MoySkladOrderFile.__tablename__ == "moysklad_order_file"
    assert ChatOutboxEvent.__tablename__ == "chat_outbox_event"
    assert OrderChatMessage.__table__.c.external_key.unique is True
    assert OrderChatMessage.__table__.c.legacy_message_id.unique is True
    assert ChatOutboxEvent.__table__.c.dedup_key.unique is True


def test_migration_is_append_only_and_does_not_run_data_changes():
    migration_path = Path("alembic/versions/c8f2a4e6d901_order_chat_delivery.py")
    migration = migration_path.read_text(encoding="utf-8")
    migration_module = runpy.run_path(str(migration_path))

    assert migration_module["down_revision"] == "107b04f2194b"
    assert "reject_order_chat_mutation" in migration
    assert "BEFORE UPDATE OR DELETE ON order_chat_message" in migration
    assert "BEFORE UPDATE OR DELETE ON order_chat_attachment" in migration
    assert 'op.execute("UPDATE message' not in migration
    assert 'op.execute("DELETE FROM message' not in migration
