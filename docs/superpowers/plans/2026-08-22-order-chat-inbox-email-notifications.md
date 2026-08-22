# Order Chat Inbox and Email Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give customers actionable order-message notifications, give MoySklad operators a persistent multi-order inbox with global unread state, and deliver one durable recipient email for every new order-chat message.

**Architecture:** Keep PostgreSQL as the source of truth. Extend `order_chat_state` for inbox projections, insert chat/email/notification side effects in the same message transaction, deliver email through a separately claimed PostgreSQL outbox, and use Redis WebSockets only as post-commit invalidation/summary signals. The website consumes the existing customer notification stream; the extension keeps an always-mounted iframe with separate inbox and selected-room lifecycles.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, Alembic/PostgreSQL, Redis, requests/SMTP.BZ, Next.js 14, React 18, TypeScript, Chrome Manifest V3, Vitest, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-08-22-order-chat-inbox-email-notifications-design.md`

## Global Constraints

- Work on `codex/order-chat-inbox-email-notifications` in the backend and a `codex/` feature branch in `../pix_frontend_v2`; never stage or discard unrelated dirty files.
- Keep route handlers thin, all environment reads in `config.py`, message decisions in `manager/`, and persistence in repositories.
- Preserve the current order-scoped room WebSocket and all old extension REST contracts during rollout.
- Never log secrets, recipient addresses, message bodies, provider response bodies, attachment filenames, or object keys.
- Never contact SMTP.BZ in tests. Inject a fake sender and fake clock/sleep boundary.
- Do not run production Alembic automatically. Deployment requires checking the production database URL, making and verifying a backup, reviewing the exact revision, and obtaining explicit approval immediately before applying it.
- Do not delete historical chat data. The new migration is additive and historical operator unread starts at zero.
- After every task, run the focused RED/GREEN command shown below and commit only the listed files.

---

## Task 1: Add backend contracts, models, and settings

**Files:**

- Create: `tests/test_order_chat_inbox_contracts.py`
- Modify: `db/models/order_chat.py`
- Modify: `db/schemas/chat.py`
- Modify: `config.py`
- Modify: `.env.example`

**Interfaces:**

- Produces `OrderChatEmailSettings`, inbox response schemas, inbox event schemas, and SQLAlchemy declarations used by Tasks 2–9.
- Consumes no new runtime integration; email remains disabled by default.

- [ ] **Step 1: Write failing contract tests**

Add tests that assert the state/outbox columns, checks, defaults, Pydantic bounds, and safe local defaults. Cover `limit`-independent schema validation, non-negative unread values, `recipient_kind`, and the disabled email feature not requiring SMTP configuration.

Use these public shapes:

```python
@dataclass(frozen=True, slots=True)
class OrderChatEmailSettings:
    manager_email: str
    public_site_url: str
    smtp_bz_token: str


class ConversationLastMessage(BaseModel):
    id: UUID
    sender_kind: SenderKind
    sender_label: str
    message: str
    created_at: datetime
    attachment_count: int = Field(ge=0)


class ConversationSummary(BaseModel):
    order_id: UUID
    order_name: str
    last_message: ConversationLastMessage
    unread_count: int = Field(ge=0)


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    next_before: UUID | None
    total_unread: int = Field(ge=0)


class OperatorReadResponse(BaseModel):
    order_id: UUID
    unread_count: Literal[0] = 0
    total_unread: int = Field(ge=0)


class ConversationUpdatedEvent(BaseModel):
    type: Literal["conversation_updated"] = "conversation_updated"
    item: ConversationSummary
    total_unread: int = Field(ge=0)
```

Add these settings fields:

```python
enable_order_chat_email_notifications: bool = False
order_chat_manager_email: str | None = None
pix_public_site_url: str | None = None
```

`Settings.require_order_chat_email()` must return the frozen settings object and obtain the token through the existing `mailersend_token` compatibility field.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_order_chat_inbox_contracts.py -q"`

Expected: imports or assertions fail because the new contracts do not exist.

- [ ] **Step 3: Implement the minimal declarations**

Extend `OrderChatState` with `order_name`, `latest_message_id`, and `operator_unread_count`. Add `OrderChatEmailOutbox` with a unique/FK `message_id`, status/recipient checks, attempt/timestamp fields, and `ix_order_chat_email_outbox_due` on `(status, available_at)`. Add the schemas exactly above.

Add non-secret `.env.example` keys with email delivery disabled and blank values:

```dotenv
ENABLE_ORDER_CHAT_EMAIL_NOTIFICATIONS=false
ORDER_CHAT_MANAGER_EMAIL=
PIX_PUBLIC_SITE_URL=
```

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run the command from Step 2.

Expected: all tests in `test_order_chat_inbox_contracts.py` pass without network access.

- [ ] **Step 5: Commit only Task 1 files**

```powershell
git add -- .env.example config.py db/models/order_chat.py db/schemas/chat.py tests/test_order_chat_inbox_contracts.py
git commit -m "feat: add order chat inbox contracts"
```

## Task 2: Add the additive PostgreSQL migration

**Files:**

- Create: `alembic/versions/f4c8a2d6b901_order_chat_inbox_email.py`
- Create: `tests/test_order_chat_inbox_migration.py`
- Modify: `scripts/check.ps1`

**Interfaces:**

- Consumes the model names from Task 1.
- Produces revision `f4c8a2d6b901` with `down_revision = "e3b7c9d1a204"` and makes it the single expected head.

