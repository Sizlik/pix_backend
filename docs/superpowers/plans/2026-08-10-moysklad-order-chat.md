# MoySklad Order Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести переписку только по заказам из Telegram в стандартное поле `Комментарий` заказа покупателя в МоемСкладе, сохранить двустороннюю доставку сообщений и файлов на сайт, неизменяемую историю и Telegram-оповещения.

**Architecture:** PostgreSQL хранит каноническую неизменяемую историю заказного чата, MinIO — канонические байты вложений, а поле `description` и коллекция `files` заказа покупателя в МоемСкладе являются рабочей проекцией для менеджера. Клиентские события фиксируются транзакционно вместе с outbox, фоновые обработчики синхронизируют МойСклад и Telegram, а защищенный webhook только дедуплицирует событие и быстро ставит его в очередь. Сайт читает историю через REST, отправляет текст и файлы через multipart REST и получает новые сообщения через существующий WebSocket, масштабированный Redis Pub/Sub.

**Tech Stack:** Python 3.11, FastAPI 0.104, Pydantic 2.5, SQLAlchemy 2.0, Alembic 1.12, PostgreSQL 16, Redis 7, MinIO Python SDK 7.2.20, requests 2.31, aiogram 3.3, pytest; Next.js 14, React 18, TypeScript 5, Axios 1.6, Vitest 3.2, Playwright 1.62, Docker Compose.

## Global Constraints

- Меняется только чат конкретного заказа; общий чат поддержки продолжает работать по существующему Telegram-сценарию.
- Встроенный виджет/приложение МоегоСклада не создается: менеджер отвечает в стандартном поле `Комментарий` заказа покупателя.
- Поле `description` заказа после инициализации целиком принадлежит заказному чату и содержит недавнюю проекцию истории, общий маркер ответа и инструкцию менеджеру.
- Общая подпись менеджера на сайте и в истории: `Менеджер Pix Logistic`; имя сотрудника МоегоСклада клиенту не раскрывается.
- Каноническая история сообщений хранится в PostgreSQL и защищена PostgreSQL-триггерами от `UPDATE` и `DELETE`; в API нет операций редактирования и удаления.
- Канонические файлы хранятся в MinIO с постоянным volume; файлы МоегоСклада являются управляемой копией, а не единственным экземпляром.
- Разрешены `.jpg`, `.jpeg`, `.png`, `.webp`, `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.txt`, `.zip`; максимум `20 MiB` на файл и `10` файлов на сообщение.
- Проверяется не только расширение, но и сигнатура содержимого; исполняемые файлы, неизвестные ZIP-контейнеры Office и TXT с NUL-байтами отклоняются.
- Клиентские копии в МоемСкладе называются `[ЧАТ-КЛИЕНТ][<message-id>] <original>`; менеджер публикует файл клиенту только с префиксом `[КЛИЕНТ]`; `[PIX]` зарезервирован для системных файлов.
- Все существующие файлы заказа при первой инициализации становятся baseline/internal и никогда автоматически не показываются клиенту.
- МойСклад допускает максимум 100 файлов на объект: при нехватке места удаляются только самые старые управляемые `client_mirror`, канонические байты остаются в MinIO; baseline/internal/manager files не удаляются. Если все 100 мест заняты неуправляемыми файлами, текст синхронизируется, вложение остается на сайте/в MinIO и создается staff alert.
- Исходный непустой комментарий заказа один раз сохраняется как `[PIX] Комментарий до подключения чата.txt` до перезаписи.
- При превышении лимита `4096` символов в комментарии показываются последние сообщения, а полная проекция публикуется как `[PIX] История переписки.txt`; PostgreSQL всегда сохраняет полную историю.
- Telegram остается каналом оповещений: сообщение клиента идет в help-группу со ссылкой на заказ, ответ менеджера — связанному клиенту; ответ по заказу через старый сайт/Telegram-route отклоняется.
- WebSocket `/api_v1/chat/ws` сохраняет параметры `auth` и `room`; для order-room он только доставляет серверные события, а отправка выполняется через multipart REST.
- Один пользователь может иметь несколько одновременных WebSocket-подключений; межпроцессная доставка идет через Redis Pub/Sub.
- Каждый доступ клиента к истории, отправке и скачиванию повторно сверяет `order.agent` из МоегоСклада с `user.moysklad_counterparty_id`; несовпадение возвращает `404`.
- Webhook `POST /api_v1/integration/webhooks/order-chat/{secret}` сравнивает секрет через `secrets.compare_digest`, не пишет его в логи и отвечает `204` без обращения к МоемСкладу.
- Идемпотентность webhook основана на `requestId`, `auditContext.meta.href`, ID заказа и ID файлов; обработка сериализуется PostgreSQL advisory lock по заказу.
- Outbox делает до `8` попыток с базовой задержкой `5` секунд, экспоненциальным backoff и jitter `0..5` секунд, не удерживает HTTP-запрос клиента и восстанавливает зависшие `processing`-события.
- `ENABLE_MOYSKLAD_ORDER_CHAT=false` по умолчанию; отсутствующая конфигурация при включенном флаге завершается через `IntegrationNotConfigured` без значений секретов.
- Точные переменные: `ENABLE_MOYSKLAD_ORDER_CHAT`, `MOYSKLAD_ORDER_CHAT_WEBHOOK_SECRET`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_SECURE`, `CHAT_ATTACHMENT_MAX_BYTES`, `CHAT_ATTACHMENT_MAX_COUNT`, `CHAT_OUTBOX_MAX_ATTEMPTS`, `CHAT_OUTBOX_BASE_DELAY_SECONDS`.
- Локальные значения: `MINIO_BUCKET=pix-order-chat`, `MINIO_SECURE=false`, `CHAT_ATTACHMENT_MAX_BYTES=20971520`, `CHAT_ATTACHMENT_MAX_COUNT=10`, `CHAT_OUTBOX_MAX_ATTEMPTS=8`, `CHAT_OUTBOX_BASE_DELAY_SECONDS=5`.
- Тесты используют fakes/локальный mock backend и не обращаются к рабочим МойСклад, Telegram, MinIO или webhook URL.
- Alembic migration, регистрация webhook и любые production-изменения не запускаются автоматически; оператор выполняет их отдельно после просмотра URL, базы, diff и плана отката.
- Сохраняются границы `routes/` → `dependecies/` → `manager/` → repository; browser HTTP-вызовы остаются в `src/routes/routes.tsx`, настройки — только в `config.py`.
- После финальной правки обязательны backend `scripts/check.ps1`, frontend `npm.cmd run check`, `git diff --check`, `alembic history` и ручной просмотр migration.

## File Structure

Backend repository (`pix_backend`):

- Modify `config.py`, `.env.example`, `requirements.txt` — feature flag, MinIO/outbox limits and pinned SDK.
- Create `infra/minio/Dockerfile` — reproducible source build of `RELEASE.2025-10-15T17-29-55Z` instead of an unmaintained legacy binary image.
- Modify `local-docker-compose.yml`, `docker-compose.yml` — MinIO service, healthcheck and persistent volume.
- Create `db/models/order_chat.py` — isolated order-chat messages, attachments, sync state, observed MoySklad files and outbox rows.
- Modify `alembic/env.py`; create `alembic/versions/c8f2a4e6d901_order_chat_delivery.py` — tables, indexes and append-only triggers.
- Create `db/schemas/chat.py` — API DTOs and MoySklad webhook DTOs.
- Create `manager/order_chat_format.py` — pure comment rendering/parsing and MoySklad filename classification.
- Create `manager/chat_files.py` — filename normalization, content signature checks and upload limits.
- Create `manager/chat_storage.py` — S3-compatible storage protocol and MinIO adapter.
- Create `db/order_chat_repository.py` — transactional message/outbox persistence, cursor pagination, legacy import and outbox claiming.
- Create `db/moysklad_order_chat_repository.py` — focused order description/file/webhook operations with timeout and HTTP error propagation.
- Create `manager/order_chat.py` — access policy, client history/send/download use cases.
- Create `manager/moysklad_order_chat.py` — initialization, outbound projection and inbound manager reply/file processing.
- Create `manager/chat_outbox.py` — retries, stale-claim recovery, per-order PostgreSQL advisory lock and handler dispatch.
- Create `manager/chat_realtime.py` — multi-socket local hub and Redis Pub/Sub bridge.
- Create `dependecies/order_chat.py` — construction of repositories, storage, managers and application-scoped services.
- Modify `routes/chat.py` — new order endpoints, authorized outbound-only order WebSocket, multiple sockets and legacy order-reply rejection.
- Create `routes/integration/order_chat_webhook.py`; modify `routes/bitrix.py` — fast protected webhook transport.
- Modify `routes/notifications.py` — enrich `ORDER_MESSAGE` from the new immutable table.
- Modify `bot/sender.py` — separate support chat actions from order-chat notification-only messages.
- Modify `main.py` — outbox and Redis listener lifecycle when the feature is enabled.
- Create `scripts/register_moysklad_order_chat_webhook.py` — dry-run by default, explicit `--apply`, idempotent registration.
- Modify `scripts/check.ps1`, `conf.d/default.conf`, `README.md`, `docs/ARCHITECTURE.md`, `docs/LOCAL_DEVELOPMENT.md`, `docs/ENVIRONMENT.md`, `docs/SECURITY_NOTES.md` — lint coverage and operator runbook.
- Create focused tests: `tests/test_order_chat_config.py`, `tests/test_order_chat_models.py`, `tests/test_order_chat_format.py`, `tests/test_chat_files.py`, `tests/test_chat_storage.py`, `tests/test_moysklad_order_chat_repository.py`, `tests/test_order_chat_service.py`, `tests/test_chat_outbox.py`, `tests/test_order_chat_webhook.py`, `tests/test_chat_realtime.py`.

Frontend repository (`../pix_frontend_v2`):

- Modify `src/config/api.ts` — deployment-derived `ws://`/`wss://` URL helper.
- Create `src/app/dashboard/orders/[id]/orderChat.ts` and `orderChat.test.ts` — DTOs, deduplication, pagination merge and client file policy.
- Modify `src/routes/routes.tsx` — list/send/download order-chat API calls.
- Create `src/app/dashboard/orders/[id]/OrderChat.tsx` — immutable history, attachment previews/downloads, selection and multipart send.
- Modify `src/app/dashboard/orders/[id]/page.tsx` — replace legacy inline chat/WebSocket code with `OrderChat`.
- Modify `tests/mock-backend.mjs`; create `tests/order-chat.spec.ts` — deterministic history, multipart upload and realtime browser flow.

---

### Task 1: Append-only order-chat schema and migration

**Files:**
- Create: `db/models/order_chat.py`
- Modify: `alembic/env.py`
- Create: `alembic/versions/c8f2a4e6d901_order_chat_delivery.py`
- Create: `tests/test_order_chat_models.py`

**Interfaces:**
- Produces: `OrderChatMessage`, `OrderChatAttachment`, `OrderChatState`, `MoySkladOrderFile`, `ChatOutboxEvent` SQLAlchemy models.
- Produces: unique keys `order_chat_message.external_key`, `order_chat_message.legacy_message_id`, `moysklad_order_file(order_id, moysklad_file_id)`, `chat_outbox_event.dedup_key`.
- Produces: database-level rejection of every `UPDATE`/`DELETE` on `order_chat_message` and `order_chat_attachment`.
- Consumes: existing `User.id` and current Alembic head `107b04f2194b`.

- [ ] **Step 1: Write failing metadata and migration tests**

Create `tests/test_order_chat_models.py`:

```python
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
    migration = Path(
        "alembic/versions/c8f2a4e6d901_order_chat_delivery.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "107b04f2194b"' in migration
    assert "reject_order_chat_mutation" in migration
    assert "BEFORE UPDATE OR DELETE ON order_chat_message" in migration
    assert "BEFORE UPDATE OR DELETE ON order_chat_attachment" in migration
    assert "op.execute(\"UPDATE message" not in migration
    assert "op.execute(\"DELETE FROM message" not in migration
```

- [ ] **Step 2: Run the model test and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_models.py -v
```

Expected: import fails because `db.models.order_chat` does not exist.

- [ ] **Step 3: Define isolated models without modifying legacy support rows**

Create `db/models/order_chat.py` with these columns and constraints:

```python
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    UUID,
    func,
)

from db.postgres import Base


class OrderChatMessage(Base):
    __tablename__ = "order_chat_message"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID, nullable=False, index=True)
    client_id = Column(ForeignKey("user.id"), nullable=False, index=True)
    sender_kind = Column(String(16), nullable=False)
    source = Column(String(16), nullable=False)
    body = Column(Text, nullable=False, default="")
    external_key = Column(String(255), nullable=True, unique=True)
    legacy_message_id = Column(UUID, nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("sender_kind IN ('client', 'manager')", name="ck_order_chat_sender_kind"),
        CheckConstraint("source IN ('site', 'moysklad', 'legacy')", name="ck_order_chat_source"),
        Index("ix_order_chat_message_order_created", "order_id", "created_at", "id"),
    )


class OrderChatAttachment(Base):
    __tablename__ = "order_chat_attachment"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    message_id = Column(ForeignKey("order_chat_message.id"), nullable=False, index=True)
    object_key = Column(String(512), nullable=False, unique=True)
    original_filename = Column(String(255), nullable=False)
    mime_type = Column(String(255), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    origin = Column(String(16), nullable=False)
    origin_external_file_id = Column(UUID, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_order_chat_attachment_size"),
        CheckConstraint("origin IN ('site', 'moysklad')", name="ck_order_chat_attachment_origin"),
    )


class OrderChatState(Base):
    __tablename__ = "order_chat_state"

    order_id = Column(UUID, primary_key=True)
    client_id = Column(ForeignKey("user.id"), nullable=False, index=True)
    initialized = Column(Boolean, nullable=False, default=False, server_default="false")
    rendered_description_hash = Column(String(64), nullable=True)
    prior_comment_file_id = Column(UUID, nullable=True)
    history_file_id = Column(UUID, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class MoySkladOrderFile(Base):
    __tablename__ = "moysklad_order_file"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID, nullable=False, index=True)
    moysklad_file_id = Column(UUID, nullable=False)
    filename = Column(String(255), nullable=False)
    disposition = Column(String(32), nullable=False)
    message_id = Column(ForeignKey("order_chat_message.id"), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("order_id", "moysklad_file_id", name="uq_moysklad_order_file"),
        CheckConstraint(
            "disposition IN ('baseline', 'client_mirror', 'manager_public', 'internal', 'system')",
            name="ck_moysklad_order_file_disposition",
        ),
    )


class ChatOutboxEvent(Base):
    __tablename__ = "chat_outbox_event"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    event_type = Column(String(64), nullable=False)
    order_id = Column(UUID, nullable=False, index=True)
    dedup_key = Column(String(255), nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'completed', 'dead')", name="ck_chat_outbox_status"),
        Index("ix_chat_outbox_due", "status", "available_at"),
    )
