import importlib.util
from pathlib import Path

from db.models.order_chat import OrderChatAttachment, OrderChatMessage
from db.schemas.chat import AttachmentOrigin, MessageSource

MIGRATION = Path(
    "alembic/versions/e3b7c9d1a204_allow_extension_chat_source.py"
)


def test_extension_source_is_declared_in_models_and_schema():
    assert MessageSource.EXTENSION.value == "extension"
    assert AttachmentOrigin.EXTENSION.value == "extension"
    message_constraints = " ".join(
        str(item.sqltext)
        for item in OrderChatMessage.__table__.constraints
        if hasattr(item, "sqltext")
    )
    attachment_constraints = " ".join(
        str(item.sqltext)
        for item in OrderChatAttachment.__table__.constraints
        if hasattr(item, "sqltext")
    )
    assert "'extension'" in message_constraints
    assert "'extension'" in attachment_constraints


def test_additive_revision_replaces_only_source_constraints():
    assert MIGRATION.exists(), "additive extension migration is missing"
    spec = importlib.util.spec_from_file_location("extension_chat_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    operations: list[tuple] = []

    class Recorder:
        def drop_constraint(self, name, table_name, *, type_):
            operations.append(("drop", name, table_name, type_))

        def create_check_constraint(self, name, table_name, condition):
            operations.append(("create", name, table_name, condition))

    migration.op = Recorder()
    migration.upgrade()

    assert migration.down_revision == "d4e5f6a7b8c9"
    assert operations == [
        ("drop", "ck_order_chat_source", "order_chat_message", "check"),
        (
            "create",
            "ck_order_chat_source",
            "order_chat_message",
            "source IN ('site', 'moysklad', 'legacy', 'extension')",
        ),
        (
            "drop",
            "ck_order_chat_attachment_origin",
            "order_chat_attachment",
            "check",
        ),
        (
            "create",
            "ck_order_chat_attachment_origin",
            "order_chat_attachment",
            "origin IN ('site', 'moysklad', 'extension')",
        ),
    ]