- [ ] **Step 1: Write failing migration tests**

Test the exact revision chain, additive columns/checks/FK/unique/index operations, the PostgreSQL latest-message backfill, and downgrade ordering. Assert that no network lookup, data deletion, or historical unread increment exists.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_order_chat_inbox_migration.py -q"`

Expected: the revision cannot be imported.

- [ ] **Step 3: Implement the revision**

Create the state columns nullable first, create the email outbox, and backfill only the latest pointer with PostgreSQL SQL:

```sql
UPDATE order_chat_state AS state
SET latest_message_id = latest.id,
    updated_at = GREATEST(state.updated_at, latest.created_at)
FROM (
    SELECT DISTINCT ON (order_id) order_id, id, created_at
    FROM order_chat_message
    ORDER BY order_id, created_at DESC, id DESC
) AS latest
WHERE latest.order_id = state.order_id
```

Add `operator_unread_count` with server default `0`, a non-negative check, and keep that default. Do not fetch `order_name` during the migration. Downgrade must drop the outbox before removing the state columns and must not delete chat messages.

Update `scripts/check.ps1` to expect exactly one Alembic head at `f4c8a2d6b901` and include the new revision in its tracked migration list.

- [ ] **Step 4: Run migration verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_order_chat_inbox_migration.py -q"
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m alembic heads"
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m alembic history -r e3b7c9d1a204:head"
```

Expected: tests pass; one head is `f4c8a2d6b901`; history shows it directly after `e3b7c9d1a204`. Do not run `alembic upgrade` against production.

- [ ] **Step 5: Commit only Task 2 files**

```powershell
git add -- alembic/versions/f4c8a2d6b901_order_chat_inbox_email.py scripts/check.ps1 tests/test_order_chat_inbox_migration.py
git commit -m "feat: migrate order chat inbox state"
```

## Task 3: Make message side effects atomic and idempotent

**Files:**

- Create: `tests/test_order_chat_delivery_repository.py`
- Modify: `db/order_chat_repository.py`
- Modify: `tests/test_order_chat_repository.py`

**Interfaces:**

- Consumes `OrderChatEmailOutbox` and `OrderChatState` from Task 1.
- Produces atomic client/manager write methods used by `OrderChatService` in Task 7.

- [ ] **Step 1: Write failing repository tests**

Cover these cases with a transactional fake or test session factory:

1. Client insert stores message/attachments, updates `latest_message_id` and `order_name`, increments unread, and inserts one manager outbox row.
2. Manager insert stores the same projection, does not increment operator unread, creates one `ORDER_MESSAGE`, and inserts one client outbox row.
3. Replaying an existing `external_key` returns the canonical row without repeating unread, notification, or outbox effects.
4. State/client mismatch rolls back everything.
5. Email disabled (`email_delivery=None`) still commits chat and notification state without an outbox row.

Use one value object rather than raw recipient arguments:

```python
@dataclass(frozen=True, slots=True)
class NewEmailDelivery:
    recipient_email: str
    recipient_kind: Literal["client", "manager"]
```

Extend the write signatures:

```python
async def create_client_message_with_delivery(
    self, *, message_id: UUID, order_id: UUID, client_id: UUID,
    body: str, source: str, order_name: str | None = None,
    email_delivery: NewEmailDelivery | None = None,
    attachments: tuple[NewAttachment, ...] = (),
) -> StoredMessage: ...

async def create_manager_message_with_notification(
    self, *, message_id: UUID, order_id: UUID, client_id: UUID,
    body: str, source: str, order_name: str | None = None,
    email_delivery: NewEmailDelivery | None = None,
    attachments: tuple[NewAttachment, ...] = (),
    external_key: str | None = None,
    created_at: datetime | None = None,
) -> StoredMessage: ...
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_order_chat_delivery_repository.py -q"`

Expected: the client delivery method and atomic projection behavior are missing.

- [ ] **Step 3: Implement one locked-state transaction per message**

After `_insert_message` reports `inserted=True`, lock `order_chat_state` with `FOR UPDATE`, verify `client_id`, insert attachments, apply sender-specific side effects, and insert the unique outbox row when configured. Update `updated_at=func.now()` on every inserted message. Keep duplicate replay free of repeated side effects.

Factor only session-local helpers such as `_locked_state`, `_update_latest_state`, and `_add_email_delivery`; do not open nested sessions. Update the existing repository transaction spy test to model the locked state and assert the added projection/outbox operations.

- [ ] **Step 4: Run focused and existing repository tests**

Run:

```powershell
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_order_chat_delivery_repository.py tests/test_order_chat_repository.py -q"
```

Expected: new atomic tests and existing pagination/attachment tests pass.

- [ ] **Step 5: Commit only Task 3 files**

```powershell
git add -- db/order_chat_repository.py tests/test_order_chat_delivery_repository.py tests/test_order_chat_repository.py
git commit -m "feat: persist order chat delivery atomically"
```

## Task 4: Add inbox projection queries and global read state

**Files:**

- Create: `tests/test_order_chat_inbox_repository.py`
- Modify: `db/order_chat_repository.py`

**Interfaces:**

- Produces stable conversation-page records, total unread, lazy name updates, and an idempotent read mutation.
- Consumes the latest-message pointer maintained by Task 3.

- [ ] **Step 1: Write failing query tests**