```

Do not add relationships with cascade mutations to the append-only tables; repository reads use explicit joins.

- [ ] **Step 4: Add the reviewed Alembic migration and append-only triggers**

Import `order_chat` in `alembic/env.py`. Create revision `c8f2a4e6d901_order_chat_delivery.py` with `revision = "c8f2a4e6d901"`, `down_revision = "107b04f2194b"`, and tables/indexes matching the models. After table creation execute:

```python
    op.execute(
        """
        CREATE FUNCTION reject_order_chat_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'order chat history is append-only';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER order_chat_message_append_only
        BEFORE UPDATE OR DELETE ON order_chat_message
        FOR EACH ROW EXECUTE FUNCTION reject_order_chat_mutation();

        CREATE TRIGGER order_chat_attachment_append_only
        BEFORE UPDATE OR DELETE ON order_chat_attachment
        FOR EACH ROW EXECUTE FUNCTION reject_order_chat_mutation();
        """
    )
```

The downgrade first drops both triggers, then the function, indexes and five new tables in reverse dependency order. It never touches legacy `message` or `chat_room` rows.

- [ ] **Step 5: Run tests and review migration without applying it**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_models.py -v
& ".\.venv\Scripts\python.exe" -m alembic history
git diff -- alembic/env.py alembic/versions/c8f2a4e6d901_order_chat_delivery.py db/models/order_chat.py
git diff --check
```

Expected: tests PASS and history shows `107b04f2194b -> c8f2a4e6d901 (head)`. Do not run `alembic upgrade`, `downgrade` or autogenerate.

- [ ] **Step 6: Commit the append-only schema**

```powershell
git add db/models/order_chat.py alembic/env.py alembic/versions/c8f2a4e6d901_order_chat_delivery.py tests/test_order_chat_models.py
git commit -m "feat: add immutable order chat schema"
```

---

### Task 2: Comment projection and attachment policy

**Files:**
- Create: `db/schemas/chat.py`
- Create: `manager/order_chat_format.py`
- Create: `manager/chat_files.py`
- Create: `tests/test_order_chat_format.py`
- Create: `tests/test_chat_files.py`

**Interfaces:**
- Produces: `SenderKind`, `MessageSource`, `AttachmentOrigin` string enums and REST/webhook DTOs.
- Produces: `TranscriptEntry`, `RenderedOrderComment`, `render_order_comment(entries)`, `render_full_history(entries)`, `extract_manager_reply(description)`, `description_hash(description)`.
- Produces: `FileDisposition`, `classify_moysklad_filename(filename)`, `client_copy_filename(message_id, original_filename, ordinal)`, `manager_public_filename(filename)`.
- Produces: `ValidatedUpload`, `validate_chat_upload(filename, content, max_bytes)`, `validate_upload_batch(files, max_count)`.

- [ ] **Step 1: Write failing projection tests**

Create `tests/test_order_chat_format.py`:

```python
from datetime import datetime, timezone
from uuid import UUID

import pytest

from manager.order_chat_format import (
    CHAT_HEADER,
    HISTORY_FILENAME,
    REPLY_PROMPT,
    FileDisposition,
    MalformedOrderChatComment,
    TranscriptEntry,
    classify_moysklad_filename,
    client_copy_filename,
    extract_manager_reply,
    manager_public_filename,
    render_order_comment,
)


def entry(number: int, body: str) -> TranscriptEntry:
    return TranscriptEntry(
        sender_kind="client" if number % 2 else "manager",
        created_at=datetime(2026, 8, 10, 10, number, tzinfo=timezone.utc),
        body=body,
        filenames=(f"file-{number}.pdf",) if number == 1 else (),
    )


def test_comment_has_generic_signature_and_extracts_only_text_below_prompt():
    rendered = render_order_comment([entry(1, "Где заказ?"), entry(2, "Проверяем")])

    assert rendered.text.startswith(CHAT_HEADER)
    assert "Клиент:" in rendered.text
    assert "Менеджер Pix Logistic:" in rendered.text
    assert rendered.text.endswith(REPLY_PROMPT)
    assert extract_manager_reply(rendered.text + "\nОтправим сегодня") == "Отправим сегодня"


def test_comment_never_exceeds_moysklad_limit_and_requests_history_file():
    rendered = render_order_comment([entry(number, "x" * 700) for number in range(1, 12)])

    assert len(rendered.text) <= 4096
    assert rendered.truncated is True
    assert rendered.history_filename == HISTORY_FILENAME
    assert "Показаны последние" in rendered.text
    assert "x" * 700 in rendered.full_history


def test_missing_prompt_is_not_interpreted_as_a_client_facing_reply():
    with pytest.raises(MalformedOrderChatComment):
        extract_manager_reply("менеджер случайно удалил служебный маркер")


def test_moysklad_file_prefixes_are_unambiguous():
    message_id = UUID("00000000-0000-0000-0000-000000000123")

    assert client_copy_filename(message_id, "../../счет.pdf", 1) == (
        "[ЧАТ-КЛИЕНТ][00000000-0000-0000-0000-000000000123] счет.pdf"
    )
    assert classify_moysklad_filename("[КЛИЕНТ] фото.jpg") is FileDisposition.MANAGER_PUBLIC
    assert manager_public_filename("[КЛИЕНТ] фото.jpg") == "фото.jpg"
    assert classify_moysklad_filename("[ЧАТ-КЛИЕНТ][m] фото.jpg") is FileDisposition.CLIENT_MIRROR
    assert classify_moysklad_filename("[PIX] История переписки.txt") is FileDisposition.SYSTEM
    assert classify_moysklad_filename("накладная.pdf") is FileDisposition.INTERNAL
```

- [ ] **Step 2: Write failing file signature tests**

Create `tests/test_chat_files.py`:

```python
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from manager.chat_files import ChatFileRejected, validate_chat_upload, validate_upload_batch


def zip_bytes(member: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(member, "content")
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "content", "mime_type"),
    [
        ("photo.jpg", b"\xff\xd8\xff\xe0image", "image/jpeg"),
        ("photo.png", b"\x89PNG\r\n\x1a\nimage", "image/png"),
        ("photo.webp", b"RIFF\x10\x00\x00\x00WEBPimage", "image/webp"),
        ("doc.pdf", b"%PDF-1.7\nbody", "application/pdf"),
        ("note.txt", "текст".encode(), "text/plain"),
        ("doc.docx", zip_bytes("word/document.xml"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("sheet.xlsx", zip_bytes("xl/workbook.xml"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("archive.zip", zip_bytes("file.txt"), "application/zip"),
    ],
)
def test_allowed_uploads_require_matching_content(filename, content, mime_type):
    validated = validate_chat_upload(filename, content, 20 * 1024 * 1024)

    assert validated.filename == filename
    assert validated.mime_type == mime_type
    assert validated.size_bytes == len(content)
    assert len(validated.sha256) == 64


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("program.exe", b"MZ"),
        ("fake.pdf", b"not a pdf"),
        ("fake.docx", zip_bytes("xl/workbook.xml")),
        ("bad.txt", b"hello\x00world"),
        ("empty.txt", b""),
    ],
)
def test_dangerous_or_mismatched_files_are_rejected(filename, content):
    with pytest.raises(ChatFileRejected):
        validate_chat_upload(filename, content, 20 * 1024 * 1024)


def test_batch_limit_and_file_size_are_enforced():
    with pytest.raises(ChatFileRejected, match="maximum 10"):
        validate_upload_batch([("a.txt", b"a")] * 11, 10, 20 * 1024 * 1024)
    with pytest.raises(ChatFileRejected, match="too large"):
        validate_chat_upload("a.txt", b"a" * 11, 10)
```

- [ ] **Step 3: Run both test files and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_format.py tests/test_chat_files.py -v
```

Expected: imports fail because the schema, formatter and validator do not exist.

- [ ] **Step 4: Add exact transport DTOs**

Create `db/schemas/chat.py` with `StrEnum` values and these response shapes:

```python
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SenderKind(StrEnum):
    CLIENT = "client"
    MANAGER = "manager"


class MessageSource(StrEnum):
    SITE = "site"
    MOYSKLAD = "moysklad"
    LEGACY = "legacy"


class AttachmentOrigin(StrEnum):
    SITE = "site"
    MOYSKLAD = "moysklad"


class OrderChatAttachmentResponse(BaseModel):
    id: UUID
    filename: str
    mime_type: str
    size_bytes: int


class OrderChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    sender_kind: SenderKind
    sender_label: str
    message: str
    created_at: datetime
    attachments: list[OrderChatAttachmentResponse]
    delivery_state: Literal["pending", "synced", "failed"]


class OrderChatPageResponse(BaseModel):
    items: list[OrderChatMessageResponse]
    next_before: UUID | None


class MoySkladWebhookMeta(BaseModel):
    type: str
    href: HttpUrl


class MoySkladWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    meta: MoySkladWebhookMeta
    action: str
    accountId: UUID
    updatedFields: list[str] = Field(default_factory=list)


class MoySkladAuditContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    meta: MoySkladWebhookMeta
    moment: str
    uid: str


class MoySkladWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    auditContext: MoySkladAuditContext | None = None
    events: list[MoySkladWebhookEvent]
```

- [ ] **Step 5: Implement deterministic comment and filename functions**

In `manager/order_chat_format.py`, define exact constants and dataclasses:

```python
CHAT_HEADER = "ПЕРЕПИСКА С КЛИЕНТОМ — НЕ РЕДАКТИРОВАТЬ"
REPLY_MARKER = "ОТВЕТ МЕНЕДЖЕРА:"
REPLY_PROMPT = "ОТВЕТ МЕНЕДЖЕРА:\nНапишите ответ ниже этой строки и сохраните заказ."
HISTORY_FILENAME = "[PIX] История переписки.txt"
PRIOR_COMMENT_FILENAME = "[PIX] Комментарий до подключения чата.txt"
MAX_COMMENT_CHARS = 4096
```

Use `zoneinfo.ZoneInfo("Europe/Kaliningrad")`, format every line as `[ДД.ММ.ГГГГ ЧЧ:ММ] <label>: <body>`, append `Файлы: name1, name2` when present, and build `full_history` from every message. Reserve the header, truncation notice and prompt before selecting whole recent message blocks from newest to oldest; never cut a message in half. `description_hash` is lowercase SHA-256 hex of UTF-8 text. `extract_manager_reply` requires both the header and the exact prompt, then returns only the trimmed suffix.

Define filename classification with prefix order `[PIX]`, `[ЧАТ-КЛИЕНТ]`, `[КЛИЕНТ]`, other. Strip directory components, control characters and surrounding whitespace, preserve the extension, cap the final UTF-8-safe visible name at 255 characters, and append ` (2)`, ` (3)` for ordinal values above one before the extension.

- [ ] **Step 6: Implement byte-level file validation**

Create `manager/chat_files.py` with:

```python
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    filename: str
    content: bytes
    mime_type: str
    size_bytes: int
    sha256: str


class ChatFileRejected(ValueError):
    pass
```

Implement `validate_chat_upload` with the exact signatures from the tests. For `.doc` and `.xls`, require the OLE header `D0 CF 11 E0 A1 B1 1A E1`; for `.docx` require a ZIP member under `word/`; for `.xlsx` require a member under `xl/`; for `.zip` reject archives containing absolute paths or `..` path segments and accept other safe members. Decode `.txt` as UTF-8. Call the validator for every tuple in `validate_upload_batch`, fail the whole batch before storage, and return a tuple of `ValidatedUpload`.

- [ ] **Step 7: Run focused tests GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_format.py tests/test_chat_files.py -v
& ".\.venv\Scripts\python.exe" -m ruff check db/schemas/chat.py manager/order_chat_format.py manager/chat_files.py tests/test_order_chat_format.py tests/test_chat_files.py
```

Expected: all projection, parser, filename and signature cases PASS.

- [ ] **Step 8: Commit the pure contracts and policy**

```powershell
git add db/schemas/chat.py manager/order_chat_format.py manager/chat_files.py tests/test_order_chat_format.py tests/test_chat_files.py
git commit -m "feat: define order chat projection rules"
```

---

### Task 3: Object storage adapter and transactional chat repository

**Files:**
- Create: `manager/chat_storage.py`
- Create: `db/order_chat_repository.py`
- Create: `tests/test_chat_storage.py`
- Create: `tests/test_order_chat_repository.py`

**Interfaces:**
- Consumes: models from Task 1 and validated attachment metadata from Task 2; production credentials are injected later at the dependency boundary.
- Produces: `StoredObject`, `ObjectStorage.put/read/delete/ensure_bucket`, `MinioObjectStorage`.
- Produces: `NewAttachment`, `NewOutboxEvent`, `StoredMessage` dataclasses.
- Produces: `OrderChatRepository.ensure_state`, `import_legacy_messages`, `create_message`, `create_manager_message_with_notification`, `list_messages`, `get_attachment_for_client`, `list_transcript`, `delivery_state_for`, `record_moysklad_files`, `list_unmirrored_site_attachments`, `order_lock`, `claim_due_event`, `release_claim`, `complete_event`, `retry_event`, `recover_stale_events`.
- Produces: `before: UUID | None` as the public cursor contract; pagination resolves that message row and applies `created_at < cursor.created_at OR (created_at = cursor.created_at AND id < cursor.id)`.

- [ ] **Step 1: Write failing storage and retry tests**

Create `tests/test_chat_storage.py` with a fake synchronous MinIO client and verify bucket creation, content type, length and object cleanup:

