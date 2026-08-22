import runpy
from pathlib import Path

import sqlalchemy as sa

MIGRATION = Path(
    "alembic/versions/f4c8a2d6b901_order_chat_inbox_email.py"
)


class OperationRecorder:
    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def add_column(self, *args, **kwargs):
        self._record("add_column", *args, **kwargs)

    def create_check_constraint(self, *args, **kwargs):
        self._record("create_check_constraint", *args, **kwargs)

    def create_foreign_key(self, *args, **kwargs):
        self._record("create_foreign_key", *args, **kwargs)

    def create_index(self, *args, **kwargs):
        self._record("create_index", *args, **kwargs)

    def create_table(self, *args, **kwargs):
        self._record("create_table", *args, **kwargs)

    def drop_constraint(self, *args, **kwargs):
        self._record("drop_constraint", *args, **kwargs)

    def drop_column(self, *args, **kwargs):
        self._record("drop_column", *args, **kwargs)

    def drop_index(self, *args, **kwargs):
        self._record("drop_index", *args, **kwargs)

    def drop_table(self, *args, **kwargs):
        self._record("drop_table", *args, **kwargs)

    def execute(self, *args, **kwargs):
        self._record("execute", *args, **kwargs)


def load_migration():
    assert MIGRATION.exists(), f"missing migration {MIGRATION}"
    return runpy.run_path(str(MIGRATION))


def run_operation(name: str) -> OperationRecorder:
    module = load_migration()
    recorder = OperationRecorder()
    operation = module[name]
    operation.__globals__["op"] = recorder
    operation()
    return recorder


def test_revision_extends_the_current_single_head():
    module = load_migration()

    assert module["revision"] == "f4c8a2d6b901"
    assert module["down_revision"] == "e3b7c9d1a204"


def test_upgrade_adds_projection_and_durable_email_outbox_without_deleting_data():
    recorder = run_operation("upgrade")
    call_names = [name for name, _, _ in recorder.calls]

    assert "drop_table" not in call_names
    assert "drop_column" not in call_names

    state_columns = {
        args[1].name: args[1]
        for name, args, _ in recorder.calls
        if name == "add_column" and args[0] == "order_chat_state"
    }
    assert set(state_columns) == {
        "order_name",
        "latest_message_id",
        "operator_unread_count",
    }
    assert state_columns["order_name"].nullable is True
    assert state_columns["latest_message_id"].nullable is True
    assert state_columns["operator_unread_count"].nullable is False
    assert str(state_columns["operator_unread_count"].server_default.arg) == "0"
    foreign_keys = {
        args[0]: args
        for name, args, _ in recorder.calls
        if name == "create_foreign_key"
    }
    assert foreign_keys["fk_order_chat_state_latest_message"][1:] == (
        "order_chat_state",
        "order_chat_message",
        ["latest_message_id"],
        ["id"],
    )
    checks = {
        args[0]: args
        for name, args, _ in recorder.calls
        if name == "create_check_constraint"
    }
    assert checks["ck_order_chat_operator_unread_nonnegative"][1:] == (
        "order_chat_state",
        "operator_unread_count >= 0",
    )

    table_call = next(
        call for call in recorder.calls if call[0] == "create_table"
    )
    assert table_call[1][0] == "order_chat_email_outbox"
    table_items = table_call[1][1:]
    columns = {
        item.name: item for item in table_items if isinstance(item, sa.Column)
    }
    assert set(columns) == {
        "id",
        "message_id",
        "recipient_email",
        "recipient_kind",
        "status",
        "attempts",
        "available_at",
        "locked_at",
        "sent_at",
        "last_error",
        "created_at",
    }
    assert columns["recipient_email"].type.length == 320
    assert columns["last_error"].type.length == 255

    executed_sql = "\n".join(
        str(args[0])
        for name, args, _ in recorder.calls
        if name == "execute"
    )
    normalized_sql = " ".join(executed_sql.split())
    assert "SELECT DISTINCT ON (order_id)" in normalized_sql
    assert "ORDER BY order_id, created_at DESC, id DESC" in normalized_sql
    assert "SET latest_message_id = latest.id" in normalized_sql
    assert "operator_unread_count" not in normalized_sql
    assert "DELETE FROM" not in normalized_sql.upper()

    indexes = {
        args[0]: args
        for name, args, _ in recorder.calls
        if name == "create_index"
    }
    assert indexes["ix_order_chat_email_outbox_due"][1:] == (
        "order_chat_email_outbox",
        ["status", "available_at"],
    )


def test_downgrade_removes_only_additive_objects_in_dependency_order():
    recorder = run_operation("downgrade")
    calls = [(name, args[0]) for name, args, _ in recorder.calls]

    assert calls.index(("drop_index", "ix_order_chat_email_outbox_due")) < calls.index(
        ("drop_table", "order_chat_email_outbox")
    )
    assert calls.index(("drop_table", "order_chat_email_outbox")) < calls.index(
        ("drop_column", "order_chat_state")
    )
    assert all(
        not (name == "drop_table" and target in {"order_chat_message", "order_chat_attachment"})
        for name, target in calls
    )