Test newest-first ordering by `(created_at, id)`, exclusion of empty states, `limit + 1` cursor behavior, invalid cursor as `OrderChatNotFound`, attachment counts without filenames, summed unread, idempotent clearing, and a missing-state read as not found.

Use this repository record:

```python
@dataclass(frozen=True, slots=True)
class StoredConversation:
    order_id: UUID
    order_name: str | None
    last_message: StoredMessage
    attachment_count: int
    unread_count: int
```

Add these methods:

```python
async def list_conversations(
    self, before: UUID | None, limit: int
) -> tuple[list[StoredConversation], UUID | None]: ...

async def total_operator_unread(self) -> int: ...
async def clear_operator_unread(self, order_id: UUID) -> int: ...
async def cache_order_name(self, order_id: UUID, order_name: str) -> None: ...
async def conversation(self, order_id: UUID) -> StoredConversation | None: ...
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_order_chat_inbox_repository.py -q"`

Expected: inbox methods do not exist.

- [ ] **Step 3: Implement set-based queries**

Join state to its pointed message and an attachment-count subquery. Resolve `before` from an `OrderChatMessage` and compare the latest message tuple. Lock only the selected state in `clear_operator_unread`; return the new global total after commit. `cache_order_name` must update only the named order and refresh `updated_at`.

- [ ] **Step 4: Run focused and existing repository tests**

Run the command from Task 3 Step 4 with `tests/test_order_chat_inbox_repository.py` added.

Expected: all repository suites pass.

- [ ] **Step 5: Commit only Task 4 files**

```powershell
git add -- db/order_chat_repository.py tests/test_order_chat_inbox_repository.py
git commit -m "feat: query operator chat inbox"
```

## Task 5: Build safe order-chat email templates and SMTP.BZ sender

**Files:**

- Create: `manager/order_chat_email.py`
- Create: `tests/test_order_chat_email.py`

**Interfaces:**

- Produces a synchronous, injectable sender used only through the dispatcher.
- Consumes no database session and never reads environment variables directly.

- [ ] **Step 1: Write failing template and sender tests**

Test both recipient subjects, 300-character Unicode truncation, HTML escaping, newline handling, empty-body fallback, attachment count, exact HTTPS links, form fields, authorization header, bounded timeout, and safe exception categories. Assert that the fake response body and recipient do not appear in logs/exceptions.

Define:

```python
@dataclass(frozen=True, slots=True)
class OrderChatEmailContent:
    recipient_email: str
    recipient_kind: Literal["client", "manager"]
    order_id: UUID
    order_name: str
    sender_label: str
    message: str
    attachment_count: int


@dataclass(frozen=True, slots=True)
class EmailEnvelope:
    recipient_email: str
    subject: str
    html: str
    text: str


class OrderChatEmailSender(Protocol):
    def send(self, envelope: EmailEnvelope) -> None: ...
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_order_chat_email.py -q"`

Expected: module import fails.

- [ ] **Step 3: Implement rendering and the blocking adapter**

`render_order_chat_email(content, public_site_url)` must use:

- manager subject `Новое сообщение клиента по заказу №{order_name}` and link `https://online.moysklad.ru/app/#customerorder/edit?id={order_id}`;
- client subject `Новое сообщение по заказу №{order_name}` and link `{public_site_url}/dashboard/orders/{order_id}?openChat=1#order-chat`.

Use `html.escape(..., quote=True)`, plain text for the text body, and no attachment names. `SmtpBzOrderChatEmailSender.send` calls `requests.post("https://api.smtp.bz/v1/smtp/send", ..., timeout=(3.05, 10))`, accepts only 2xx, and raises a safe typed error such as `OrderChatEmailSendError("timeout")` or `("provider_5xx")`.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run the command from Step 2.

Expected: all renderer/sender tests pass with the injected fake request function.

- [ ] **Step 5: Commit only Task 5 files**

```powershell
git add -- manager/order_chat_email.py tests/test_order_chat_email.py
git commit -m "feat: render order chat emails safely"
```

## Task 6: Implement PostgreSQL outbox claiming and dispatch

**Files:**

- Create: `db/order_chat_email_repository.py`
- Create: `manager/order_chat_email_dispatcher.py`
- Create: `dependecies/order_chat_email.py`
- Create: `tests/test_order_chat_email_outbox.py`
- Create: `tests/test_order_chat_email_dispatcher.py`

**Interfaces:**

- Consumes outbox rows from Task 3 and the sender from Task 5.
- Produces a lifecycle-managed async dispatcher for Task 9.

- [ ] **Step 1: Write failing outbox tests**

Cover `FOR UPDATE SKIP LOCKED`, pending and expired-processing eligibility, atomically changing claimed rows to `processing`, canonical joined content, success to `sent`, retry scheduling, tenth failure to `dead`, and safe `last_error` truncation. Verify that attachment aggregation returns only a count.

Use:

```python
@dataclass(frozen=True, slots=True)
class ClaimedOrderChatEmail:
    outbox_id: UUID
    attempts: int
    content: OrderChatEmailContent


async def claim_due(self, *, now: datetime, limit: int, lease_before: datetime) -> list[ClaimedOrderChatEmail]: ...
async def mark_sent(self, outbox_id: UUID, *, sent_at: datetime) -> None: ...
async def mark_failed(self, outbox_id: UUID, *, category: str, available_at: datetime | None, dead: bool) -> None: ...
```