```python
from io import BytesIO

from manager.chat_storage import MinioObjectStorage


class FakeMinio:
    def __init__(self):
        self.buckets = set()
        self.objects = {}

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket):
        self.buckets.add(bucket)

    def put_object(self, bucket, key, stream, length, content_type):
        self.objects[(bucket, key)] = (stream.read(), length, content_type)

    def get_object(self, bucket, key):
        content = self.objects[(bucket, key)][0]

        class Response:
            data = content

            def close(self):
                return None

            def release_conn(self):
                return None

        return Response()

    def remove_object(self, bucket, key):
        self.objects.pop((bucket, key), None)


async def test_minio_adapter_owns_bucket_and_round_trips_bytes():
    client = FakeMinio()
    storage = MinioObjectStorage(client=client, bucket="pix-order-chat")

    await storage.ensure_bucket()
    await storage.put("orders/o/messages/m/a.txt", b"hello", "text/plain")

    assert await storage.read("orders/o/messages/m/a.txt") == b"hello"
    assert client.objects[("pix-order-chat", "orders/o/messages/m/a.txt")][1:] == (5, "text/plain")
    await storage.delete("orders/o/messages/m/a.txt")
    assert client.objects == {}
```

Create `tests/test_order_chat_repository.py` for pure key/cursor/backoff helpers:

```python
from datetime import datetime, timedelta, timezone
from uuid import UUID

from db.order_chat_repository import object_key, retry_at


def test_object_key_never_contains_client_filename():
    order_id = UUID("00000000-0000-0000-0000-000000000001")
    message_id = UUID("00000000-0000-0000-0000-000000000002")
    attachment_id = UUID("00000000-0000-0000-0000-000000000003")

    assert object_key(order_id, message_id, attachment_id) == (
        "orders/00000000-0000-0000-0000-000000000001/"
        "messages/00000000-0000-0000-0000-000000000002/"
        "attachments/00000000-0000-0000-0000-000000000003"
    )


def test_retry_backoff_is_exponential_and_capped_at_one_hour():
    now = datetime(2026, 8, 10, tzinfo=timezone.utc)

    assert retry_at(now, attempts=1, base_seconds=5, jitter_seconds=0) == now + timedelta(seconds=5)
    assert retry_at(now, attempts=4, base_seconds=5, jitter_seconds=0) == now + timedelta(seconds=40)
    assert retry_at(now, attempts=20, base_seconds=5, jitter_seconds=0) == now + timedelta(hours=1)
```

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_chat_storage.py tests/test_order_chat_repository.py -v
```

Expected: imports fail because both modules are new.

- [ ] **Step 3: Implement the S3-compatible storage boundary**

Create `manager/chat_storage.py`. The public protocol is:

```python
from typing import Protocol


class ObjectStorage(Protocol):
    async def ensure_bucket(self) -> None:
        raise NotImplementedError

    async def put(self, key: str, content: bytes, content_type: str) -> None:
        raise NotImplementedError

    async def read(self, key: str) -> bytes:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError
```

`MinioObjectStorage` accepts an injected client for tests; production construction creates `minio.Minio(endpoint, access_key, secret_key, secure)`. Wrap every blocking SDK operation with `anyio.to_thread.run_sync`. Always close and release the response returned by `get_object` in `finally`.

- [ ] **Step 4: Implement transaction-sized repository methods**

Create `db/order_chat_repository.py` with constructor `OrderChatRepository(session_factory=async_session_maker)`. Use one `async with session.begin()` in `create_message` to insert the message, every attachment, and every supplied outbox row. Catch `IntegrityError` on unique dedup keys by rolling back and returning the existing row instead of creating duplicates.

Use these immutable input types:

```python
@dataclass(frozen=True, slots=True)
class NewAttachment:
    id: UUID
    object_key: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    origin: str
    origin_external_file_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class NewOutboxEvent:
    event_type: str
    order_id: UUID
    dedup_key: str
    payload: dict


@dataclass(frozen=True, slots=True)
class StoredMessage:
    id: UUID
    order_id: UUID
    client_id: UUID
    sender_kind: str
    source: str
    body: str
    created_at: datetime
    attachments: tuple[OrderChatAttachment, ...]
```

`import_legacy_messages(order_id, client_id)` selects legacy `Message` rows with `to_chat_room_id == order_id`, outer-joins `User`, maps `bot@pixlogistic.com` to manager and every other sender to client, and inserts with `legacy_message_id`; `ON CONFLICT DO NOTHING` makes repeated initialization safe.

`ensure_state(order_id, client_id)` inserts the state and a `sync_order` outbox row with dedup key `initialize_order:<order_id>` in one transaction when the state is new. Existing state must belong to the same client; a conflicting `client_id` raises `OrderChatNotFound`. This makes first page load project legacy history/back up the old comment even before a new message is sent.

`list_messages` first resolves `before` within the same `order_id`, then fetches `limit + 1` rows ordered descending by `(created_at, id)`, attaches rows in one second query, returns the selected page chronologically ascending, and uses the oldest returned message ID as `next_before` only when the extra row exists. `limit` is clamped by the route to `1..100`.

`delivery_state_for(message)` returns `synced` for manager/legacy rows. For a site client row it loads outbox dedup key `sync_order:<message.id>` and maps `completed -> synced`, `dead -> failed`, and missing/`pending`/`processing -> pending`; no mutable delivery column is added to the append-only message.

`create_manager_message_with_notification` uses one transaction for the immutable manager message, attachments, one `Notifications(user_id=client_id, type="ORDER_MESSAGE", object_id=message_id)` row and supplied outbox events. `order_lock(order_id)` is an async context manager holding one PostgreSQL connection; it calls `pg_try_advisory_lock` with a stable signed 64-bit integer derived from the order UUID and calls `pg_advisory_unlock` on that same connection in `finally`. `release_claim(event_id, delay_seconds)` returns a contended event to `pending`, sets `available_at=now()+delay`, clears `locked_at`, and subtracts the claim increment so lock contention does not consume a delivery attempt.

`claim_due_event` selects `id, event_type, order_id, payload, attempts` from due rows with `FOR UPDATE SKIP LOCKED LIMIT 1`, changes the chosen event to `processing`, sets `locked_at=now()` and increments `attempts` in the same transaction. `recover_stale_events` returns events with `locked_at < now() - 5 minutes` to `pending`. `retry_event` writes a sanitized exception class/message capped at 1000 characters and moves the event to `dead` once `attempts >= max_attempts`; otherwise it calls `retry_at(..., jitter_seconds=random.uniform(0, base_seconds))` and caps total delay at one hour.

- [ ] **Step 5: Run repository/storage tests GREEN and lint**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_chat_storage.py tests/test_order_chat_repository.py -v
& ".\.venv\Scripts\python.exe" -m ruff check manager/chat_storage.py db/order_chat_repository.py tests/test_chat_storage.py tests/test_order_chat_repository.py
```

Expected: storage round-trip and deterministic key/backoff tests PASS. PostgreSQL-specific SQL receives integration coverage in the staging checklist after the migration is explicitly applied.

- [ ] **Step 6: Commit storage and persistence boundaries**

```powershell
git add manager/chat_storage.py db/order_chat_repository.py tests/test_chat_storage.py tests/test_order_chat_repository.py
git commit -m "feat: persist order chat delivery state"
```

---

### Task 4: Feature configuration and source-built MinIO service

**Files:**
- Modify: `config.py`
- Modify: `.env.example`
- Modify: `requirements.txt`
- Create: `infra/minio/Dockerfile`
- Modify: `local-docker-compose.yml`
- Modify: `docker-compose.yml`
- Create: `tests/test_order_chat_config.py`

**Interfaces:**
- Produces: `Settings.enable_moysklad_order_chat: bool`.
- Produces: `Settings.require_order_chat() -> OrderChatSettings`.
- Produces: immutable `OrderChatSettings(endpoint, access_key, secret_key, bucket, secure, webhook_secret, attachment_max_bytes, attachment_max_count, outbox_max_attempts, outbox_base_delay_seconds)`.
- Produces: healthy MinIO endpoints `localhost:9000` (S3) and `localhost:9001` (console) with volume `pix-minio-data`.

- [ ] **Step 1: Write failing settings tests**

Create `tests/test_order_chat_config.py`:

```python
import pytest

from config import Settings
from errors import IntegrationNotConfigured


def test_order_chat_is_off_and_uses_exact_safe_limits_by_default():
    settings = Settings(_env_file=None)

    assert settings.enable_moysklad_order_chat is False
    assert settings.minio_bucket == "pix-order-chat"
    assert settings.minio_secure is False
    assert settings.chat_attachment_max_bytes == 20 * 1024 * 1024
    assert settings.chat_attachment_max_count == 10
    assert settings.chat_outbox_max_attempts == 8
    assert settings.chat_outbox_base_delay_seconds == 5


def test_enabled_order_chat_requires_storage_and_webhook_secrets():
    settings = Settings(_env_file=None, enable_moysklad_order_chat=True)

    with pytest.raises(IntegrationNotConfigured, match="moysklad order chat"):
        settings.require_order_chat()


def test_enabled_order_chat_returns_secret_values_only_at_call_time():
    settings = Settings(
        _env_file=None,
        enable_moysklad_order_chat=True,
        moysklad_order_chat_webhook_secret="webhook-secret",
        minio_endpoint="localhost:9000",
        minio_access_key="pix-local",
        minio_secret_key="pix-local-secret",
    )

    resolved = settings.require_order_chat()

    assert resolved.endpoint == "localhost:9000"
    assert resolved.access_key == "pix-local"
    assert resolved.secret_key == "pix-local-secret"
    assert resolved.webhook_secret == "webhook-secret"
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_config.py -v
```

Expected: collection or attribute access fails because the order-chat settings do not exist.

- [ ] **Step 3: Add the typed configuration boundary**

Add to `config.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OrderChatSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool
    webhook_secret: str
    attachment_max_bytes: int
    attachment_max_count: int
    outbox_max_attempts: int
    outbox_base_delay_seconds: int
```

Add these fields and method inside `Settings`:

```python
    enable_moysklad_order_chat: bool = False
    moysklad_order_chat_webhook_secret: SecretStr | None = None
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: SecretStr | None = None
    minio_bucket: str = "pix-order-chat"
    minio_secure: bool = False
    chat_attachment_max_bytes: int = Field(20 * 1024 * 1024, gt=0)
    chat_attachment_max_count: int = Field(10, gt=0)
    chat_outbox_max_attempts: int = Field(8, gt=0)
    chat_outbox_base_delay_seconds: int = Field(5, gt=0)

    def require_order_chat(self) -> OrderChatSettings:
        if not self.enable_moysklad_order_chat:
            raise IntegrationNotConfigured("moysklad order chat")
        endpoint = require_value(self.minio_endpoint, "moysklad order chat")
        access_key = require_value(self.minio_access_key, "moysklad order chat")
        secret_key = require_secret(self.minio_secret_key, "moysklad order chat")
        webhook_secret = require_secret(
            self.moysklad_order_chat_webhook_secret,
            "moysklad order chat",
        )
        return OrderChatSettings(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            bucket=self.minio_bucket,
            secure=self.minio_secure,
            webhook_secret=webhook_secret,
            attachment_max_bytes=self.chat_attachment_max_bytes,
            attachment_max_count=self.chat_attachment_max_count,
            outbox_max_attempts=self.chat_outbox_max_attempts,
            outbox_base_delay_seconds=self.chat_outbox_base_delay_seconds,
        )
```

These exact constrained `Field` declarations make zero/negative values fail settings construction; do not resolve secrets during import or while the feature is disabled.

- [ ] **Step 4: Pin the SDK and add a reproducible source build**

Append to `requirements.txt`:

```text
minio==7.2.20
```

Create `infra/minio/Dockerfile`:

```dockerfile
FROM golang:1.24.8-alpine3.22 AS build

ARG MINIO_REF=RELEASE.2025-10-15T17-29-55Z
RUN apk add --no-cache git
RUN git clone --depth 1 --branch "${MINIO_REF}" https://github.com/minio/minio.git /src/minio
WORKDIR /src/minio
RUN CGO_ENABLED=0 go build -trimpath -o /out/minio .

FROM alpine:3.22.1
RUN apk add --no-cache ca-certificates curl \
    && addgroup -S minio \
    && adduser -S -G minio minio \
    && mkdir -p /data \
    && chown minio:minio /data
COPY --from=build /out/minio /usr/local/bin/minio
USER minio
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
```

The tag is the last published MinIO security release. Keep the storage interface S3-compatible because the upstream community repository is archived and future replacement must not change application use cases.

- [ ] **Step 5: Wire MinIO into both Compose files and the example environment**

Add this service to both Compose files; in production keep the existing host-network backend and set `MINIO_ENDPOINT=localhost:9000` in the server environment, while local host development uses the same mapped port:

```yaml
  minio:
    build:
      context: .
      dockerfile: infra/minio/Dockerfile
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
    volumes:
      - pix-minio-data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 5s
      timeout: 5s
      retries: 20
    restart: unless-stopped
```

Declare `pix-minio-data:` under each top-level `volumes:`. Add to `.env.example`:

```dotenv
ENABLE_MOYSKLAD_ORDER_CHAT=false
MOYSKLAD_ORDER_CHAT_WEBHOOK_SECRET=
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=pix-local
MINIO_SECRET_KEY=pix-local-secret-change-me
MINIO_BUCKET=pix-order-chat
MINIO_SECURE=false
CHAT_ATTACHMENT_MAX_BYTES=20971520
CHAT_ATTACHMENT_MAX_COUNT=10
CHAT_OUTBOX_MAX_ATTEMPTS=8
CHAT_OUTBOX_BASE_DELAY_SECONDS=5
```

- [ ] **Step 6: Verify configuration and Compose syntax GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_config.py -v
docker compose -f local-docker-compose.yml config --quiet
docker compose -f docker-compose.yml config --quiet
git diff --check
```

Expected: 3 tests PASS, both Compose files validate, and no live integration is contacted. A source-image build is intentionally deferred to the final dependency verification because it needs network access.

- [ ] **Step 7: Commit the configuration and storage service**

```powershell
git add config.py .env.example requirements.txt infra/minio/Dockerfile local-docker-compose.yml docker-compose.yml tests/test_order_chat_config.py
git commit -m "feat: configure order chat storage"
```

---

### Task 5: Focused MoySklad order comment, file and webhook client

**Files:**
- Create: `db/moysklad_order_chat_repository.py`
- Create: `tests/test_moysklad_order_chat_repository.py`

**Interfaces:**
- Consumes: lazy MoySklad credentials from `Settings`, official JSON API 1.2 endpoints and validated bytes from Task 2.
- Produces: `MoySkladOrderChatRepository.get_order(order_id) -> dict`.
- Produces: `update_description(order_id, description) -> dict`, `list_files(order_id) -> list[MoySkladFile]`, `upload_files(order_id, files) -> list[MoySkladFile]`, `delete_file(order_id, file_id) -> None`, `download_file(download_href) -> bytes`.
- Produces: `list_webhooks() -> list[dict]`, `create_webhook(url) -> dict` for the operator script.
- Produces: `MoySkladFile(id, filename, size, download_href)` and `MoySkladUpload(filename, content)`.

- [ ] **Step 1: Write failing HTTP contract tests**

Create `tests/test_moysklad_order_chat_repository.py`:

```python
import base64
from dataclasses import dataclass
from uuid import UUID

