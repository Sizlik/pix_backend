from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy.dialects import postgresql

from db.models.order_chat import OrderChatEmailOutbox

try:
    import db.order_chat_email_repository as repository_module
except ModuleNotFoundError:
    repository_module = SimpleNamespace()


OUTBOX_ID = UUID("00000000-0000-0000-0000-000000000010")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000020")
ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
CLIENT_ID = UUID("00000000-0000-0000-0000-000000000030")
NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)


class Result:
    def __init__(self, rows=None):
        self.rows = [] if rows is None else rows

    def all(self):
        return self.rows


class OutboxSession:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []
        self.begin_count = 0
        self.flush_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    @asynccontextmanager
    async def begin(self):
        self.begin_count += 1
        yield

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0) if self.results else Result()

    async def flush(self):
        self.flush_count += 1


def outbox(*, status="pending", attempts=0, recipient_kind="manager"):
    return OrderChatEmailOutbox(
        id=OUTBOX_ID,
        message_id=MESSAGE_ID,
        recipient_email="recipient@example.com",
        recipient_kind=recipient_kind,
        status=status,
        attempts=attempts,
        available_at=NOW - timedelta(minutes=1),
        locked_at=NOW - timedelta(minutes=10) if status == "processing" else None,
        created_at=NOW - timedelta(hours=1),
    )


def message(*, sender_kind="client", body="Проверка"):
    return SimpleNamespace(
        id=MESSAGE_ID,
        order_id=ORDER_ID,
        client_id=CLIENT_ID,
        sender_kind=sender_kind,
        source="site",
        body=body,
        created_at=NOW,
        external_key=None,
    )


def state(*, order_name="12345"):
    return SimpleNamespace(
        order_id=ORDER_ID,
        client_id=CLIENT_ID,
        order_name=order_name,
    )


def compiled(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


async def test_claim_due_locks_jobs_and_returns_canonical_private_content():
    row = (outbox(), message(), state(), 2)
    session = OutboxSession(Result(rows=[row]))
    repository_type = getattr(
        repository_module,
        "OrderChatEmailOutboxRepository",
        None,
    )
    assert repository_type is not None
    repository = repository_type(session_factory=lambda: session)

    jobs = await repository.claim_due(
        now=NOW,
        limit=20,
        lease_before=NOW - timedelta(minutes=5),
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.outbox_id == OUTBOX_ID
    assert job.attempts == 1
    assert job.content.recipient_email == "recipient@example.com"
    assert job.content.recipient_kind == "manager"
    assert job.content.order_id == ORDER_ID
    assert job.content.order_name == "12345"
    assert job.content.sender_label == "Клиент"
    assert job.content.message == "Проверка"
    assert job.content.attachment_count == 2
    claimed = row[0]
    assert claimed.status == "processing"
    assert claimed.attempts == 1
    assert claimed.locked_at == NOW
    assert session.begin_count == 1
    assert session.flush_count == 1
    statement = session.statements[0]
    sql = compiled(statement)
    assert "FOR UPDATE OF order_chat_email_outbox SKIP LOCKED" in sql
    assert "order_chat_email_outbox.available_at <=" in sql
    assert "order_chat_email_outbox.locked_at <=" in sql
    assert statement._limit_clause.value == 20


async def test_claim_due_uses_safe_fallback_name_and_manager_sender_label():
    row = (
        outbox(recipient_kind="client"),
        message(sender_kind="manager", body="Готово"),
        state(order_name=None),
        0,
    )
    session = OutboxSession(Result(rows=[row]))
    repository = repository_module.OrderChatEmailOutboxRepository(
        session_factory=lambda: session
    )

    jobs = await repository.claim_due(
        now=NOW,
        limit=20,
        lease_before=NOW - timedelta(minutes=5),
    )

    assert jobs[0].content.order_name == "…00000001"
    assert jobs[0].content.sender_label == "Менеджер Pix Logistic"


async def test_mark_sent_clears_lease_and_private_error():
    session = OutboxSession()
    repository = repository_module.OrderChatEmailOutboxRepository(
        session_factory=lambda: session
    )

    await repository.mark_sent(OUTBOX_ID, sent_at=NOW)

    statement = session.statements[0]
    params = statement.compile().params
    assert "sent" in params.values()
    assert NOW in params.values()
    assert None in params.values()
    assert "order_chat_email_outbox.status = 'processing'" in compiled(statement)


async def test_mark_failed_schedules_retry_and_truncates_safe_category():
    session = OutboxSession()
    repository = repository_module.OrderChatEmailOutboxRepository(
        session_factory=lambda: session
    )
    available_at = NOW + timedelta(minutes=5)

    await repository.mark_failed(
        OUTBOX_ID,
        category="x" * 300,
        available_at=available_at,
        dead=False,
    )

    params = session.statements[0].compile().params
    assert "pending" in params.values()
    assert "x" * 255 in params.values()
    assert available_at in params.values()
    assert None in params.values()


async def test_mark_failed_moves_exhausted_job_to_dead_without_retry_time():
    session = OutboxSession()
    repository = repository_module.OrderChatEmailOutboxRepository(
        session_factory=lambda: session
    )

    await repository.mark_failed(
        OUTBOX_ID,
        category="provider_4xx",
        available_at=None,
        dead=True,
    )

    params = session.statements[0].compile().params
    assert "dead" in params.values()
    assert "provider_4xx" in params.values()