- [ ] **Step 2: Write failing dispatcher tests**

With fake repository/sender/clock, verify `asyncio.to_thread` isolation, successful marking, retry delays `[60, 300, 900, 3600, 21600]` seconds with the last value capped/reused, ten-attempt death, polling wakeup, and graceful stop not claiming new rows.

- [ ] **Step 3: Run both focused suites and confirm RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_order_chat_email_outbox.py tests/test_order_chat_email_dispatcher.py -q"
```

Expected: repository and dispatcher imports fail.

- [ ] **Step 4: Implement claim/status repository and dispatcher**

Claim at most 20 rows per poll with a five-minute lease. The joined content uses the cached order name or the same neutral shortened-UUID label as the inbox when the name is still absent. The dispatcher renders from canonical message/state data, invokes the blocking sender through `asyncio.to_thread`, and stores only the safe error category. Use an `asyncio.Event` so shutdown and new-work wakeups do not wait for the normal poll interval.

Expose `build_order_chat_email_dispatcher(settings: OrderChatEmailSettings)` from the dependency module. It must construct the repository and SMTP sender without a global network action.

- [ ] **Step 5: Run both focused suites and confirm GREEN**

Run the command from Step 3.

Expected: both suites pass.

- [ ] **Step 6: Commit only Task 6 files**

```powershell
git add -- db/order_chat_email_repository.py manager/order_chat_email_dispatcher.py dependecies/order_chat_email.py tests/test_order_chat_email_outbox.py tests/test_order_chat_email_dispatcher.py
git commit -m "feat: dispatch order chat email outbox"
```

## Task 7: Orchestrate inbox, unread, order names, and email jobs

**Files:**

- Create: `manager/operator_inbox_realtime.py`
- Create: `dependecies/operator_inbox.py`
- Create: `tests/test_operator_chat_inbox_service.py`
- Modify: `manager/order_chat.py`
- Modify: `dependecies/order_chat.py`
- Modify: `db/schemas/chat.py`
- Modify: `tests/test_operator_order_chat_service.py`
- Modify: `tests/test_order_chat_service.py`

**Interfaces:**

- Consumes Tasks 3–6.
- Produces service methods and one global Redis inbox channel for the routes in Task 8.

- [ ] **Step 1: Write failing service tests**

Test:

1. Customer send captures the live order name, queues manager email only when enabled, increments unread, publishes room and inbox summaries after commit, and does not publish customer notification count.
2. Manager send captures customer email, queues customer email only, leaves operator unread unchanged, and publishes the customer notification count.
3. Conversation listing uses repository order, lazily hydrates missing names with maximum concurrency five, caches successes, and falls back to `Заказ …{last 8 UUID chars}` when MoySklad is temporarily unavailable.
4. Opening/marking read returns the new total and publishes a zero-unread summary.
5. Redis publication failures do not fail the committed message.

Change operator resolution to return both identity and metadata:

```python
@dataclass(frozen=True, slots=True)
class ResolvedOperatorOrder:
    client: User
    order_name: str | None


async def list_operator_conversations(
    self, before: UUID | None, limit: int
) -> ConversationPage: ...

async def mark_operator_read(self, order_id: UUID) -> OperatorReadResponse: ...
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_operator_chat_inbox_service.py tests/test_operator_order_chat_service.py -q"
```

Expected: inbox orchestration and metadata result are missing.

- [ ] **Step 3: Implement service orchestration**

Extract MoySklad `order["name"]` only when it is a non-empty string. Pass `NewEmailDelivery(manager_email, "manager")` for client messages and `NewEmailDelivery(client.email, "client")` for manager messages when enabled. Do not call the sender in the request path.

Add `OperatorInboxRealtime(RedisChatRealtime)` with `channel_prefix = "order-chat:operator-inbox:"` and use room key `global`. Build it as a cached dependency. `_publish_inbox_update(order_id)` reloads the committed summary and total, then publishes `ConversationUpdatedEvent` best effort.

- [ ] **Step 4: Run focused and existing chat service tests**

Run:

```powershell
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_operator_chat_inbox_service.py tests/test_operator_order_chat_service.py tests/test_order_chat_service.py -q"
```

Expected: all service tests pass.

- [ ] **Step 5: Commit only Task 7 files**

```powershell
git add -- manager/operator_inbox_realtime.py dependecies/operator_inbox.py manager/order_chat.py dependecies/order_chat.py db/schemas/chat.py tests/test_operator_chat_inbox_service.py tests/test_operator_order_chat_service.py tests/test_order_chat_service.py
git commit -m "feat: orchestrate operator chat inbox"
```

## Task 8: Expose operator inbox REST/WebSocket and customer notification context

**Files:**

- Create: `tests/test_operator_inbox_api.py`
- Create: `tests/test_operator_inbox_websocket.py`
- Modify: `routes/operator_chat.py`
- Modify: `routes/notifications.py`
- Modify: `db/order_chat_repository.py`
- Modify: `tests/test_notifications_api.py`

**Interfaces:**

- Produces the public backend contracts consumed by the website and extension.
- Reuses `X-Pix-Chat-Secret` and the existing strict first-frame socket authentication.

- [ ] **Step 1: Write failing REST tests**

Cover `GET /api_v1/chat/operator/conversations` default/max limit, cursor passthrough, auth failures, disabled capability, and serialized page; cover idempotent `POST /api_v1/chat/operator/orders/{order_id}/read`, invalid UUID, and missing conversation. Verify notification JSON adds `order_name` and `attachment_count` while preserving `message`, `to_chat_room_id`, and all old fields.

- [ ] **Step 2: Write failing inbox WebSocket tests**

Cover missing/disabled secret close codes, malformed/late first frames, successful `{"type":"authenticate","secret":"..."}`, registration on global room, event delivery, and disconnect cleanup. The socket must reject message-send frames and never accept a room or secret query parameter.

- [ ] **Step 3: Run focused API suites and confirm RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_operator_inbox_api.py tests/test_operator_inbox_websocket.py tests/test_notifications_api.py -q"
```