from config import Settings
from db.moysklad_order_chat_repository import MoySkladOrderChatRepository, MoySkladUpload


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200
    content: bytes = b""

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/files") and method == "GET":
            return FakeResponse({"rows": []})
        if url.endswith("/files") and method == "POST":
            return FakeResponse([
                {
                    "meta": {
                        "href": url + "/00000000-0000-0000-0000-000000000010",
                        "downloadHref": "https://api.moysklad.ru/api/remap/1.2/download/file",
                    },
                    "filename": "[ЧАТ-КЛИЕНТ][m] a.txt",
                    "size": 5,
                }
            ])
        if url.endswith("/entity/webhook") and method == "GET":
            return FakeResponse({"rows": []})
        if url.endswith("/entity/webhook") and method == "POST":
            return FakeResponse({"id": "webhook"})
        if "/download/" in url and method == "GET":
            return FakeResponse({}, content=b"downloaded")
        return FakeResponse({"id": "order", "agent": {"meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/client"}}})


def settings():
    return Settings(
        _env_file=None,
        moysklad_login="login",
        moysklad_password="password",
    )


async def test_get_order_expands_agent_and_uses_timeout_and_gzip():
    session = FakeSession()
    repository = MoySkladOrderChatRepository(settings(), session=session, timeout_seconds=15)

    await repository.get_order(UUID("00000000-0000-0000-0000-000000000001"))

    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url.endswith("/entity/customerorder/00000000-0000-0000-0000-000000000001")
    assert kwargs["params"] == {"expand": "agent"}
    assert kwargs["timeout"] == 15
    assert kwargs["headers"]["Accept-Encoding"] == "gzip"
    assert kwargs["headers"]["Authorization"] == "Basic " + base64.b64encode(b"login:password").decode()


async def test_upload_uses_special_resource_base64_array_and_maps_response():
    session = FakeSession()
    repository = MoySkladOrderChatRepository(settings(), session=session)

    result = await repository.upload_files(
        UUID("00000000-0000-0000-0000-000000000001"),
        [MoySkladUpload(filename="[ЧАТ-КЛИЕНТ][m] a.txt", content=b"hello")],
    )

    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/entity/customerorder/00000000-0000-0000-0000-000000000001/files")
    assert kwargs["json"] == [{"filename": "[ЧАТ-КЛИЕНТ][m] a.txt", "content": "aGVsbG8="}]
    assert result[0].filename == "[ЧАТ-КЛИЕНТ][m] a.txt"


async def test_description_files_delete_download_and_webhook_contracts():
    session = FakeSession()
    repository = MoySkladOrderChatRepository(settings(), session=session)
    order_id = UUID("00000000-0000-0000-0000-000000000001")
    file_id = UUID("00000000-0000-0000-0000-000000000010")

    await repository.update_description(order_id, "chat projection")
    assert (await repository.list_files(order_id)) == []
    await repository.delete_file(order_id, file_id)
    assert await repository.download_file(
        "https://api.moysklad.ru/api/remap/1.2/download/file"
    ) == b"downloaded"
    assert await repository.list_webhooks() == []
    await repository.create_webhook("https://pixlogistic.com/webhook")

    calls = {(method, url): kwargs for method, url, kwargs in session.calls}
    order_url = repository.base_url + f"entity/customerorder/{order_id}"
    assert calls[("PUT", order_url)]["json"] == {"description": "chat projection"}
    assert ("GET", order_url + "/files") in calls
    assert ("DELETE", order_url + f"/files/{file_id}") in calls
    webhook_url = repository.base_url + "entity/webhook"
    assert calls[("POST", webhook_url)]["json"] == {
        "url": "https://pixlogistic.com/webhook",
        "action": "UPDATE",
        "entityType": "customerorder",
        "diffType": "FIELDS",
    }
```

- [ ] **Step 2: Run the repository tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_order_chat_repository.py -v
```

Expected: import fails because the focused client does not exist.

- [ ] **Step 3: Implement one guarded request path**

Create `db/moysklad_order_chat_repository.py` with frozen DTOs:

```python
@dataclass(frozen=True, slots=True)
class MoySkladFile:
    id: UUID
    filename: str
    size: int
    download_href: str


@dataclass(frozen=True, slots=True)
class MoySkladUpload:
    filename: str
    content: bytes
```

The constructor accepts `settings: Settings`, optional `requests.Session`, and `timeout_seconds=15`. `_request(method, path_or_url, **kwargs)` resolves Basic Auth lazily with `require_value/require_secret`, adds `Accept-Encoding: gzip`, builds `functools.partial(session.request, method, url, headers=headers, timeout=self.timeout_seconds, **kwargs)`, passes that callable to `anyio.to_thread.run_sync`, calls `raise_for_status`, and never logs headers, URL query secrets or response bodies.

Use these exact resources:

```text
GET    entity/customerorder/{order_id}?expand=agent
PUT    entity/customerorder/{order_id}                 {"description": "<rendered chat projection>"}
GET    entity/customerorder/{order_id}/files
POST   entity/customerorder/{order_id}/files            [{"filename": "<managed filename>", "content": "<Base64 bytes>"}]
DELETE entity/customerorder/{order_id}/files/{file_id}
GET    <meta.downloadHref>                               follow redirects
GET    entity/webhook
POST   entity/webhook                                   UPDATE/customerorder/FIELDS
```

Chunk `upload_files` into at most 10 items per POST, combine responses and identify UUIDs from the last path component of `meta.href`. `list_files` reads `rows`; `upload_files` reads the returned list. `download_file` accepts only an `https` URL whose host is `api.moysklad.ru`, lets `requests` follow the official redirect, caps downloaded manager files at `CHAT_ATTACHMENT_MAX_BYTES + 1`, and rejects oversized content before returning bytes.

- [ ] **Step 4: Run focused tests GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_order_chat_repository.py -v
& ".\.venv\Scripts\python.exe" -m ruff check db/moysklad_order_chat_repository.py tests/test_moysklad_order_chat_repository.py
```

Expected: all URLs, payloads, timeout, auth and response mappings PASS without network calls.

- [ ] **Step 5: Commit the focused external client**

```powershell
git add db/moysklad_order_chat_repository.py tests/test_moysklad_order_chat_repository.py
git commit -m "feat: add MoySklad order chat client"
```

---

### Task 6: Authenticated order history, multipart send and attachment download

**Files:**
- Create: `manager/order_chat.py`
- Create: `dependecies/order_chat.py`
- Modify: `routes/chat.py`
- Create: `tests/test_order_chat_service.py`
- Create: `tests/test_order_chat_api.py`

**Interfaces:**
- Consumes: `OrderChatRepository`, `ObjectStorage`, file validator, `MoySkladOrderChatRepository` and current authenticated `User`.
- Produces: `OrderChatAccessPolicy.assert_client_access(user, order_id) -> dict`.
- Produces: `OrderChatService.list_messages(user, order_id, before, limit) -> OrderChatPageResponse`.
- Produces: `create_client_message(user, order_id, body, uploads) -> OrderChatMessageResponse`.
- Produces: `get_attachment(user, attachment_id) -> DownloadedAttachment`.
- Produces: `GET/POST /api_v1/chat/orders/{order_id}/messages` and `GET /api_v1/chat/attachments/{attachment_id}`.
- Produces: outbox events `sync_order:<message_id>` and `telegram_client:<message_id>` atomically with a client message.

- [ ] **Step 1: Write failing use-case tests with in-memory fakes**

Create `tests/test_order_chat_service.py` using a minimal user object and fakes. Cover ownership denial, file cleanup on database failure, file-only messages and atomic event names:

```python
from dataclasses import dataclass
from uuid import UUID

import pytest

from manager.order_chat import OrderChatNotFound, OrderChatService, PendingUpload

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
CLIENT_ID = UUID("00000000-0000-0000-0000-000000000002")


@dataclass
class UserStub:
    id: UUID = CLIENT_ID
    moysklad_counterparty_id: UUID = UUID("00000000-0000-0000-0000-000000000003")
    first_name: str = "Анна"
    name_id: int = 42


class FakeMoySklad:
    async def get_order(self, order_id):
        return {
            "id": str(order_id),
            "name": "101",
            "agent": {"meta": {"href": f"https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{UserStub.moysklad_counterparty_id}"}},
        }


class FakeStorage:
    def __init__(self):
        self.objects = {}

    async def put(self, key, content, content_type):
        self.objects[key] = content

    async def read(self, key):
        return self.objects[key]

    async def delete(self, key):
        self.objects.pop(key, None)


async def test_access_policy_hides_another_clients_order(service_factory):
    moysklad = FakeMoySklad()

    async def another_order(order_id):
        order = await FakeMoySklad().get_order(order_id)
        order["agent"]["meta"]["href"] = order["agent"]["meta"]["href"].rsplit("/", 1)[0] + "/other"
        return order

    moysklad.get_order = another_order
    service = service_factory(moysklad=moysklad)

    with pytest.raises(OrderChatNotFound):
        await service.list_messages(UserStub(), ORDER_ID, before=None, limit=50)


async def test_file_only_message_stores_two_events_and_returns_generic_sender(service_factory):
    service, repository, storage = service_factory(return_fakes=True)

    result = await service.create_client_message(
        UserStub(),
        ORDER_ID,
        body="  ",
        uploads=[PendingUpload(filename="note.txt", content=b"hello")],
    )

    assert result.message == ""
    assert result.sender_label == "Клиент"
    assert len(result.attachments) == 1
    assert {event.event_type for event in repository.events} == {"sync_order", "telegram_client_alert"}
    assert len(storage.objects) == 1
```

The fixture `service_factory` constructs real policy/validation logic around fakes and exposes recorded attachments/events; add a test that makes `repository.create_message` raise and asserts `storage.objects == {}` afterward.

- [ ] **Step 2: Write failing endpoint tests**

Create `tests/test_order_chat_api.py` with `create_app(Settings(_env_file=None, enable_moysklad_order_chat=True, moysklad_order_chat_webhook_secret="webhook-secret", minio_endpoint="localhost:9000", minio_access_key="access", minio_secret_key="secret"))`, override `current_user_dependency` and `get_order_chat_service`, then assert:

```python
def test_order_message_accepts_text_and_repeated_files(client):
    response = client.post(
        f"/api_v1/chat/orders/{ORDER_ID}/messages",
        data={"message": "Где заказ?"},
        files=[
            ("files", ("a.txt", b"a", "text/plain")),
            ("files", ("b.pdf", b"%PDF-1.7", "application/pdf")),
        ],
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 201
    assert response.json()["message"] == "Где заказ?"


def test_empty_message_and_files_is_rejected(client):
    response = client.post(
        f"/api_v1/chat/orders/{ORDER_ID}/messages",
        data={"message": "   "},
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 422


def test_history_limit_is_bounded(client):
    response = client.get(
        f"/api_v1/chat/orders/{ORDER_ID}/messages?limit=101",
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 422
```

Add attachment assertions for authenticated `200` with exact `Content-Type` and RFC 5987 `Content-Disposition`, unauthenticated `401`, and inaccessible `404`.

- [ ] **Step 3: Run service/API tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_service.py tests/test_order_chat_api.py -v
```

Expected: new service/dependency and endpoints are missing.

- [ ] **Step 4: Implement ownership and message orchestration**

Create `manager/order_chat.py` with:

```python
@dataclass(frozen=True, slots=True)
class PendingUpload:
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class DownloadedAttachment:
    filename: str
    mime_type: str
    content: bytes


class OrderChatNotFound(LookupError):
    pass


class EmptyOrderChatMessage(ValueError):
    pass
```

`assert_client_access` fetches the authoritative order, extracts the last path segment from `agent.meta.href`, compares it as lowercase text with the user's counterparty UUID, and raises `OrderChatNotFound` for missing/malformed/mismatched values.

For every list/send call: verify access, `ensure_state(order_id, user.id)`, then `import_legacy_messages(order_id, user.id)`. After a legacy import inserts at least one row, enqueue dedup key `sync_legacy:<order_id>` so the projection includes it. For send: read all `UploadFile` bytes in the route, validate the whole batch before writes, pre-generate message/attachment UUIDs and opaque object keys, put all objects, then call one repository transaction with:

```python
NewOutboxEvent("sync_order", order_id, f"sync_order:{message_id}", {"message_id": str(message_id)}),
NewOutboxEvent(
    "telegram_client_alert",
    order_id,
    f"telegram_client:{message_id}",
    {
        "message_id": str(message_id),
        "order_name": order.get("name", str(order_id)),
        "client_name": user.first_name,
        "client_number": user.name_id,
        "filenames": [upload.filename for upload in validated],
    },
),
```

On repository failure, delete every just-created object and re-raise. The API response uses `Клиент` for site/legacy client rows and `Менеджер Pix Logistic` for manager rows.

- [ ] **Step 5: Wire dependencies and exact routes**

Create `dependecies/order_chat.py` with cached application-scoped construction for the object store/realtime bridge and per-call managers for session-backed repositories. `get_order_chat_service()` must call `get_settings().require_order_chat()` so disabled/missing integration returns the existing `503` mapping.

Declare these routes near the top of `routes/chat.py`, before `/{order_id}`:

```python
@router.get("/orders/{order_id}/messages", response_model=OrderChatPageResponse)
async def list_order_messages(
    order_id: UUID,
    before: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(current_user_dependency),
    service: OrderChatService = Depends(get_order_chat_service),
):
    return await service.list_messages(user, order_id, before, limit)


@router.post(
    "/orders/{order_id}/messages",
    response_model=OrderChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_order_message(
    order_id: UUID,
    message: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile], File()] = [],
    user: User = Depends(current_user_dependency),
    service: OrderChatService = Depends(get_order_chat_service),
):
    uploads = [PendingUpload(file.filename or "file", await file.read()) for file in files]
    return await service.create_client_message(user, order_id, message or "", uploads)
```

The attachment route returns `Response(content=download.content, media_type=download.mime_type, headers={"Content-Disposition": content_disposition})`. Map `EmptyOrderChatMessage` and `ChatFileRejected` to `422`, `OrderChatNotFound` to `404`; keep `IntegrationNotConfigured` at application level.

- [ ] **Step 6: Run order history/API tests GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_service.py tests/test_order_chat_api.py -v
& ".\.venv\Scripts\python.exe" -m ruff check manager/order_chat.py dependecies/order_chat.py routes/chat.py tests/test_order_chat_service.py tests/test_order_chat_api.py
```

Expected: owner, pagination, multipart validation, cleanup and download cases PASS without external calls.

- [ ] **Step 7: Commit the authenticated website API**

```powershell
git add manager/order_chat.py dependecies/order_chat.py routes/chat.py tests/test_order_chat_service.py tests/test_order_chat_api.py
git commit -m "feat: expose immutable order chat API"
```

---

### Task 7: Outbox worker and client-to-MoySklad projection

**Files:**
- Create: `manager/chat_outbox.py`
- Create: `manager/moysklad_order_chat.py`
- Modify: `bot/sender.py`
- Modify: `dependecies/order_chat.py`
- Modify: `main.py`
- Create: `tests/test_chat_outbox.py`
- Create: `tests/test_moysklad_order_chat.py`

**Interfaces:**
- Consumes: outbox repository, Redis, object storage, formatter and focused MoySklad client.
- Produces: `OrderChatOutboxWorker.start()`, `stop()`, `run_once()` and handler registration by event type.
- Produces: `MoySkladOrderChatSynchronizer.sync_order(order_id) -> None`.
- Produces: `Sender.send_order_client_alert(*, order_id: str, order_name: str, client_name: str, client_number: int, text: str, filenames: list[str]) -> None` and keeps `Sender.send_chat_message(text, user, chat_id)` for general support.
- Produces: `OrderChatTelegramHandlers.client_alert(event)`, `manager_alert(event)`, `projection_error(event)`; the latter two are registered when Task 8/9 introduces their event types.
- Produces: application lifecycle that starts storage bucket creation/outbox only when `ENABLE_MOYSKLAD_ORDER_CHAT=true`.

- [ ] **Step 1: Write failing worker tests**

Create `tests/test_chat_outbox.py`:

```python
from dataclasses import dataclass
from uuid import UUID

from manager.chat_outbox import OrderChatOutboxWorker

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")


@dataclass
class Event:
    id: UUID
    event_type: str
    order_id: UUID
    payload: dict
    attempts: int = 1


class FakeRepository:
    def __init__(self, event):
        self.event = event
        self.completed = []
        self.retried = []

    async def claim_due_event(self):
        event, self.event = self.event, None
        return event

    async def complete_event(self, event_id):
        self.completed.append(event_id)

    async def retry_event(self, event, error, max_attempts, base_seconds):
        self.retried.append((event.id, type(error).__name__, max_attempts, base_seconds))


class FakeLock:
    def __init__(self, acquired=True):
        self.acquired = acquired

    async def __aenter__(self):
        return self.acquired

    async def __aexit__(self, exc_type, exc, traceback):
        return False


async def test_worker_completes_a_registered_handler():
    event = Event(UUID("00000000-0000-0000-0000-000000000002"), "sync_order", ORDER_ID, {})
    repository = FakeRepository(event)
    calls = []
    worker = OrderChatOutboxWorker(
        repository=repository,
        order_lock=lambda order_id: FakeLock(),
        handlers={"sync_order": lambda item: calls.append(item.order_id)},
        max_attempts=8,
        base_delay_seconds=5,
    )

    await worker.run_once()

    assert calls == [ORDER_ID]
    assert repository.completed == [event.id]
    assert repository.retried == []


async def test_worker_retries_failure_without_exposing_payload():
    event = Event(UUID("00000000-0000-0000-0000-000000000002"), "sync_order", ORDER_ID, {"secret": "hidden"})
    repository = FakeRepository(event)

    async def fail(item):
        raise RuntimeError("temporary")

    worker = OrderChatOutboxWorker(
        repository=repository,
        order_lock=lambda order_id: FakeLock(),
        handlers={"sync_order": fail},
        max_attempts=8,
        base_delay_seconds=5,
    )

    await worker.run_once()

    assert repository.retried == [(event.id, "RuntimeError", 8, 5)]
```

The production worker accepts sync or async handlers by checking `inspect.isawaitable(result)`. Add a test for lock contention that reschedules without incrementing business attempts.

- [ ] **Step 2: Write failing outbound projection tests**

Create `tests/test_moysklad_order_chat.py` with fakes and these cases:

```python
async def test_first_sync_backs_up_comment_baselines_files_and_projects_message(sync_fixture):
    synchronizer, sql, moysklad, storage = sync_fixture(
        description="Старый комментарий",
        files=[moysklad_file("internal.pdf")],
        messages=[client_message("Где заказ?", attachments=[site_attachment("photo.jpg", b"image")])],
    )

    await synchronizer.sync_order(ORDER_ID)

    assert moysklad.uploaded[0].filename == "[PIX] Комментарий до подключения чата.txt"
    assert moysklad.uploaded[0].content == "Старый комментарий".encode()
    assert any(upload.filename.startswith("[ЧАТ-КЛИЕНТ][") for upload in moysklad.uploaded)
    assert moysklad.description.startswith("ПЕРЕПИСКА С КЛИЕНТОМ")
    assert "Где заказ?" in moysklad.description
    assert sql.file_dispositions["internal.pdf"] == "baseline"
    assert sql.state.initialized is True


async def test_long_history_replaces_managed_history_file_only_after_new_upload(sync_fixture):
    synchronizer, sql, moysklad, storage = sync_fixture(
        description="",
        files=[],
        messages=[client_message("x" * 700) for _ in range(12)],
        history_file_id=OLD_HISTORY_ID,
    )

    await synchronizer.sync_order(ORDER_ID)

    history_upload = next(upload for upload in moysklad.uploaded if upload.filename == "[PIX] История переписки.txt")
    assert len(history_upload.content) > 4096
    assert moysklad.deleted == [OLD_HISTORY_ID]
    assert sql.state.history_file_id == moysklad.id_by_filename[history_upload.filename]


async def test_repeated_sync_does_not_duplicate_mirrored_attachments(sync_fixture):
    synchronizer, sql, moysklad, storage = sync_fixture(
        description="",
        files=[],
        messages=[client_message("photo", attachments=[site_attachment("photo.jpg", b"image")])],
    )

    await synchronizer.sync_order(ORDER_ID)
    await synchronizer.sync_order(ORDER_ID)

    client_uploads = [item for item in moysklad.uploaded if item.filename.startswith("[ЧАТ-КЛИЕНТ]")]
    assert len(client_uploads) == 1
```

- [ ] **Step 3: Run worker/projection tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_chat_outbox.py tests/test_moysklad_order_chat.py -v
```

Expected: worker and synchronizer modules are missing.

- [ ] **Step 4: Implement a recoverable single-event worker**

Create `manager/chat_outbox.py`. `start()` calls `recover_stale_events()` once, creates an `asyncio.Task` loop, and stores it; `stop()` sets an event, cancels and awaits the task. The loop calls `run_once()`, sleeps 1 second only when no event exists, and yields between events.

For every claimed event, enter `order_lock(event.order_id)`. If `pg_try_advisory_lock` returns false, call `release_claim(event.id, delay_seconds=1)`; otherwise invoke the exact handler, mark completed, and release the advisory lock in `finally`. Unknown event types go to `dead` immediately with `last_error="Unknown event type"`. Exception text passed to the repository is `f"{type(exc).__name__}: {str(exc)[:900]}"`; never include the event payload.

- [ ] **Step 5: Implement first initialization and outbound projection**

Create `manager/moysklad_order_chat.py`. `sync_order` performs this order under the worker's per-order lock:

1. Load state, authoritative order, current files, complete transcript and unmirrored site attachments.
2. If `state.initialized` is false, insert every current file as `baseline`; if `description.strip()` is nonempty and does not start with `CHAT_HEADER`, upload its UTF-8 bytes as `PRIOR_COMMENT_FILENAME`, record its file ID, and only then continue.
3. Before mirroring, reserve required slots under MoySklad's 100-file cap by deleting only the oldest recorded `client_mirror` rows/files; MinIO and DB references remain. If baseline/internal/manager files consume all slots, enqueue `telegram_projection_error`, leave those attachments unmirrored for a later retry/operator cleanup, and continue the text projection. Read each eligible attachment from MinIO, upload it with `client_copy_filename`, match the returned file by the unique name, and record `client_mirror` against its message. Upload no more than 10 per MoySklad call.
4. Render the current transcript. When truncated, replace `HISTORY_FILENAME`. If the order is already at 100 files and an old managed history file exists, delete that old history file first to free its reserved system slot; otherwise upload first, identify the new file ID, delete the previous managed history file, then replace `state.history_file_id`. On retry, compare every same-named system file to recorded IDs and retain the newest successful upload. Never delete baseline, internal or manager-public files.
5. `PUT` only `description`; after success store `rendered_description_hash`, set `initialized=true`, and complete the outbox event.

If any network operation fails, leave the outbox pending. Already-recorded files and unique filenames make the retry idempotent. A file uploaded successfully but not yet recorded is rediscovered by filename on retry before another POST.

- [ ] **Step 6: Split Telegram notification-only order methods**

Add to `bot/sender.py`:

```python
async def send_order_client_alert(
    self,
    *,
    order_id: str,
    order_name: str,
    client_name: str,
    client_number: int,
    text: str,
    filenames: list[str],
) -> None:
    attachment_line = "\nФайлы: " + ", ".join(filenames) if filenames else ""
    safe_text = html.escape(text) if text else "(только файлы)"
    message = (
        f'Клиент #{client_number} {html.escape(client_name)} написал по заказу '
        f'<a href="https://online.moysklad.ru/app/#customerorder/edit?id={order_id}">'
        f'#{html.escape(order_name)}</a>:\n\n{safe_text}{html.escape(attachment_line)}\n\n'
        "Ответьте в поле «Комментарий» этого заказа в МоемСкладе."
    )
    await self._bot().send_message(self.help_chat_id, message, disable_web_page_preview=True)
```

Do not attach `chat_keyboard()` to order alerts. Keep the existing keyboard and `send_chat_message` behavior only when `chat_id == user.id` (general support).

- [ ] **Step 7: Register handlers and application lifecycle**

In `dependecies/order_chat.py`, expose one application-scoped runtime containing storage, synchronizer and outbox worker; the worker receives `OrderChatRepository.order_lock`. Register:

```python
handlers = {
    "sync_order": lambda event: synchronizer.sync_order(event.order_id),
    "telegram_client_alert": telegram_handlers.client_alert,
}
```

In `main.py` lifespan, after Redis cache initialization:

```python
        order_chat_runtime = None
        if settings.enable_moysklad_order_chat:
            order_chat_runtime = get_order_chat_runtime(settings)
            await order_chat_runtime.storage.ensure_bucket()
            await order_chat_runtime.worker.start()
            application.state.order_chat_runtime = order_chat_runtime
```

In `finally`, stop the worker before scheduler shutdown. Construction and bucket access happen only with the feature flag enabled.

- [ ] **Step 8: Run outbound tests GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_chat_outbox.py tests/test_moysklad_order_chat.py -v
& ".\.venv\Scripts\python.exe" -m pytest tests/test_app.py tests/test_integrations.py -v
& ".\.venv\Scripts\python.exe" -m ruff check manager/chat_outbox.py manager/moysklad_order_chat.py bot/sender.py dependecies/order_chat.py main.py
```

Expected: retry/idempotency/projection tests PASS; application imports with the feature disabled and does not contact MinIO/MoySklad/Telegram.

- [ ] **Step 9: Commit outbound delivery**

```powershell
git add manager/chat_outbox.py manager/moysklad_order_chat.py bot/sender.py dependecies/order_chat.py main.py tests/test_chat_outbox.py tests/test_moysklad_order_chat.py
git commit -m "feat: sync client chat to MoySklad"
```

---

### Task 8: Fast webhook and manager-to-client reply/file ingestion

**Files:**
- Create: `routes/integration/order_chat_webhook.py`
- Modify: `routes/bitrix.py`
- Modify: `manager/moysklad_order_chat.py`
- Modify: `dependecies/order_chat.py`
- Modify: `routes/notifications.py`
- Create: `tests/test_order_chat_webhook.py`
- Modify: `tests/test_moysklad_order_chat.py`

**Interfaces:**
- Consumes: `MoySkladWebhookPayload`, query `requestId`, path secret and initialized `OrderChatState`.
- Produces: `OrderChatWebhookReceiver.enqueue(request_id, payload) -> int` count of accepted customer-order UPDATE events.
- Produces: outbox event `process_moysklad_update` with dedup key `moysklad:<requestId>:<order_id>`.
- Produces: `MoySkladOrderChatSynchronizer.process_moysklad_update(event) -> None`.
- Produces: notification type `ORDER_MESSAGE` pointing to `OrderChatMessage.id` and outbox `telegram_manager_alert:<message_id>`.

- [ ] **Step 1: Write failing fast-webhook tests**

Create `tests/test_order_chat_webhook.py`:

```python
from unittest.mock import AsyncMock


def payload(action="UPDATE", entity_type="customerorder"):
    return {
        "auditContext": {
            "meta": {"type": "audit", "href": "https://api.moysklad.ru/api/remap/1.2/audit/audit-id"},
            "moment": "2026-08-10 12:00:00",
            "uid": "manager@example.com",
        },
        "events": [{
            "meta": {
                "type": entity_type,
                "href": "https://api.moysklad.ru/api/remap/1.2/entity/customerorder/00000000-0000-0000-0000-000000000001",
            },
            "updatedFields": ["description", "files"],
            "action": action,
            "accountId": "00000000-0000-0000-0000-000000000099",
        }],
    }


def test_webhook_accepts_valid_secret_and_only_enqueues(client, receiver):
    response = client.post(
        "/api_v1/integration/webhooks/order-chat/webhook-secret?requestId=request-1",
        json=payload(),
    )

    assert response.status_code == 204
    receiver.enqueue.assert_awaited_once()


def test_webhook_hides_secret_failure_as_not_found(client, receiver):
    response = client.post(
        "/api_v1/integration/webhooks/order-chat/wrong?requestId=request-1",
        json=payload(),
    )

    assert response.status_code == 404
    receiver.enqueue.assert_not_awaited()


def test_webhook_ignores_non_update_and_non_customerorder(client, receiver):
    first = client.post(
        "/api_v1/integration/webhooks/order-chat/webhook-secret?requestId=request-2",
        json=payload(action="DELETE"),
    )
    second = client.post(
        "/api_v1/integration/webhooks/order-chat/webhook-secret?requestId=request-3",
        json=payload(entity_type="product"),
    )

    assert first.status_code == second.status_code == 204
    assert receiver.accepted_events == 0
```

The fixture overrides a receiver dependency with `AsyncMock`; test repeated `requestId` and assert only one repository dedup key exists.

- [ ] **Step 2: Add failing inbound manager scenarios**

Append to `tests/test_moysklad_order_chat.py`:

```python
async def test_manager_reply_and_prefixed_files_create_one_immutable_message(sync_fixture):
    synchronizer, sql, moysklad, storage = sync_fixture(initialized=True)
    moysklad.description = sql.rendered_description + "\nОтправили ваш заказ"
    moysklad.files = [
        moysklad_file("internal.pdf"),
        moysklad_file("[КЛИЕНТ] фото.jpg", file_id=PUBLIC_FILE_ID, content=b"\xff\xd8\xffimage"),
    ]

    await synchronizer.process_moysklad_update(moysklad_event(audit_id="audit-1"))

    message = sql.messages[-1]
    assert message.sender_kind == "manager"
    assert message.body == "Отправили ваш заказ"
    assert message.attachments[0].original_filename == "фото.jpg"
    assert message.attachments[0].origin_external_file_id == PUBLIC_FILE_ID
    assert sql.notifications[-1].object_id == message.id
    assert sql.events[-1].dedup_key == f"telegram_manager:{message.id}"
    assert moysklad.description == sql.rendered_description_after_insert


async def test_unprefixed_new_file_remains_internal_and_is_not_sent(sync_fixture):
    synchronizer, sql, moysklad, storage = sync_fixture(initialized=True)
    moysklad.files = [moysklad_file("warehouse.pdf", file_id=INTERNAL_FILE_ID)]

    await synchronizer.process_moysklad_update(moysklad_event(audit_id="audit-2"))

    assert sql.messages == []
    assert sql.file_dispositions["warehouse.pdf"] == "internal"


async def test_missing_reply_marker_alerts_staff_and_restores_canonical_description(sync_fixture):
    synchronizer, sql, moysklad, storage = sync_fixture(initialized=True)
    moysklad.description = "случайно переписанный комментарий"

    await synchronizer.process_moysklad_update(moysklad_event(audit_id="audit-3"))

    assert sql.messages == []
    assert moysklad.description == sql.rendered_description
    assert sql.events[-1].event_type == "telegram_projection_error"


async def test_self_generated_webhook_creates_no_message(sync_fixture):
    synchronizer, sql, moysklad, storage = sync_fixture(initialized=True)
    moysklad.description = sql.rendered_description
    moysklad.files = sql.known_moysklad_files

    await synchronizer.process_moysklad_update(moysklad_event(audit_id="self-update"))

    assert sql.messages == []
    assert sql.notifications == []


async def test_identical_later_replies_with_distinct_audits_are_distinct_messages(sync_fixture):
    synchronizer, sql, moysklad, storage = sync_fixture(initialized=True)
    for audit_id in ("audit-repeat-1", "audit-repeat-2"):
        moysklad.description = sql.rendered_description + "\nПринято"
        await synchronizer.process_moysklad_update(moysklad_event(audit_id=audit_id))

    assert [message.body for message in sql.messages] == ["Принято", "Принято"]
```

Add replay test with the same audit ID/file IDs and assert one message, one attachment and one notification. Add a table-driven test for 11 new `[КЛИЕНТ]` files, a 20 MiB + 1 byte file, and an executable/mismatched signature; each case creates no message/attachment, leaves the manager reply suffix in MoySklad, and enqueues one correction alert without attempting partial delivery.

- [ ] **Step 3: Run webhook/inbound tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_webhook.py tests/test_moysklad_order_chat.py -v
```

Expected: webhook module and inbound processor are absent.

- [ ] **Step 4: Implement a 1.5-second-safe receiver**

`OrderChatWebhookReceiver.enqueue` loops all events, accepts only `action == "UPDATE"` and `meta.type == "customerorder"`, parses order UUID from the final `meta.href` segment, and inserts this event without external calls:

```python
NewOutboxEvent(
    event_type="process_moysklad_update",
    order_id=order_id,
    dedup_key=f"moysklad:{request_id}:{order_id}",
    payload={
        "request_id": request_id,
        "audit_href": str(payload.auditContext.meta.href) if payload.auditContext else None,
        "audit_moment": payload.auditContext.moment if payload.auditContext else None,
        "updated_fields": event.updatedFields,
    },
)
```

Create the route with `status_code=204`. Resolve the configured secret, compare with `secrets.compare_digest`, return `404` on mismatch, require nonblank `requestId`, call enqueue, and return an empty `Response(status_code=204)`. Mount it below the existing integration webhook router in `routes/bitrix.py`.

- [ ] **Step 5: Process authoritative manager changes**

Register `process_moysklad_update` in the outbox worker. The handler:

1. Loads state; if no initialized state exists, returns successfully without claiming any existing comments/files as chat.
2. Fetches the authoritative order and file list regardless of `updatedFields`, because special file resources may not report a stable field name. Reloads the state's client and compares its `moysklad_counterparty_id` to authoritative `order.agent`; if the order is missing or ownership changed, acknowledge/complete the event without creating client data.
3. Compares description to `rendered_description_hash`. If the chat header/prompt is malformed, enqueues `telegram_projection_error`, restores the canonical DB rendering, and never sends the arbitrary text.
4. Extracts the suffix after `REPLY_PROMPT`; compares new file IDs to `MoySkladOrderFile` rows. Before storing any public file, require at most 10 new `[КЛИЕНТ]` files and validate the entire downloaded batch with the same signature/size policy. If download/MinIO fails, raise so outbox retries and keep the reply suffix. If count/type/size validation fails, create one correction alert, complete this webhook without a message, do not classify the invalid public IDs, and keep the reply suffix for the manager to correct. On a valid batch, strip prefixes, store every byte in MinIO, then attach them atomically. New `[PIX]`/`[ЧАТ-КЛИЕНТ]` are recorded as system/client mirror; other files are internal.
5. Builds `audit_identity = audit_href or request_id` and `external_key = sha256("|".join([order_id, audit_identity, reply, *sorted(public_file_ids)]))`. If it already exists, skip message creation but still restore the canonical projection.
6. Creates one manager message when reply or public files exist, plus a `Notifications` row of type `ORDER_MESSAGE` and `telegram_manager_alert`; publish is added in Task 9.
7. Calls `sync_order(order_id)` to clear the reply suffix and render the canonical DB history. Transcript tampering above an intact prompt is silently repaired from PostgreSQL.

The correction alert names only sanitized filenames and the accepted type/count/size rule. It never includes file bytes, comment text, credentials or webhook path.

- [ ] **Step 6: Enrich order notifications from the new table**

In `routes/notifications.py`, inject `OrderChatRepository`. For `NotificationTypes.ORDER_MESSAGE`, look up the immutable order message first; return:

```python
{
    **notification.__dict__,
    "id": notification.id,
    "object_id": str(message.id),
    "message": message.body,
    "first_name": "bot",
    "from_user_id": None,
    "to_chat_room_id": str(message.order_id),
    "time_created": message.created_at,
}
```

Fall back to legacy `MessageManager` for pre-migration `ORDER_MESSAGE` IDs, preserving existing notifications.

- [ ] **Step 7: Run inbound tests GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_webhook.py tests/test_moysklad_order_chat.py -v
& ".\.venv\Scripts\python.exe" -m pytest tests/test_app.py tests/test_integrations.py -v
& ".\.venv\Scripts\python.exe" -m ruff check routes/integration/order_chat_webhook.py routes/bitrix.py manager/moysklad_order_chat.py routes/notifications.py
```

Expected: secret, request dedup, reply/file classification, replay and notification compatibility tests PASS.

- [ ] **Step 8: Commit inbound delivery**

```powershell
git add routes/integration/order_chat_webhook.py routes/bitrix.py manager/moysklad_order_chat.py dependecies/order_chat.py routes/notifications.py tests/test_order_chat_webhook.py tests/test_moysklad_order_chat.py
git commit -m "feat: deliver MoySklad replies to clients"
```

---

### Task 9: Redis realtime, multiple sockets and Telegram-only notifications

**Files:**
- Create: `manager/chat_realtime.py`
- Modify: `manager/chat.py`
- Modify: `routes/chat.py`
- Modify: `dependecies/chat.py`
- Modify: `dependecies/order_chat.py`
- Modify: `manager/order_chat.py`
- Modify: `manager/moysklad_order_chat.py`
- Modify: `manager/chat_outbox.py`
- Modify: `bot/sender.py`
- Modify: `main.py`
- Create: `tests/test_chat_realtime.py`
- Modify: `tests/test_order_chat_api.py`

**Interfaces:**
- Produces: `LocalChatHub.connect(room_id, websocket)`, `disconnect`, `broadcast` with `set[WebSocket]` per room.
- Produces: `RedisChatRealtime.start()`, `stop()`, `publish(room_id, message)` using `order-chat:room:<uuid>` channels and `psubscribe`.
- Consumes: existing WebSocket `auth` and `room` query semantics.
- Produces: outbound-only authorized order-room sockets and unchanged bidirectional general support room.
- Produces: `Sender.send_order_manager_alert(telegram_id, order_id, order_name, text, filenames)`.
- Produces: realtime `{"type":"order_chat_delivery","message_id":UUID,"delivery_state":"synced"|"failed"}` for client-side MoySklad delivery status.

- [ ] **Step 1: Write failing hub and Redis bridge tests**

Create `tests/test_chat_realtime.py`:

```python
class FakeSocket:
    def __init__(self):
        self.accepted = False
        self.messages = []
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, value):
        if self.closed:
            raise RuntimeError("closed")
        self.messages.append(value)


async def test_hub_keeps_multiple_connections_and_removes_only_dead_socket():
    hub = LocalChatHub()
    first = FakeSocket()
    second = FakeSocket()

    await hub.connect("room", first)
    await hub.connect("room", second)
    first.closed = True
    await hub.broadcast("room", {"id": "message"})

    assert second.messages == [{"id": "message"}]
    assert first not in hub.connections["room"]
    assert second in hub.connections["room"]


async def test_redis_bridge_serializes_one_room_event(redis_fixture):
    bridge, local_hub, redis = redis_fixture()

    await bridge.publish("room", {"id": "message"})
    await bridge.dispatch_for_test("order-chat:room:room", redis.published[-1][1])

    assert local_hub.broadcasts == [("room", {"id": "message"})]
```

Add API WebSocket tests: two authenticated sockets with the same order room both receive a published manager message; a user whose counterparty does not own the order is closed with code `4404`; client JSON sent into an order room receives `{"type":"error","code":"order_chat_http_required"}` and creates no legacy `Message`. Add a worker test where completed `sync_order` with `payload.message_id` publishes `delivery_state="synced"`, and exhausted retry publishes `delivery_state="failed"`; initialization events without `message_id` publish no delivery event.

- [ ] **Step 2: Run realtime tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_chat_realtime.py tests/test_order_chat_api.py -v
```

Expected: the Redis bridge does not exist and current `ChatManager.connect` closes the first socket.

- [ ] **Step 3: Implement local multi-socket and Redis fan-out**

Create `manager/chat_realtime.py`. `LocalChatHub.connections` is `defaultdict(set)`. `broadcast` iterates a snapshot, removes only sockets whose `send_json` raises, and removes empty rooms. `RedisChatRealtime` uses one duplicated Redis connection/pubsub, `psubscribe("order-chat:room:*")`, JSON with `ensure_ascii=False`, and derives the room by removing the exact prefix. `stop()` cancels listener, closes pubsub, and does not close the shared auth/cache Redis client.

Update legacy `ChatManager` to delegate connection/broadcast to the shared realtime bridge; remove the singleton decorator, `print`, and first-socket close behavior. General support persistence and Telegram call remain unchanged.

- [ ] **Step 4: Authorize and split WebSocket behavior by room**

In `/chat/ws`:

- reject missing/invalid token with close `4401`;
- when `room` is absent or equals `str(user.id)`, run the existing support receive loop;
- when `room` parses as UUID and differs from user ID, call `OrderChatAccessPolicy.assert_client_access` before accept, close `4404` on failure, and keep a receive loop that only answers with the error JSON above;
- subscribe/accept once and always disconnect the exact socket in `finally`.

Do not persist order-room input from WebSocket. The REST send path from Task 6 publishes its response after the transaction; the inbound manager handler publishes after its transaction. Redis Pub/Sub is best-effort because reconnecting clients recover from REST history.

After `complete_event` for `sync_order`, `OrderChatOutboxWorker` publishes a delivery event when `event.payload["message_id"]` exists. Make `retry_event` return the resulting status; when it returns `dead` for `sync_order`, publish `failed`. REST history derives the same status from outbox, so loss of this best-effort event is repaired on reload.

- [ ] **Step 5: Reject the legacy manager order-reply route**

In `POST /chat/send_message`, keep the current bot-account path only when `client_id == to_chat_room` (general support). When they differ, return:

```python
raise HTTPException(
    status_code=409,
    detail={
        "code": "order_reply_in_moysklad_required",
        "message": "Reply in the MoySklad customer order comment",
    },
)
```

This removes the remaining backend order-reply path outside MoySklad without changing general support.

- [ ] **Step 6: Add manager-to-client Telegram notification**

Add `send_order_manager_alert` to `bot/sender.py`. It sends only when the linked user has `telegram_id`, uses generic `Менеджер Pix Logistic`, escapes order/text/filenames, and links to `https://client.pixlogistic.com/dashboard/orders/{order_id}`. File-only copy is `(отправлены файлы)`. No inline keyboard is attached.

Register handlers:

```python
"telegram_manager_alert": telegram_handlers.manager_alert,
"telegram_projection_error": telegram_handlers.projection_error,
```

`projection_error` goes to `help_chat_id` and includes the MoySklad order link plus a safe error code, never webhook secret, credentials or raw exception payload.

- [ ] **Step 7: Start/stop the realtime bridge in application lifespan**

Start the Redis realtime bridge unconditionally after Redis cache initialization because the existing general support chat also consumes it; this does not introduce a new external integration because Redis already backs authentication/cache. When the order-chat flag is enabled, inject that same bridge into the order service/inbound processor and start outbox after realtime. On shutdown stop outbox first, then realtime. With the flag false, no MinIO, MoySklad or Telegram order-chat call is made and general support keeps its current behavior.

- [ ] **Step 8: Run realtime and compatibility tests GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_chat_realtime.py tests/test_order_chat_api.py tests/test_app.py -v
& ".\.venv\Scripts\python.exe" -m ruff check manager/chat_realtime.py manager/chat.py routes/chat.py dependecies/chat.py bot/sender.py main.py
```

Expected: multi-socket, ownership, outbound-only order room, publish and general-support compatibility cases PASS.

- [ ] **Step 9: Commit realtime and notification boundaries**

```powershell
git add manager/chat_realtime.py manager/chat.py manager/chat_outbox.py routes/chat.py dependecies/chat.py dependecies/order_chat.py manager/order_chat.py manager/moysklad_order_chat.py bot/sender.py main.py tests/test_chat_realtime.py tests/test_order_chat_api.py
git commit -m "feat: stream order replies in realtime"
```

---

### Task 10: Frontend order-chat contracts and deployment-derived WebSocket URL

**Files:**
- Modify: `../pix_frontend_v2/src/config/api.ts`
- Create: `../pix_frontend_v2/src/app/dashboard/orders/[id]/orderChat.ts`
- Create: `../pix_frontend_v2/src/app/dashboard/orders/[id]/orderChat.test.ts`
- Modify: `../pix_frontend_v2/src/routes/routes.tsx`

**Interfaces:**
- Produces: `backendWebSocketUrl(path, query) -> string` derived from `NEXT_PUBLIC_BACKEND_URL`.
- Produces: `OrderChatAttachment`, `OrderChatMessage`, `OrderChatPage`, `mergeOrderChatMessages`, `validateSelectedFiles`.
- Produces: `GetOrderChatMessages(orderId, before?)`, `SendOrderChatMessage(orderId, message, files)`, `DownloadOrderChatAttachment(id)`.
- Consumes: API contracts from Task 6 and existing `token` cookie without changing its format.

- [ ] **Step 1: Write failing URL, deduplication and file-policy tests**

Create `src/app/dashboard/orders/[id]/orderChat.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { backendWebSocketUrl } from "@/config/api";
import {
  applyDeliveryEvent,
  mergeOrderChatMessages,
  validateSelectedFiles,
  type OrderChatMessage,
} from "./orderChat";

const message = (id: string, createdAt: string): OrderChatMessage => ({
  id,
  order_id: "00000000-0000-0000-0000-000000000001",
  sender_kind: id === "client" ? "client" : "manager",
  sender_label: id === "client" ? "Клиент" : "Менеджер Pix Logistic",
  message: id,
  created_at: createdAt,
  attachments: [],
  delivery_state: id === "client" ? "pending" : "synced",
});

describe("order chat helpers", () => {
  it("merges pagination and websocket copies once in chronological order", () => {
    const result = mergeOrderChatMessages(
      [message("manager", "2026-08-10T12:01:00Z")],
      [
        message("client", "2026-08-10T12:00:00Z"),
        message("manager", "2026-08-10T12:01:00Z"),
      ],
    );

    expect(result.map((item) => item.id)).toEqual(["client", "manager"]);
  });

  it("applies a durable delivery update without changing history order", () => {
    const current = [message("client", "2026-08-10T12:00:00Z")];

    expect(applyDeliveryEvent(current, {
      type: "order_chat_delivery",
      message_id: "client",
      delivery_state: "synced",
    })[0].delivery_state).toBe("synced");
  });

  it("rejects more than ten files, disallowed extensions, and files over 20 MiB", () => {
    expect(validateSelectedFiles(Array.from({ length: 11 }, (_, index) => new File(["a"], `${index}.txt`)))).toBe(
      "Можно прикрепить не более 10 файлов",
    );
    expect(validateSelectedFiles([new File(["MZ"], "program.exe")])).toBe("Тип файла program.exe не поддерживается");
    expect(validateSelectedFiles([new File([new Uint8Array(20 * 1024 * 1024 + 1)], "big.pdf")])).toBe(
      "Файл big.pdf больше 20 МБ",
    );
  });
});

describe("backendWebSocketUrl", () => {
  it("uses ws locally and encodes auth plus room", () => {
    expect(
      backendWebSocketUrl("chat/ws", { auth: "a+b/c", room: "order id" }),
    ).toBe("ws://localhost:8000/api_v1/chat/ws?auth=a%2Bb%2Fc&room=order+id");
  });
});
```

Use `// @vitest-environment happy-dom` only if the current Vitest runtime lacks `File`; otherwise keep the existing node environment and create structural `{name, size}` file stubs typed with `as File` to avoid a new dependency.

- [ ] **Step 2: Run the focused frontend test and verify RED**

```powershell
Set-Location ..\pix_frontend_v2
npm.cmd run test:unit -- "src/app/dashboard/orders/[id]/orderChat.test.ts"
```

Expected: helper module and WebSocket URL function do not exist.

- [ ] **Step 3: Add pure types, ordering and client-side preflight**

Create `orderChat.ts`:

```ts
export type OrderChatAttachment = {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
};

export type OrderChatMessage = {
  id: string;
  order_id: string;
  sender_kind: "client" | "manager";
  sender_label: "Клиент" | "Менеджер Pix Logistic";
  message: string;
  created_at: string;
  attachments: OrderChatAttachment[];
  delivery_state: "pending" | "synced" | "failed";
};

export type OrderChatDeliveryEvent = {
  type: "order_chat_delivery";
  message_id: string;
  delivery_state: "synced" | "failed";
};

export type OrderChatPage = {
  items: OrderChatMessage[];
  next_before: string | null;
};

const allowedExtensions = new Set([
  "jpg", "jpeg", "png", "webp", "pdf", "doc", "docx", "xls", "xlsx", "txt", "zip",
]);
const maxBytes = 20 * 1024 * 1024;

export function mergeOrderChatMessages(
  current: OrderChatMessage[],
  incoming: OrderChatMessage[],
): OrderChatMessage[] {
  const byId = new Map(current.map((item) => [item.id, item]));
  for (const item of incoming) byId.set(item.id, item);
  return [...byId.values()].sort((left, right) => {
    const time = Date.parse(left.created_at) - Date.parse(right.created_at);
    return time || left.id.localeCompare(right.id);
  });
}

export function validateSelectedFiles(files: File[]): string | null {
  if (files.length > 10) return "Можно прикрепить не более 10 файлов";
  for (const file of files) {
    const extension = file.name.split(".").at(-1)?.toLowerCase() ?? "";
    if (!allowedExtensions.has(extension)) return `Тип файла ${file.name} не поддерживается`;
    if (file.size > maxBytes) return `Файл ${file.name} больше 20 МБ`;
  }
  return null;
}

export function applyDeliveryEvent(
  messages: OrderChatMessage[],
  event: OrderChatDeliveryEvent,
): OrderChatMessage[] {
  return messages.map((message) =>
    message.id === event.message_id
      ? { ...message, delivery_state: event.delivery_state }
      : message,
  );
}
```

The browser check is usability only; backend byte-signature validation remains authoritative.

- [ ] **Step 4: Build WebSocket URLs from the configured API origin**

Append to `src/config/api.ts`:

```ts
export function backendWebSocketUrl(
  path: string,
  query: Record<string, string>,
): string {
  const url = new URL(backendUrl(path));
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  for (const [key, value] of Object.entries(query)) url.searchParams.set(key, value);
  return url.toString();
}
```

Remove no existing API helper and never put the webhook secret in this public module.

- [ ] **Step 5: Add typed REST functions without success toasts**

Add imports/types and these functions to `src/routes/routes.tsx`:

```ts
export async function GetOrderChatMessages(orderId: string, before?: string) {
  return axios.get<OrderChatPage>(backendUrl(`chat/orders/${orderId}/messages`), {
    headers: { Authorization: getCookie("token") },
    params: { limit: 50, ...(before ? { before } : {}) },
  });
}

export async function SendOrderChatMessage(
  orderId: string,
  message: string,
  files: File[],
) {
  const body = new FormData();
  if (message.trim()) body.append("message", message.trim());
  for (const file of files) body.append("files", file, file.name);
  return axios.post<OrderChatMessage>(
    backendUrl(`chat/orders/${orderId}/messages`),
    body,
    { headers: { Authorization: getCookie("token") } },
  );
}

export async function DownloadOrderChatAttachment(attachmentId: string) {
  return axios.get<Blob>(backendUrl(`chat/attachments/${attachmentId}`), {
    headers: { Authorization: getCookie("token") },
    responseType: "blob",
  });
}
```

Do not set multipart `Content-Type`; Axios/browser must add the boundary. Keep old `GetMessagesEndpoint` for general support; order page stops using `GetMessagesOrderEndpoint` in Task 11.

- [ ] **Step 6: Run focused tests GREEN and API URL guard**

```powershell
npm.cmd run test:unit -- "src/app/dashboard/orders/[id]/orderChat.test.ts"
npm.cmd run check:api-url
```

Expected: unit tests PASS and source guard finds no hard-coded production API/WebSocket origin.

- [ ] **Step 7: Commit frontend contracts**

```powershell
git add src/config/api.ts "src/app/dashboard/orders/[id]/orderChat.ts" "src/app/dashboard/orders/[id]/orderChat.test.ts" src/routes/routes.tsx
git commit -m "feat: add order chat browser contracts"
```

---

### Task 11: Order-page history, files and realtime UI

**Files:**
- Create: `../pix_frontend_v2/src/app/dashboard/orders/[id]/OrderChat.tsx`
- Modify: `../pix_frontend_v2/src/app/dashboard/orders/[id]/page.tsx`
- Modify: `../pix_frontend_v2/tests/mock-backend.mjs`
- Create: `../pix_frontend_v2/tests/order-chat.spec.ts`

**Interfaces:**
- Consumes: Task 10 helpers/API, current bearer cookie and `/chat/ws?auth&room`.
- Produces: `OrderChat({ orderId })` with newest page load, older-page prepend, deduplicated REST/WebSocket inserts, multiple file selection, image preview, authenticated download and no edit/delete actions.
- Produces: deterministic browser coverage for text, files, immutable history, pagination and manager realtime.

- [ ] **Step 1: Extend the local mock backend contract**

In `tests/mock-backend.mjs`, add a fixed UUID order chat and binary helper:

```js
const orderChatMessages = [
  {
    id: "00000000-0000-0000-0000-000000000101",
    order_id: "existing-order",
    sender_kind: "manager",
    sender_label: "Менеджер Pix Logistic",
    message: "Заказ уже на складе",
    created_at: "2026-08-10T12:00:00Z",
    delivery_state: "synced",
    attachments: [{
      id: "00000000-0000-0000-0000-000000000201",
      filename: "photo.jpg",
      mime_type: "image/jpeg",
      size_bytes: 8,
    }],
  },
];

function sendBytes(response, content, contentType) {
  response.writeHead(200, {
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Origin": "*",
    "Content-Disposition": "inline; filename=photo.jpg",
    "Content-Type": contentType,
  });
  response.end(content);
}
```

Add handlers before the generic 404:

```js
if (request.method === "GET" && pathname === "/api_v1/chat/orders/existing-order/messages") {
  return sendJson(response, { items: orderChatMessages, next_before: null });
}
if (request.method === "POST" && pathname === "/api_v1/chat/orders/existing-order/messages") {
  return sendJson(response, {
    id: "00000000-0000-0000-0000-000000000102",
    order_id: "existing-order",
    sender_kind: "client",
    sender_label: "Клиент",
    message: "Прикрепил документ",
    created_at: "2026-08-10T12:01:00Z",
    delivery_state: "pending",
    attachments: [{
      id: "00000000-0000-0000-0000-000000000202",
      filename: "document.pdf",
      mime_type: "application/pdf",
      size_bytes: 8,
    }],
  }, 201);
}
if (pathname === "/api_v1/chat/attachments/00000000-0000-0000-0000-000000000201") {
  return sendBytes(response, Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4]), "image/jpeg");
}
```

Remove only the old order-specific `/api_v1/chat/messages/existing-order` mock; retain `/api_v1/chat/messages` for support.

- [ ] **Step 2: Write the failing order chat browser test**

Create `tests/order-chat.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([{
    name: "token",
    value: "Bearer test-token",
    url: "http://127.0.0.1:3100",
  }]);
  await page.routeWebSocket(/\/api_v1\/chat\/ws/, (socket) => {
    setTimeout(() => {
      socket.send(JSON.stringify({
        id: "00000000-0000-0000-0000-000000000103",
        order_id: "existing-order",
        sender_kind: "manager",
        sender_label: "Менеджер Pix Logistic",
        message: "Можно забирать",
        created_at: "2026-08-10T12:02:00Z",
        delivery_state: "synced",
        attachments: [],
      }));
    }, 250);
  });
});

test("shows immutable history, sends files, and receives a MoySklad reply", async ({ page }) => {
  await page.goto("/dashboard/orders/existing-order");

  await expect(page.getByText("Заказ уже на складе")).toBeVisible();
  await expect(page.getByText("Менеджер Pix Logistic")).toBeVisible();
  await expect(page.getByRole("img", { name: "photo.jpg" })).toBeVisible();
  await expect(page.getByRole("button", { name: /редактировать|удалить/i })).toHaveCount(0);

  await page.getByPlaceholder("Введите сообщение...").fill("Прикрепил документ");
  await page.getByLabel("Прикрепить файлы").setInputFiles({
    name: "document.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.7"),
  });
  await expect(page.getByText("document.pdf")).toBeVisible();
  await page.getByRole("button", { name: "Отправить сообщение" }).click();

  await expect(page.getByText("Прикрепил документ")).toBeVisible();
  await expect(page.getByRole("button", { name: "Скачать document.pdf" })).toBeVisible();
  await expect(page.getByText("Можно забирать")).toBeVisible();
});
```

- [ ] **Step 3: Run the browser test and verify RED**

```powershell
npx.cmd playwright test tests/order-chat.spec.ts
```

Expected: the order page still uses the old message endpoint, hard-coded production WebSocket and has no attachments UI.

- [ ] **Step 4: Implement authenticated attachment rendering**

Inside `OrderChat.tsx`, implement `AttachmentView`. On mount for `mime_type.startsWith("image/")`, call `DownloadOrderChatAttachment`, create an object URL, render `<img alt={filename}>`, and revoke the URL in cleanup. For non-images render a button; on click fetch the blob, create a temporary `<a download={filename}>`, click it and revoke the URL. A failed request shows `Не удалось загрузить файл` and never falls back to an unauthenticated direct URL.

- [ ] **Step 5: Implement the immutable order chat component**

Create a client component with this state and lifecycle:

```tsx
export default function OrderChat({ orderId }: { orderId: string }) {
  const [messages, setMessages] = useState<OrderChatMessage[]>([]);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (before?: string) => {
    const response = await GetOrderChatMessages(orderId, before);
    setMessages((current) => mergeOrderChatMessages(current, response.data.items));
    setNextBefore(response.data.next_before);
  }, [orderId]);

  useEffect(() => {
    setMessages([]);
    setNextBefore(null);
    setIsLoading(true);
    load().catch(() => setError("Не удалось загрузить переписку")).finally(() => setIsLoading(false));
  }, [load]);

  useEffect(() => {
    const bearer = String(getCookie("token") ?? "");
    const auth = bearer.startsWith("Bearer ") ? bearer.slice(7) : bearer;
    let active = true;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const connect = () => {
      socket = new WebSocket(backendWebSocketUrl("chat/ws", { auth, room: orderId }));
      socket.onopen = () => {
        attempt = 0;
        void load();
      };
      socket.onmessage = (event) => {
        const incoming = JSON.parse(event.data) as OrderChatMessage | OrderChatDeliveryEvent | { type: "error" };
        if ("type" in incoming && incoming.type === "order_chat_delivery") {
          setMessages((current) => applyDeliveryEvent(current, incoming));
        } else if ("id" in incoming) {
          setMessages((current) => mergeOrderChatMessages(current, [incoming]));
        }
      };
      socket.onclose = () => {
        if (!active) return;
        setError("Связь с чатом прервана; выполняется переподключение");
        const delay = Math.min(1000 * 2 ** attempt, 30_000);
        attempt += 1;
        retryTimer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      active = false;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    };
  }, [load, orderId]);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fileError = validateSelectedFiles(files);
    if (fileError) return setError(fileError);
    if (!text.trim() && files.length === 0) return setError("Введите сообщение или прикрепите файл");
    setIsSending(true);
    setError(null);
    try {
      const response = await SendOrderChatMessage(orderId, text, files);
      setMessages((current) => mergeOrderChatMessages(current, [response.data]));
      setText("");
      setFiles([]);
    } catch {
      setError("Не удалось отправить сообщение");
    } finally {
      setIsSending(false);
    }
  }
```

Import `OrderChatDeliveryEvent` and `applyDeliveryEvent`. Render one optional `Показать предыдущие` button calling `load(nextBefore)`, chronological message cards with label/time/text/attachments and client delivery copy `Отправляется в МойСклад` for `pending`, `Не доставлено в МойСклад — мы повторяем отправку` for `failed`, and no extra badge for `synced`. Render selected filename/size chips with pre-send remove buttons, a multiple file input labeled `Прикрепить файлы`, controlled textarea, and submit button labeled `Отправить сообщение`. Remove buttons exist only for unsent selected files; sent message/attachment cards have no edit/delete controls. Preserve the welcome message as static helper copy outside stored history.

- [ ] **Step 6: Replace the legacy inline order chat**

In `page.tsx`, remove `getMessagesType`, `GetMessagesOrderEndpoint`, message/socket states, both legacy chat effects, `sendMessage`, `PixTextArea`, `SymmetryHorizontal`, `FormEvent`, `useRef`, and the local `Message` component. Import `OrderChat` and replace the whole `Комментарии по заказу` block with:

```tsx
<OrderChat orderId={params.id} />
```

Do not change order editing, documents, actions or general support pages.

- [ ] **Step 7: Run focused frontend checks GREEN**

```powershell
npm.cmd run test:unit -- "src/app/dashboard/orders/[id]/orderChat.test.ts"
npx.cmd playwright test tests/order-chat.spec.ts
npm.cmd run lint
npm.cmd run check:api-url
```

Expected: unit/browser tests PASS, the order page has no production WebSocket literal, and lint adds no warnings.

- [ ] **Step 8: Review and commit the order UI**

```powershell
git diff --check
git diff -- "src/app/dashboard/orders/[id]/OrderChat.tsx" "src/app/dashboard/orders/[id]/page.tsx" tests/mock-backend.mjs tests/order-chat.spec.ts
git add "src/app/dashboard/orders/[id]/OrderChat.tsx" "src/app/dashboard/orders/[id]/page.tsx" tests/mock-backend.mjs tests/order-chat.spec.ts
git commit -m "feat: show order chat files and history"
```

---

### Task 12: Safe registration, proxy limits, documentation and final verification

**Files:**
- Create: `scripts/register_moysklad_order_chat_webhook.py`
- Modify: `scripts/check.ps1`
- Modify: `conf.d/default.conf`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/LOCAL_DEVELOPMENT.md`
- Modify: `docs/ENVIRONMENT.md`
- Modify: `docs/SECURITY_NOTES.md`
- Modify: `tests/test_order_chat_webhook.py`

**Interfaces:**
- Produces: `python scripts/register_moysklad_order_chat_webhook.py --base-url https://pixlogistic.com` as a non-mutating preview.
- Produces: explicit `--apply` idempotent creation of one `UPDATE/customerorder/FIELDS` webhook.
- Produces: NGINX order-upload limit `205m` and webhook `access_log off`.
- Produces: rollout, rollback, backup, staging verification and MinIO maintenance notes.

- [ ] **Step 1: Write a failing registration-plan test**

Append to `tests/test_order_chat_webhook.py`:

```python
from scripts.register_moysklad_order_chat_webhook import build_webhook_url, redact_webhook_url


def test_registration_url_uses_configured_secret_but_redaction_never_returns_it():
    url = build_webhook_url("https://pixlogistic.com/", "super-secret")

    assert url == "https://pixlogistic.com/api_v1/integration/webhooks/order-chat/super-secret"
    assert redact_webhook_url(url) == "https://pixlogistic.com/api_v1/integration/webhooks/order-chat/***"
    assert "super-secret" not in redact_webhook_url(url)
```

Make `scripts` importable with a minimal `scripts/__init__.py` only if Python import resolution requires it; include that file in the task commit.

- [ ] **Step 2: Run the registration test and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_webhook.py::test_registration_url_uses_configured_secret_but_redaction_never_returns_it -v
```

Expected: registration module is missing.

- [ ] **Step 3: Implement dry-run-first idempotent registration**

Create `scripts/register_moysklad_order_chat_webhook.py`:

```python
import argparse
import asyncio
from urllib.parse import urlparse

from config import get_settings
from db.moysklad_order_chat_repository import MoySkladOrderChatRepository


def build_webhook_url(base_url: str, secret: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("base URL must be an https origin without query or fragment")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{origin}/api_v1/integration/webhooks/order-chat/{secret}"


def redact_webhook_url(url: str) -> str:
    return url.rsplit("/", 1)[0] + "/***"


async def run(base_url: str, apply: bool) -> int:
    settings = get_settings()
    chat = settings.require_order_chat()
    target = build_webhook_url(base_url, chat.webhook_secret)
    repository = MoySkladOrderChatRepository(settings)
    existing = await repository.list_webhooks()
    found = any(
        item.get("entityType") == "customerorder"
        and item.get("action") == "UPDATE"
        and item.get("url") == target
        for item in existing
    )
    if found:
        print(f"Webhook already exists: {redact_webhook_url(target)}")
        return 0
    if not apply:
        print(f"Dry run: would create UPDATE/customerorder/FIELDS at {redact_webhook_url(target)}")
        return 0
    await repository.create_webhook(target)
    print(f"Webhook created: {redact_webhook_url(target)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args.base_url, args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
```

The script never accepts the secret on the command line and never prints the unredacted target. It performs a live list request even in dry-run, so run it only in the deliberate integration phase.

- [ ] **Step 4: Add exact NGINX routing before the generic API location**

Add to the TLS server in `conf.d/default.conf`:

```nginx
    location ^~ /api_v1/integration/webhooks/order-chat/ {
        access_log off;
        proxy_pass http://backend;
    }

    location ^~ /api_v1/chat/orders/ {
        client_max_body_size 205m;
        proxy_pass http://backend;
    }
```

Keep the existing WebSocket upgrade location and generic `/api_v1/` proxy. The `205m` cap allows ten 20 MiB multipart parts plus boundary overhead; application validation still enforces each file and count.

- [ ] **Step 5: Extend lint coverage and operator documentation**

Add every new Python module and both changed chat/notification route modules to `$ruffTargets` in `scripts/check.ps1`.

Document these exact flows:

- `docs/ARCHITECTURE.md`: site → immutable DB/MinIO → outbox → MoySklad comment/files; MoySklad webhook → outbox → DB/MinIO → Redis/WebSocket/site; Telegram side notifications.
- `docs/ENVIRONMENT.md`: all 11 variables, defaults, secret/non-secret classification, feature flag and `MOYSKLAD_PASSWORD` spelling.
- `docs/LOCAL_DEVELOPMENT.md`: build/start PostgreSQL, Redis and source-built MinIO; console URL; feature-off offline checks; local fake-only tests.
- `docs/SECURITY_NOTES.md`: URL-path secret redaction, rotate webhook secret, MinIO credentials, append-only trigger, owner checks, filename/signature policy, volume/database backups, AGPL review and archived upstream risk.
- `README.md`: short feature-disabled local start note and links to detailed docs.

Add this production rollout runbook without executing it:

1. Back up PostgreSQL and the MinIO volume; record restore commands and retention owner.
2. Deploy code/containers with `ENABLE_MOYSKLAD_ORDER_CHAT=false`; build the pinned MinIO source image and scan it.
3. Inspect `alembic history`, the active database host/name without printing password, and migration SQL; obtain explicit approval before `alembic upgrade c8f2a4e6d901`.
4. Start MinIO, verify health and bucket persistence across restart.
5. Set production MinIO/webhook secrets, enable the feature and restart backend; verify `/api_v1/health` and an authenticated order history request.
6. Run registration script without `--apply`, review the redacted plan, then obtain approval and rerun with `--apply`.
7. In a staging order, send site text/photo/PDF, verify comment/file copies and Telegram group alert; reply with text and `[КЛИЕНТ]` file in MoySklad, verify site realtime/history/client Telegram.
8. Verify a second client receives `404`, a manager internal file is hidden, repeated webhook `requestId` does not duplicate, and two tabs both receive the reply.

Rollback: disable feature flag, disable/delete only the exact registered webhook after explicit approval, keep PostgreSQL tables and MinIO volume intact, and continue existing general support. Do not downgrade the append-only migration during incident rollback.

- [ ] **Step 6: Run registration tests and static checks GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_order_chat_webhook.py -v
& ".\.venv\Scripts\python.exe" -m ruff check scripts/register_moysklad_order_chat_webhook.py
docker compose -f local-docker-compose.yml config --quiet
docker compose -f docker-compose.yml config --quiet
git diff --check
```

Expected: registration/redaction tests PASS; no script is run against MoySklad and no migration is applied.

- [ ] **Step 7: Run the full backend verification matrix after the final backend edit**

From `pix_backend`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
& ".\.venv\Scripts\python.exe" -m alembic history
& ".\.venv\Scripts\python.exe" -c "from config import Settings; from main import create_app; app=create_app(Settings(_env_file=None, app_env='test')); print(app.title)"
git diff --check
git status --short
```

Expected: Ruff and all pytest tests PASS, migration has one head, fresh feature-disabled application import prints `Pix Logistic API`, and only intentional files plus pre-existing user-owned changes are present. No live external service is contacted.

- [ ] **Step 8: Build the pinned MinIO image and verify local persistence**

This step needs network access for the pinned Git source and Go modules:

```powershell
docker compose -f local-docker-compose.yml build minio
docker compose -f local-docker-compose.yml up -d minio
docker compose -f local-docker-compose.yml ps minio
```

Expected: container becomes healthy. Upload a disposable test object through a small SDK smoke test, restart only the MinIO container, and verify the object still exists; delete only that exact disposable object afterward. Do not delete the named volume.

- [ ] **Step 9: Run the full frontend verification matrix after the final frontend edit**

From `../pix_frontend_v2`:

```powershell
npm.cmd run lint
npm.cmd run check:api-url
npm.cmd run test:unit
npx.cmd playwright test tests/order-chat.spec.ts
npm.cmd run build
npm.cmd run test:e2e
npm.cmd run check
git diff --check
git status --short
```

Expected: lint/API URL guard/unit/build/all Playwright/full check PASS. If Google Fonts cannot be downloaded because the environment blocks outbound network, record the exact build failure while retaining successful source, unit and local browser evidence; do not claim full check success.

- [ ] **Step 10: Review cross-repository contracts and commit operations/docs**

From `pix_backend`, compare all public paths, DTO field names, WebSocket query parameters, file limits and feature variables against the frontend diff and this plan. Then:

```powershell
git add scripts/register_moysklad_order_chat_webhook.py scripts/check.ps1 conf.d/default.conf README.md docs/ARCHITECTURE.md docs/LOCAL_DEVELOPMENT.md docs/ENVIRONMENT.md docs/SECURITY_NOTES.md tests/test_order_chat_webhook.py
git commit -m "docs: add order chat rollout runbook"
```

Do not stage tracked `__pycache__`, unrelated worktree changes, secrets, production URLs containing the webhook secret, or generated test artifacts.

## External References Used During Implementation

- MoySklad webhook payload, `requestId` retry semantics, 1.5-second response limit and `UPDATE/customerorder/FIELDS`: `https://dev.moysklad.ru/doc/api/remap/1.2/#vebhuki`.
- MoySklad special file resources, Base64 upload, 10 files per request and 100 files per entity: `https://dev.moysklad.ru/doc/api/remap/1.2/#fajly`.
- MinIO source-only/archived status and source build guidance: `https://github.com/minio/minio`.
- Pinned security release: `https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z`.
- Python SDK pin: `https://pypi.org/project/minio/7.2.20/`.