Expected: routes and notification context fields are absent.

- [ ] **Step 4: Implement thin routes**

Add:

```python
@router.get("/conversations", response_model=ConversationPage, dependencies=operator_rest_dependencies)
async def list_operator_conversations(before: UUID | None = None, limit: Annotated[int, Query(ge=1, le=50)] = 50, service: OrderChatService = Depends(get_order_chat_service)): ...

@router.post("/orders/{order_id}/read", response_model=OperatorReadResponse, dependencies=operator_rest_dependencies)
async def mark_operator_order_read(order_id: str, service: OrderChatService = Depends(get_order_chat_service)): ...

@router.websocket("/inbox/ws")
async def operator_inbox_websocket(websocket: WebSocket): ...
```

Factor shared authenticated-socket setup without changing `/chat/operator/ws`. Add one repository context query for customer notification serialization; do not issue MoySklad requests from `routes/notifications.py` for chat names.

- [ ] **Step 5: Run focused and existing transport suites**

Run:

```powershell
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_operator_inbox_api.py tests/test_operator_inbox_websocket.py tests/test_operator_chat_api.py tests/test_operator_chat_websocket.py tests/test_notifications_api.py -q"
```

Expected: all new and backward-compatibility transport tests pass.

- [ ] **Step 6: Commit only Task 8 files**

```powershell
git add -- routes/operator_chat.py routes/notifications.py db/order_chat_repository.py tests/test_operator_inbox_api.py tests/test_operator_inbox_websocket.py tests/test_notifications_api.py
git commit -m "feat: expose operator conversation inbox"
```

## Task 9: Wire production validation and application lifecycle

**Files:**

- Modify: `manager/production_config.py`
- Modify: `main.py`
- Modify: `tests/test_production_config.py`
- Modify: `tests/test_app.py`

**Interfaces:**

- Starts operator inbox realtime whenever normal realtime is active.
- Starts the email dispatcher only when `ENABLE_ORDER_CHAT_EMAIL_NOTIFICATIONS=true`, independent of `ENABLE_SCHEDULER`.

- [ ] **Step 1: Write failing configuration/lifespan tests**

Test that production email delivery requires a syntactically valid manager email, SMTP token, and an HTTPS origin with no path/query; disabled delivery does not require them. Test startup/shutdown order with fakes, scheduler independence, test-environment no-network behavior, and dispatcher cleanup when lifespan startup later fails.

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_production_config.py tests/test_app.py -q"
```

Expected: validation and lifecycle assertions fail.

- [ ] **Step 3: Implement preflight and lifespan wiring**

Extend `_validate_order_chat` only when email delivery is enabled:

```python
if settings.enable_order_chat_email_notifications:
    if not _is_email_address(settings.order_chat_manager_email):
        _add(issues, "ORDER_CHAT_MANAGER_EMAIL", "must be a valid email address")
    _require_secret(issues, "MAILERSEND_TOKEN", settings.mailersend_token)
    if not _is_https_origin(settings.pix_public_site_url or ""):
        _add(issues, "PIX_PUBLIC_SITE_URL", "must be an HTTPS origin")
```

Start/stop `get_operator_inbox_realtime()` beside the existing chat/notification realtimes. Build and start the dispatcher after settings validation and before yielding; stop it before realtime shutdown. Do not tie it to APScheduler.

- [ ] **Step 4: Run focused tests and import/health verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\python.exe -m pytest tests/test_production_config.py tests/test_app.py -q"
powershell -ExecutionPolicy Bypass -Command "$env:APP_ENV='test'; .\.venv\Scripts\python.exe -c \"import main; print(main.app.title)\""
```

Expected: tests pass and the fresh process prints the application title without contacting production.

- [ ] **Step 5: Commit only Task 9 files**

```powershell
git add -- manager/production_config.py main.py tests/test_production_config.py tests/test_app.py
git commit -m "feat: run order chat email dispatcher"
```

## Task 10: Make website notifications open the correct chat

**Files (frontend repository):**

- Create: `../pix_frontend_v2/src/features/notifications/orderMessageNotification.ts`
- Create: `../pix_frontend_v2/src/features/notifications/orderMessageNotification.test.ts`
- Create: `../pix_frontend_v2/src/features/order-chat/openChatIntent.ts`
- Create: `../pix_frontend_v2/src/features/order-chat/openChatIntent.test.ts`
- Modify: `../pix_frontend_v2/src/routes/routes.tsx`
- Modify: `../pix_frontend_v2/src/app/dashboard/notifications/page.tsx`
- Modify: `../pix_frontend_v2/src/app/dashboard/orders/[id]/page.tsx`
- Modify: `../pix_frontend_v2/src/app/dashboard/orders/[id]/OrderChatPanel.tsx`

**Interfaces:**

- Consumes backend `order_name`, `message`, `attachment_count`, and `to_chat_room_id`.
- Produces `/dashboard/orders/{id}?openChat=1#order-chat` behavior without changing direct order-page layout.

- [ ] **Step 1: Create the frontend feature branch**

From `../pix_frontend_v2`, inspect status, preserve existing changes, and create `codex/order-chat-inbox-email-notifications` if it does not already exist.

- [ ] **Step 2: Write failing pure unit tests**

Test:

```typescript
export function orderMessageTitle(orderName: string | undefined): string;
export function orderMessagePreview(message: string | undefined, attachmentCount: number | undefined): string;
export function orderMessageHref(orderId: string): string;
export function hasOpenChatIntent(search: URLSearchParams, hash: string): boolean;
```

Expected title is `Новое сообщение по заказу №12345`; whitespace-only body with attachments is `Прикреплены файлы`; href includes the exact query and hash.

- [ ] **Step 3: Run unit tests and confirm RED**

Run from frontend: `npm.cmd run test:unit -- --run src/features/notifications/orderMessageNotification.test.ts src/features/order-chat/openChatIntent.test.ts`

Expected: helper imports fail.

- [ ] **Step 4: Implement notification presentation and one-shot chat intent**

Extend `getNotificationsType` with `order_name?: string` and `attachment_count?: number`. Use the helper for label, preview, and navigation after awaiting/serializing the existing read mutation.

Read `useSearchParams()` on the order page and pass `initiallyExpanded` to `OrderChat`. In `OrderChatPanel.tsx`, give the section `id="order-chat"`, expand on the one-shot prop, `scrollIntoView({block: "start"})`, focus a `tabIndex={-1}` heading, and remove only `openChat=1` from browser history after handling it. Preserve other query values and the `#order-chat` anchor.

- [ ] **Step 5: Run frontend unit, lint, and build checks**

Run from frontend:

```powershell
npm.cmd run test:unit -- --run src/features/notifications/orderMessageNotification.test.ts src/features/order-chat/openChatIntent.test.ts
npm.cmd run lint
npm.cmd run build
```

Expected: focused tests, lint, and production build pass.

- [ ] **Step 6: Commit only Task 10 frontend files**

```powershell
git add -- src/features/notifications/orderMessageNotification.ts src/features/notifications/orderMessageNotification.test.ts src/features/order-chat/openChatIntent.ts src/features/order-chat/openChatIntent.test.ts src/routes/routes.tsx 'src/app/dashboard/notifications/page.tsx' 'src/app/dashboard/orders/[id]/page.tsx' 'src/app/dashboard/orders/[id]/OrderChatPanel.tsx'
git commit -m "feat: open order chat from notifications"
```

## Task 11: Keep the extension panel mounted and secure its navigation bridge

**Files (frontend repository):**

- Create: `../pix_frontend_v2/moysklad-chat-extension/src/bridge.ts`
- Create: `../pix_frontend_v2/moysklad-chat-extension/src/bridge.test.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/route.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/route.test.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/content/panelHost.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/content.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/panel/main.tsx`

**Interfaces:**

- Produces an always-mounted iframe and exact validated bridge messages.
- Does not add host permissions or accept arbitrary URLs.

- [ ] **Step 1: Write failing route and bridge tests**

Change the host contract to:

```typescript
export interface PanelHost {
  mount(): void;
  updateRoute(orderId: string | null): void;
  destroy(): void;
}
```

Test exact parsing for:

```typescript
type RouteContextMessage = {
  source: "pix-order-chat-extension-host";
  type: "route_context";
  orderId: string | null;
};

type NavigateOrderMessage = {
  source: "pix-order-chat-extension";
  type: "navigate_order";
  orderId: string;
};

type PanelReadyMessage = {
  source: "pix-order-chat-extension";
  type: "panel_ready";
};
```

Reject extra keys, non-UUID IDs, foreign origins, and messages not from the mounted iframe window. Test exact target hash creation.

- [ ] **Step 2: Run extension unit tests and confirm RED**

Run from frontend: `npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- --run src/route.test.ts src/bridge.test.ts`

Expected: new contract tests fail.

- [ ] **Step 3: Implement persistent host lifecycle**

Mount once on any supported MoySklad `/app/*` page. Do not put `order_id` in the iframe URL. On iframe `panel_ready`, and on every route change, post the current route context to the exact extension origin. For `navigate_order`, validate source/origin/shape/UUID and assign only:

```typescript
window.location.hash = `customerorder/edit?id=${orderId.toLowerCase()}`;
```

Keep the existing validated resize handling. The panel bootstrap owns route-context state and passes it to `App`.

- [ ] **Step 4: Run extension unit/type/build checks**

Run from frontend:

```powershell
npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- --run src/route.test.ts src/bridge.test.ts
npm.cmd run typecheck --workspace pix-moysklad-chat-extension
npm.cmd run build --workspace pix-moysklad-chat-extension
```

Expected: unit tests, typecheck, and extension build pass without manifest permission changes.

- [ ] **Step 5: Commit only Task 11 frontend files**

```powershell
git add -- moysklad-chat-extension/src/bridge.ts moysklad-chat-extension/src/bridge.test.ts moysklad-chat-extension/src/route.ts moysklad-chat-extension/src/route.test.ts moysklad-chat-extension/src/content/panelHost.ts moysklad-chat-extension/src/content.ts moysklad-chat-extension/src/panel/main.tsx
git commit -m "feat: keep MoySklad chat panel available"
```

## Task 12: Add extension inbox API, realtime, and state model

**Files (frontend repository):**

- Create: `../pix_frontend_v2/moysklad-chat-extension/src/panel/inboxModel.ts`
- Create: `../pix_frontend_v2/moysklad-chat-extension/src/panel/inboxModel.test.ts`
- Create: `../pix_frontend_v2/moysklad-chat-extension/src/panel/inboxSocket.ts`
- Create: `../pix_frontend_v2/moysklad-chat-extension/src/panel/inboxSocket.test.ts`
- Create: `../pix_frontend_v2/moysklad-chat-extension/src/panel/useOperatorInbox.ts`
- Create: `../pix_frontend_v2/moysklad-chat-extension/src/panel/useOperatorInbox.test.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/panel/api.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/panel/api.test.ts`

**Interfaces:**

- Consumes Task 8 REST/WS contracts.
- Produces merged/paginated inbox state independent of the selected room hook.

- [ ] **Step 1: Write failing API/model tests**

Add TypeScript equivalents of `ConversationSummary`, `ConversationPage`, and `OperatorReadResponse`. Test deterministic merge/reorder, no duplicates, unread total replacement from server, pagination cursor, malformed item rejection, focus reload, and abort of stale loads.

Extend `OperatorChatApi`:

```typescript
listConversations(before?: string, signal?: AbortSignal): Promise<ConversationPage>;
markRead(orderId: string, signal?: AbortSignal): Promise<OperatorReadResponse>;
```

- [ ] **Step 2: Write failing inbox socket tests**

Model the existing room socket but target `/api_v1/chat/operator/inbox/ws`, send the secret only in the first frame, require `authenticated`, reconnect with capped backoff, and invoke a full-reload callback for reconnect or malformed events. Keep it connected regardless of collapsed panel state.

- [ ] **Step 3: Run focused extension tests and confirm RED**

Run from frontend:

```powershell
npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- --run src/panel/api.test.ts src/panel/inboxModel.test.ts src/panel/inboxSocket.test.ts src/panel/useOperatorInbox.test.ts
```

Expected: new APIs and inbox modules are missing.

- [ ] **Step 4: Implement inbox data lifecycle**

`useOperatorInbox({secret, onUnauthorized})` loads the first page after secret setup, exposes `loadOlder`/`reload`, maintains `totalUnread`, and applies `conversation_updated` by replacing/reordering the row. Reload on window focus and successful socket reconnect. Unauthorized REST or socket response clears the secret through the existing callback.

- [ ] **Step 5: Run focused tests and extension typecheck**

Run:

```powershell
npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- --run src/panel/api.test.ts src/panel/inboxModel.test.ts src/panel/inboxSocket.test.ts src/panel/useOperatorInbox.test.ts
npm.cmd run typecheck --workspace pix-moysklad-chat-extension
```

Expected: all focused tests and typecheck pass.

- [ ] **Step 6: Commit only Task 12 frontend files**

```powershell
git add -- moysklad-chat-extension/src/panel/inboxModel.ts moysklad-chat-extension/src/panel/inboxModel.test.ts moysklad-chat-extension/src/panel/inboxSocket.ts moysklad-chat-extension/src/panel/inboxSocket.test.ts moysklad-chat-extension/src/panel/useOperatorInbox.ts moysklad-chat-extension/src/panel/useOperatorInbox.test.ts moysklad-chat-extension/src/panel/api.ts moysklad-chat-extension/src/panel/api.test.ts
git commit -m "feat: add MoySklad conversation inbox data"
```

## Task 13: Build the extension inbox/detail experience and smoke test

**Files (frontend repository):**

- Create: `../pix_frontend_v2/moysklad-chat-extension/src/panel/ConversationList.tsx`
- Create: `../pix_frontend_v2/moysklad-chat-extension/src/panel/conversationNavigation.ts`
- Create: `../pix_frontend_v2/moysklad-chat-extension/src/panel/conversationNavigation.test.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/panel/App.tsx`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/panel/useOrderChat.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/src/panel/styles.css`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/tests/extension-smoke.spec.ts`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/package.json`
- Modify: `../pix_frontend_v2/package-lock.json`

**Interfaces:**

- Consumes persistent route context, inbox hook, room hook, and secure navigation bridge.
- Produces inbox/detail/back switching, global unread badges, and version `0.2.0` build output.

- [ ] **Step 1: Write failing navigation-state tests**

Test route-context auto-selection, selecting a row, Back returning only to inbox, selecting another order aborting old work, successful history load followed by `markRead`, non-empty text/files requiring confirmation, cancellation preserving the draft, and confirmed navigation clearing it.

- [ ] **Step 2: Run focused tests and confirm RED**

Run from frontend:

```powershell
npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- --run src/panel/conversationNavigation.test.ts src/panel/useOrderChat.test.ts
```

Expected: navigation model is missing and current room hook does not expose the required cancellation/read lifecycle.

- [ ] **Step 3: Implement inbox and detail UI**

The inbox header shows `totalUnread`; each row shows order name, sender, preview or `Прикреплены файлы`, attachment indicator/count, time, and an unread badge. Add loading, empty, retry, reconnecting, and unauthorized states.

Selecting a row posts `navigate_order`, enters detail, loads history, then calls `markRead`. Create the room socket only in detail. Back disposes room work but leaves the inbox socket active and does not post navigation. Use a Russian confirmation before abandoning a non-empty draft. Collapse must retain both current view and inbox connection.

- [ ] **Step 4: Rewrite the extension smoke fixture around inbox behavior**

Mock conversations, read, room history/send/attachments, and WebSocket authentication. Assert:

1. The launcher exists on the MoySklad dashboard.
2. Saving a valid secret loads the inbox.
3. Unread/order/attachment data render safely without HTML execution.
4. Selecting order two changes the exact host hash and opens its detail.
5. Successful history triggers `POST .../read`.
6. Back returns to inbox without changing the host hash.
7. A realtime summary reorders a row and updates the global badge.
8. Existing send retry and attachment download still work.

Bump extension package version to `0.2.0`; let the existing manifest build script derive the packaged version.

- [ ] **Step 5: Run the complete extension check**

Run from frontend: `npm.cmd run check --workspace pix-moysklad-chat-extension`

Expected: lint, typecheck, all unit tests, build, manifest validation, and Playwright smoke pass.

- [ ] **Step 6: Commit only Task 13 frontend files**

```powershell
git add -- moysklad-chat-extension/src/panel/ConversationList.tsx moysklad-chat-extension/src/panel/conversationNavigation.ts moysklad-chat-extension/src/panel/conversationNavigation.test.ts moysklad-chat-extension/src/panel/App.tsx moysklad-chat-extension/src/panel/useOrderChat.ts moysklad-chat-extension/src/panel/styles.css moysklad-chat-extension/tests/extension-smoke.spec.ts moysklad-chat-extension/package.json package-lock.json
git commit -m "feat: add MoySklad order chat inbox UI"
```

## Task 14: Document rollout, run cross-repository verification, and prepare artifacts

**Files:**

- Create: `docs/operations/order-chat-inbox-email-rollout.md`
- Modify: `docs/ENVIRONMENT.md`
- Modify: `README.md`
- Modify: `../pix_frontend_v2/moysklad-chat-extension/README.md`

**Interfaces:**

- Produces an auditable deployment/rollback procedure and an unpacked-extension ZIP.
- Does not itself authorize production migration, deployment, email sending, or destructive data work.

- [ ] **Step 1: Write the operations runbook**

Document this exact rollout order:

1. Verify both commit SHAs and clean scoped diffs.
2. Inspect production `DATABASE_URL` without printing its credential.
3. Create a timestamped PostgreSQL dump and verify it with `pg_restore --list`.
4. Review revision `f4c8a2d6b901` and current production head.
5. Stop and obtain explicit approval.
6. Apply only `alembic upgrade f4c8a2d6b901`.
7. Deploy backend with email flag still off; verify health, old room chat, new inbox REST/WS, and notification JSON.
8. Deploy the website.
9. Set `ORDER_CHAT_MANAGER_EMAIL=Pixtool22@gmail.com`, `PIX_PUBLIC_SITE_URL=https://pixlogistic.com`, the existing SMTP.BZ token, and enable email delivery.
10. Send one controlled client message and one controlled manager message; verify only the recipient receives each email and outbox rows become `sent`.
11. Distribute extension `0.2.0` and keep `0.1.0` compatibility during rollout.

Rollback must disable email delivery first, redeploy the prior application images, preserve additive tables/columns and pending jobs, and avoid Alembic downgrade unless separately approved.

- [ ] **Step 2: Update non-secret environment and install documentation**

Explain all three settings, outbox states/retry schedule, inbox endpoints, extension unpacked installation, secret setup, version verification, and how to reload after replacing the folder. Never include the real extension secret or SMTP token.

- [ ] **Step 3: Run backend verification after final edits**

Run from backend:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
git diff --check
```

Expected: the full backend check passes, the new Alembic head is recognized, and no whitespace errors are reported.

- [ ] **Step 4: Run frontend verification after final edits**

Run from frontend:

```powershell
npm.cmd run check
git diff --check
```

Expected: site and extension lint, unit, build, and browser suites pass.

- [ ] **Step 5: Build and inspect the extension ZIP**

After the successful extension build, create `pix-logistic-moysklad-chat-v0.2.0.zip` from the contents of `moysklad-chat-extension/dist` so `manifest.json` is at the ZIP root. Inspect the archive entry list and confirm no source maps, local secrets, `.env` files, or credentials are present. Do not commit the ZIP unless repository policy explicitly changes.

- [ ] **Step 6: Commit documentation in the correct repositories**

Backend:

```powershell
git add -- docs/operations/order-chat-inbox-email-rollout.md docs/ENVIRONMENT.md README.md
git commit -m "docs: add order chat inbox rollout"
```

Frontend:

```powershell
git add -- moysklad-chat-extension/README.md
git commit -m "docs: update MoySklad chat extension install"
```

- [ ] **Step 7: Request code review before merge or deployment**

Use `superpowers:requesting-code-review` across both repository diffs. Resolve findings with focused regression tests. Then use `superpowers:verification-before-completion` and rerun the relevant complete commands from Steps 3–4 after the final edit.

- [ ] **Step 8: Merge/push/deploy only under explicit authority**

Use `superpowers:finishing-a-development-branch` to present merge/push choices. Production backup, migration, environment mutation, container deployment, controlled email delivery, and old-data cleanup remain separate approval gates. This feature does not require or authorize deleting old chat records.
