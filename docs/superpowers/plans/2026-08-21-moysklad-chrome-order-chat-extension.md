# MoySklad Chrome Order Chat Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the MoySklad comment/file chat projection with an automatically injected Chrome extension panel that shares the website's canonical order chat and attachments.

**Architecture:** FastAPI exposes a secret-authenticated operator REST/WebSocket transport alongside the existing customer transport. Both transports delegate to one order-chat service backed by PostgreSQL, MinIO, Redis, and the existing notification tables. A Manifest V3 iframe panel detects MoySklad customer-order routes, stores the shared secret in trusted extension storage, and renders the same immutable room history.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, Alembic, PostgreSQL, Redis, MinIO, Next.js 14, React 18, TypeScript 5, Vite 7.3.6, Vitest 3.2.4, Playwright 1.62.1, Chrome Manifest V3.

**Spec:** `docs/superpowers/specs/2026-08-21-moysklad-chrome-order-chat-extension-design.md`

## Global Constraints

- Read the spec above and both repositories' `AGENTS.md` files before executing Task 1.
- Use `superpowers:using-git-worktrees` at execution time and create coordinated isolated worktrees for `pix_backend` and `../pix_frontend_v2`; do not overwrite the current dirty worktrees.
- Preserve the intentionally misspelled backend package name `dependecies/`.
- Keep the public API prefix `/api_v1` and the customer socket `/api_v1/chat/ws?auth=...&room=...`.
- Store all environment inputs in backend `config.py`; never read `os.getenv` in application modules.
- Never put the shared extension secret in source, manifests, build-time public values, URLs, logs, source maps, screenshots, or test output.
- Production accepts only HTTPS/WSS. The unpacked development build may use `http://localhost:8000/api_v1`.
- The extension supports only `https://online.moysklad.ru/app/#customerorder/edit?id=<UUID>`.
- Attachments remain limited to 10 files, 20 MiB each, with JPEG, PNG, WebP, PDF, DOC, DOCX, XLS, XLSX, TXT, and ZIP allowlisted by the existing backend validator.
- PostgreSQL and MinIO remain canonical; MoySklad descriptions and order files receive no new chat data.
- Do not apply or generate a production Alembic revision automatically. Create and statically verify the additive revision only.
- Do not delete the production webhook automatically. Produce and review a manual runbook.
- Do not include the later destructive cleanup of `chat_outbox_event`, `moysklad_order_file`, or projection-only state columns in this implementation.
- Use `npm.cmd` and the existing `package-lock.json`; do not create `yarn.lock`.
- After the final backend edit run `scripts/check.ps1`; after the final frontend/extension edit run `npm.cmd run check`.

## File Structure

### Backend units

- `alembic/versions/e3b7c9d1a204_allow_extension_chat_source.py` — additive source/origin constraint revision.
- `manager/order_chat_auth.py` — constant-time shared-secret comparison with no FastAPI dependency.
- `manager/order_chat.py` — customer and operator use cases, order linkage, MinIO compensation, realtime publication.
- `db/order_chat_repository.py` — linked-user lookup, order-scoped attachment lookup, transactional manager message plus notification.
- `routes/operator_chat.py` — operator header authentication, multipart REST routes, and first-frame WebSocket authentication.
- `dependecies/order_chat.py` — settings-to-storage/repository/service/authenticator wiring.
- `routes/chat.py` — customer transport only.
- `manager/chat_realtime.py` — accept/register split needed by authenticated operator sockets.
- `config.py` and `manager/production_config.py` — extension secret and production preflight.
- `conf.d/default.conf` — operator upload, request-rate, and WebSocket proxy rules.
- `docs/operations/moysklad-chat-extension-cutover.md` — manual cutover, webhook removal, rollback, and live smoke.

### Shared website units

- `src/features/order-chat/model.ts` — shared TypeScript message contract, merge helper, and attachment selection validation.
- `src/app/dashboard/orders/[id]/OrderChatPanel.tsx` — website UI without projection delivery state.
- `src/routes/routes.tsx` — unchanged customer URL/auth behavior using the simplified message response.

### Extension units

- `moysklad-chat-extension/manifest.template.json` — narrow Manifest V3 declaration without a secret.
- `moysklad-chat-extension/scripts/build-manifest.mjs` — validates the build-time API origin and emits `dist/manifest.json`.
- `moysklad-chat-extension/scripts/check-manifest.mjs` — rejects broad or sensitive production permissions.
- `moysklad-chat-extension/src/route.ts` — pure MoySklad URL parser and route transition controller.
- `moysklad-chat-extension/src/content/panelHost.ts` — fixed iframe host and collapse resize messages.
- `moysklad-chat-extension/src/content.ts` — content-script entry and SPA listeners.
- `moysklad-chat-extension/src/panel/secretStore.ts` — trusted-context `chrome.storage.local` access.
- `moysklad-chat-extension/src/panel/api.ts` — fixed-origin operator REST client.
- `moysklad-chat-extension/src/panel/socket.ts` — first-frame authentication and bounded reconnect logic.
- `moysklad-chat-extension/src/panel/useOrderChat.ts` — order-scoped UI state and stale-request protection.
- `moysklad-chat-extension/src/panel/App.tsx` — first-run, unavailable, retry, history, attachments, and composer UI.
- `moysklad-chat-extension/src/panel/AttachmentView.tsx` — authenticated Blob previews/downloads.
- `moysklad-chat-extension/src/panel/styles.css` — self-contained extension panel styling.

---

### Task 1: Add the additive extension source migration

**Files:**
- Create: `alembic/versions/e3b7c9d1a204_allow_extension_chat_source.py`
- Create: `tests/test_order_chat_extension_migration.py`
- Modify: `db/models/order_chat.py`
- Modify: `db/schemas/chat.py`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: existing Alembic head `d4e5f6a7b8c9`; existing `source` and `origin` string constraints.
- Produces: `MessageSource.EXTENSION`, `AttachmentOrigin.EXTENSION`, and database acceptance of the literal value `extension`.

- [ ] **Step 1: Write a failing migration/model test**

```python
# tests/test_order_chat_extension_migration.py
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
        str(item.sqltext) for item in OrderChatMessage.__table__.constraints
        if hasattr(item, "sqltext")
    )
    attachment_constraints = " ".join(
        str(item.sqltext) for item in OrderChatAttachment.__table__.constraints
        if hasattr(item, "sqltext")
    )
    assert "'extension'" in message_constraints
    assert "'extension'" in attachment_constraints


def test_additive_revision_replaces_only_source_constraints():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision: Union[str, None] = "d4e5f6a7b8c9"' in source
    assert "ck_order_chat_source" in source
    assert "ck_order_chat_attachment_origin" in source
    assert "drop_table" not in source
    assert "drop_column" not in source
    assert "reject_order_chat_mutation" not in source
```

- [ ] **Step 2: Run the focused test and confirm the missing revision/enums failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_order_chat_extension_migration.py -q`

Expected: FAIL because the migration file and `EXTENSION` enum members do not exist.

- [ ] **Step 3: Add enum/model values and the additive revision**

```python
# db/schemas/chat.py
class MessageSource(StrEnum):
    SITE = "site"
    MOYSKLAD = "moysklad"
    LEGACY = "legacy"
    EXTENSION = "extension"


class AttachmentOrigin(StrEnum):
    SITE = "site"
    MOYSKLAD = "moysklad"
    EXTENSION = "extension"
```

Update the two SQLAlchemy check constraints to the exact sets
`('site', 'moysklad', 'legacy', 'extension')` and
`('site', 'moysklad', 'extension')`.

```python
# alembic/versions/e3b7c9d1a204_allow_extension_chat_source.py
"""Allow Chrome extension order-chat messages and attachments."""

from typing import Sequence, Union

from alembic import op

revision: str = "e3b7c9d1a204"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_order_chat_source", "order_chat_message", type_="check"
    )
    op.create_check_constraint(
        "ck_order_chat_source",
        "order_chat_message",
        "source IN ('site', 'moysklad', 'legacy', 'extension')",
    )
    op.drop_constraint(
        "ck_order_chat_attachment_origin",
        "order_chat_attachment",
        type_="check",
    )
    op.create_check_constraint(
        "ck_order_chat_attachment_origin",
        "order_chat_attachment",
        "origin IN ('site', 'moysklad', 'extension')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_order_chat_attachment_origin",
        "order_chat_attachment",
        type_="check",
    )
    op.create_check_constraint(
        "ck_order_chat_attachment_origin",
        "order_chat_attachment",
        "origin IN ('site', 'moysklad')",
    )
    op.drop_constraint(
        "ck_order_chat_source", "order_chat_message", type_="check"
    )
    op.create_check_constraint(
        "ck_order_chat_source",
        "order_chat_message",
        "source IN ('site', 'moysklad', 'legacy')",
    )
```

Add the new revision path to `$ruffTargets` in `scripts/check.ps1`. Do not edit
`c8f2a4e6d901_order_chat_delivery.py`; it may already be deployed.

- [ ] **Step 4: Run migration/model checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_chat_extension_migration.py tests/test_order_chat_models.py -q
.\.venv\Scripts\python.exe -m alembic history
.\.venv\Scripts\python.exe -m ruff check db/models/order_chat.py db/schemas/chat.py alembic/versions/e3b7c9d1a204_allow_extension_chat_source.py tests/test_order_chat_extension_migration.py
```

Expected: tests PASS; Alembic shows `d4e5f6a7b8c9 -> e3b7c9d1a204 (head)`.
Do not run `alembic upgrade` or `downgrade`.

- [ ] **Step 5: Commit the additive contract**

```powershell
git add alembic/versions/e3b7c9d1a204_allow_extension_chat_source.py db/models/order_chat.py db/schemas/chat.py scripts/check.ps1 tests/test_order_chat_extension_migration.py
git commit -m "feat: allow extension order chat records"
```

### Task 2: Add extension-secret configuration and constant-time authentication

**Files:**
- Create: `manager/order_chat_auth.py`
- Create: `tests/test_operator_chat_auth.py`
- Modify: `config.py`
- Modify: `dependecies/order_chat.py`
- Modify: `manager/production_config.py`
- Modify: `tests/test_order_chat_config.py`
- Modify: `tests/test_production_config.py`
- Modify: `.env.example`
- Modify: `.env.production.example`
- Modify: `docs/ENVIRONMENT.md`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: `Settings`, `SecretStr`, `IntegrationNotConfigured`.
- Produces: `Settings.require_chat_extension_secret() -> str`, `OperatorChatAuthenticator.matches(candidate: str | None) -> bool`, and `get_operator_chat_authenticator() -> OperatorChatAuthenticator`.

- [ ] **Step 1: Write failing configuration and authenticator tests**

```python
# tests/test_operator_chat_auth.py
from unittest.mock import patch

import pytest

from config import Settings
from errors import IntegrationNotConfigured
from manager.order_chat_auth import OperatorChatAuthenticator


def test_extension_secret_has_no_default_and_is_required_at_call_time():
    settings = Settings(_env_file=None)
    with pytest.raises(IntegrationNotConfigured):
        settings.require_chat_extension_secret()


def test_authenticator_rejects_missing_and_uses_constant_time_comparison():
    authenticator = OperatorChatAuthenticator("x" * 32)
    assert authenticator.matches(None) is False
    with patch("manager.order_chat_auth.compare_digest", return_value=True) as compare:
        assert authenticator.matches("candidate") is True
    compare.assert_called_once_with("candidate", "x" * 32)
```

Extend `tests/test_order_chat_config.py` and `tests/test_production_config.py`
to assert that production order-chat preflight reports
`MOYSKLAD_CHAT_EXTENSION_SECRET` when absent, rejects a 31-character value,
accepts a 32-character value, and never includes the value in rendered issues.

- [ ] **Step 2: Run the focused tests and confirm missing symbols**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_operator_chat_auth.py tests/test_order_chat_config.py tests/test_production_config.py -q
```

Expected: FAIL because the setting, authenticator, and production issue do not exist.

- [ ] **Step 3: Implement the secret boundary**

```python
# manager/order_chat_auth.py
from secrets import compare_digest


class OperatorChatAuthenticator:
    def __init__(self, expected_secret: str):
        self._expected_secret = expected_secret

    def matches(self, candidate: str | None) -> bool:
        if candidate is None:
            return False
        return compare_digest(candidate, self._expected_secret)
```

```python
# config.py, inside Settings
moysklad_chat_extension_secret: SecretStr | None = None

def require_chat_extension_secret(self) -> str:
    return require_secret(
        self.moysklad_chat_extension_secret,
        "moysklad chat extension",
    )
```

```python
# dependecies/order_chat.py
def get_operator_chat_authenticator() -> OperatorChatAuthenticator:
    return OperatorChatAuthenticator(
        get_settings().require_chat_extension_secret()
    )
```

In `manager/production_config.py`, call `_require_strong_secret` for
`MOYSKLAD_CHAT_EXTENSION_SECRET` whenever `require_order_chat=True`. Add a blank
key to both environment examples and describe it as a shared 32+ character
operator credential in `docs/ENVIRONMENT.md`. Keep the existing webhook secret
for now; Task 6 removes it together with the old runtime.

- [ ] **Step 4: Run focused tests and secret scans**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_operator_chat_auth.py tests/test_order_chat_config.py tests/test_production_config.py -q
.\.venv\Scripts\python.exe -m ruff check config.py manager/order_chat_auth.py dependecies/order_chat.py manager/production_config.py tests/test_operator_chat_auth.py
rg -n "MOYSKLAD_CHAT_EXTENSION_SECRET=.*[^=]$" .env.example .env.production.example
```

Expected: tests PASS; the final `rg` prints no credential-bearing example.

- [ ] **Step 5: Commit the authentication boundary**

```powershell
git add .env.example .env.production.example config.py dependecies/order_chat.py docs/ENVIRONMENT.md manager/order_chat_auth.py manager/production_config.py scripts/check.ps1 tests/test_operator_chat_auth.py tests/test_order_chat_config.py tests/test_production_config.py
git commit -m "feat: configure extension chat authentication"
```

### Task 3: Add operator order resolution and manager-message use cases

**Files:**
- Create: `tests/test_operator_order_chat_service.py`
- Modify: `errors.py`
- Modify: `db/moysklad_order_chat_repository.py`
- Modify: `db/order_chat_repository.py`
- Modify: `manager/order_chat.py`
- Modify: `db/schemas/chat.py`
- Modify: `tests/test_order_chat_repository.py`
- Modify: `tests/test_order_chat_service.py`
- Modify: `tests/test_order_chat_api.py`

**Interfaces:**
- Consumes: `MoySkladOrderChatRepository.get_order(order_id)`, `OrderChatRepository.ensure_state`, existing attachment validator/storage, `NotificationManager.notify_count_changed`.
- Produces: `OperatorOrderChatAccessPolicy.resolve_client(order_id: UUID) -> User`, `OrderChatService.prepare_operator_order(order_id: UUID) -> User`, `list_operator_messages`, `create_manager_message`, and `get_operator_attachment`.

- [ ] **Step 1: Write failing operator service tests**

Create fakes for MoySklad, repository, storage, realtime, and notification
publication. Cover these exact cases:

```python
async def test_operator_policy_resolves_linked_counterparty_and_pins_state():
    client = await policy.resolve_client(ORDER_ID)
    assert client.id == CLIENT_ID
    assert repository.ensured == [(ORDER_ID, CLIENT_ID)]


async def test_operator_policy_hides_unlinked_and_conflicting_orders():
    repository.user = None
    with pytest.raises(OrderChatNotFound):
        await policy.resolve_client(ORDER_ID)


async def test_manager_message_is_extension_origin_and_notifies_after_commit():
    result = await service.create_manager_message(
        ORDER_ID,
        "  Документы готовы  ",
        [PendingUpload("invoice.pdf", b"%PDF-1.7")],
    )
    assert repository.created["source"] == "extension"
    assert repository.created["attachments"][0].origin == "extension"
    assert result.sender_kind.value == "manager"
    assert result.message == "Документы готовы"
    assert notifications.changed == [CLIENT_ID]
    assert realtime.rooms == [str(ORDER_ID)]


async def test_manager_database_failure_removes_new_minio_objects():
    repository.failure = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.create_manager_message(
            ORDER_ID, "file", [PendingUpload("note.txt", b"hello")]
        )
    assert storage.objects == {}


async def test_committed_manager_message_survives_realtime_failure():
    realtime.failure = RuntimeError("redis unavailable")
    result = await service.create_manager_message(ORDER_ID, "Готово", [])
    assert result.message == "Готово"
    assert repository.created["source"] == "extension"
    assert notifications.changed == [CLIENT_ID]


async def test_committed_manager_message_survives_notification_publish_failure():
    notifications.failure = RuntimeError("redis unavailable")
    result = await service.create_manager_message(ORDER_ID, "Готово", [])
    assert result.message == "Готово"
    assert repository.created["source"] == "extension"
```

Parameterize the fakes so the same file also covers malformed/missing agent
metadata, a MoySklad `404`, a transient MoySklad request failure, a file-only
manager message, a text-plus-file message, paginated history, and a
cross-order attachment ID. Assert lookup `404`/missing linkage become
`OrderChatNotFound`, transient lookup failure stays a generic
`MoySkladOrderLookupUnavailable`, and a cross-order attachment is never read
from MinIO.

Run the existing validator cases through `create_manager_message`: 11 files,
one file over 20 MiB, a blocked extension, a mismatched signature, and an
unsafe ZIP archive must each raise `ChatFileRejected` before the repository
commit. Reuse the small signature fixtures from `tests/test_chat_files.py`
rather than adding large binary fixtures.

Also update the existing customer service test to assert that
`create_client_message` passes no projection outbox event and that the response
has no `delivery_state` attribute. Add a repository regression test that spies
on the async session and proves one `session.begin()` encloses manager message,
attachment, and `Notifications(type="ORDER_MESSAGE")` creation before the
method returns.

- [ ] **Step 2: Run service tests and confirm missing operator methods**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_operator_order_chat_service.py tests/test_order_chat_service.py -q
```

Expected: FAIL because the operator policy/methods do not exist and customer responses still contain projection state.

- [ ] **Step 3: Add repository queries and transactional manager creation**

Translate the bounded external lookup at the repository boundary. Add
`MoySkladOrderLookupUnavailable` in `errors.py`; make `get_order` return `None`
for a MoySklad `404`, raise that generic exception for other request/JSON
failures, and never include URL, credentials, or response bodies in it. The
operator access policy maps `None` to `OrderChatNotFound` and lets the generic
temporary failure propagate to the transport.

Add these concrete repository interfaces:

```python
async def get_user_by_moysklad_counterparty(
    self, counterparty_id: UUID
) -> User | None:
    async with self._session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.moysklad_counterparty_id == counterparty_id
            ).limit(2)
        )
        users = list(result.scalars())
        return users[0] if len(users) == 1 else None


async def get_attachment_for_order(
    self, order_id: UUID, attachment_id: UUID
) -> tuple[OrderChatAttachment, StoredMessage] | None:
    async with self._session_factory() as session:
        result = await session.execute(
            select(OrderChatAttachment, OrderChatMessage)
            .join(
                OrderChatMessage,
                OrderChatMessage.id == OrderChatAttachment.message_id,
            )
            .where(
                OrderChatAttachment.id == attachment_id,
                OrderChatMessage.order_id == order_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        attachment, message = row
        return attachment, _stored_message(message, (attachment,))
```

Generalize `create_manager_message_with_notification` with
`source: str = "moysklad"` and `external_key: str | None = None`. Preserve the
single transaction that inserts the manager message, attachments, and
`Notifications(type="ORDER_MESSAGE")`. Operator calls pass `source="extension"`
and no MoySklad file/outbox records.

- [ ] **Step 4: Implement operator policy and service methods**

```python
class OperatorOrderChatAccessPolicy:
    def __init__(self, moysklad, repository: OrderChatRepository):
        self._moysklad = moysklad
        self._repository = repository

    async def resolve_client(self, order_id: UUID):
        order = await self._moysklad.get_order(order_id)
        try:
            href = order["agent"]["meta"]["href"]
            counterparty_id = UUID(href.rstrip("/").rsplit("/", 1)[-1])
        except (KeyError, TypeError, ValueError):
            raise OrderChatNotFound() from None
        client = await self._repository.get_user_by_moysklad_counterparty(
            counterparty_id
        )
        if client is None:
            raise OrderChatNotFound()
        try:
            await self._repository.ensure_state(order_id, client.id)
        except LookupError:
            raise OrderChatNotFound() from None
        return client
```

Add `operator_access_policy` and `notification_manager` constructor arguments
to `OrderChatService`. Implement:

```python
async def prepare_operator_order(self, order_id: UUID):
    if self._operator_access_policy is None:
        raise OrderChatNotFound()
    return await self._operator_access_policy.resolve_client(order_id)

async def list_operator_messages(self, order_id, before, limit):
    await self.prepare_operator_order(order_id)
    messages, next_before = await self._repository.list_messages(
        order_id, before, limit
    )
    return OrderChatPageResponse(
        items=[await self._response(item) for item in messages],
        next_before=next_before,
    )
```

`create_manager_message` must share the existing validation/storage
compensation path, create `NewAttachment(origin="extension")`, call the
transactional repository method with `source="extension"`, then publish the
message and call `notification_manager.notify_count_changed(client.id)` after
commit. Redis is an ephemeral fan-out only: independently catch and safely log
chat-room or notification-count publication failures without failing or
deleting the committed message. A chat-room failure must still attempt the
notification-count publication; neither log may include body, filename,
secret, or external response content. `get_operator_attachment` must call
`prepare_operator_order`, then
`get_attachment_for_order(order_id, attachment_id)` before reading MinIO.

Stop creating `sync_order` events in `ensure_state` and
`create_client_message`. Remove `delivery_state` from
`OrderChatMessageResponse`, `_response`, API test fixtures, and service fakes.

- [ ] **Step 5: Run service/API tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_operator_order_chat_service.py tests/test_order_chat_repository.py tests/test_order_chat_service.py tests/test_order_chat_api.py tests/test_notification_repository.py -q
.\.venv\Scripts\python.exe -m ruff check errors.py db/moysklad_order_chat_repository.py db/order_chat_repository.py db/schemas/chat.py manager/order_chat.py tests/test_operator_order_chat_service.py tests/test_order_chat_repository.py tests/test_order_chat_service.py
```

Expected: PASS. The customer response JSON contains no `delivery_state`, and no
new customer message enqueues `sync_order`.

- [ ] **Step 6: Commit the shared use case**

```powershell
git add errors.py db/moysklad_order_chat_repository.py db/order_chat_repository.py db/schemas/chat.py manager/order_chat.py tests/test_operator_order_chat_service.py tests/test_order_chat_repository.py tests/test_order_chat_service.py tests/test_order_chat_api.py
git commit -m "feat: add operator order chat use cases"
```

### Task 4: Expose the operator REST API and runtime capability

**Files:**
- Create: `routes/operator_chat.py`
- Create: `tests/test_operator_chat_api.py`
- Modify: `dependecies/order_chat.py`
- Modify: `main.py`
- Modify: `tests/test_app.py`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: `OperatorChatAuthenticator`, `OrderChatService.list_operator_messages`, `create_manager_message`, `get_operator_attachment`.
- Produces: three REST routes under `/api_v1/chat/operator` and the missing `/api_v1/capabilities` response.

- [ ] **Step 1: Write failing operator REST tests**

Use `create_app(Settings(_env_file=None, app_env="test"))`, override
`get_order_chat_service` and `get_operator_chat_authenticator`, and assert:

```python
def test_operator_history_requires_the_shared_secret():
    with operator_client(secret="expected") as client:
        missing = client.get(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/messages"
        )
        wrong = client.get(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/messages",
            headers={"X-Pix-Chat-Secret": "wrong"},
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json() == wrong.json() == {"detail": "Unauthorized"}


def test_operator_message_accepts_text_and_repeated_files():
    response = client.post(
        f"/api_v1/chat/operator/orders/{ORDER_ID}/messages",
        headers={"X-Pix-Chat-Secret": "expected"},
        data={"message": "Готово"},
        files=[
            ("files", ("a.txt", b"a", "text/plain")),
            ("files", ("b.pdf", b"%PDF-1.7", "application/pdf")),
        ],
    )
    assert response.status_code == 201
    assert response.json()["sender_kind"] == "manager"


def test_operator_attachment_is_scoped_to_url_order():
    response = client.get(
        f"/api_v1/chat/operator/orders/{ORDER_ID}/attachments/{ATTACHMENT_ID}",
        headers={"X-Pix-Chat-Secret": "expected"},
    )
    assert response.status_code == 200
    service.get_operator_attachment.assert_awaited_once_with(
        ORDER_ID, ATTACHMENT_ID
    )


def test_operator_malformed_order_is_the_same_generic_404():
    response = client.get(
        "/api_v1/chat/operator/orders/not-a-uuid/messages",
        headers={"X-Pix-Chat-Secret": "expected"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Order not found"}


def test_operator_lookup_outage_is_503_without_external_details():
    service.list_operator_messages.side_effect = (
        MoySkladOrderLookupUnavailable()
    )
    response = client.get(
        f"/api_v1/chat/operator/orders/{ORDER_ID}/messages",
        headers={"X-Pix-Chat-Secret": "expected"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Chat temporarily unavailable"}
```

Add a `tests/test_app.py` case asserting
`GET /api_v1/capabilities == {"moysklad_order_chat": <settings flag>}`. Add an
operator-route case proving a disabled flag fails closed with `503` before the
service or MoySklad lookup runs.

- [ ] **Step 2: Run route tests and confirm 404/missing capability**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_operator_chat_api.py tests/test_app.py -q
```

Expected: FAIL because the operator router and capabilities route are absent.

- [ ] **Step 3: Implement header authentication and REST routes**

```python
# routes/operator_chat.py
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)

router = APIRouter(prefix="/chat/operator", tags=["Operator Order Chat"])


async def require_operator_chat_secret(
    secret: Annotated[
        str | None,
        Header(alias="X-Pix-Chat-Secret"),
    ] = None,
    authenticator: OperatorChatAuthenticator = Depends(
        get_operator_chat_authenticator
    ),
) -> None:
    if not authenticator.matches(secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
```

Store the exact `Settings` instance passed to `create_app` on
`application.state.settings`. Add a router-level REST dependency that reads
that instance from `Request`, raises
`IntegrationNotConfigured("moysklad order chat")` when the feature flag is
off, and therefore prevents disabled deployments from using operator routes
even if credentials remain in the environment.

Implement list/create/download routes with the exact paths in the spec. Keep
path IDs as strings, parse them through one route helper, and map malformed
order or attachment UUIDs to the same generic `404` as inaccessible records
instead of FastAPI's identifying `422`. Read the history cursor as
`before: UUID | None = None` and its page size as
`limit: Annotated[int, Query(ge=1, le=100)] = 50`. Read each uploaded file
into `PendingUpload`, reject empty text plus empty files,
map `OrderChatNotFound` to a generic `404`, map
`EmptyOrderChatMessage`/`ChatFileRejected` to `422`, and use the same encoded
`Content-Disposition` behavior as the customer download route. Map
`MoySkladOrderLookupUnavailable` to a body-free-of-external-details `503`;
the application's existing `IntegrationNotConfigured` handler also remains
the `503` boundary for missing secret, MoySklad credentials, or MinIO config.

Wire `OrderChatService` with one repository instance shared by
`OperatorOrderChatAccessPolicy`, add `build_notification_manager()`, and mount
the operator router in `main.py`.

```python
@api_router.get("/capabilities")
async def capabilities():
    return {"moysklad_order_chat": settings.enable_moysklad_order_chat}
```

- [ ] **Step 4: Run operator REST and app tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_operator_chat_api.py tests/test_app.py tests/test_order_chat_api.py -q
.\.venv\Scripts\python.exe -m ruff check routes/operator_chat.py dependecies/order_chat.py main.py tests/test_operator_chat_api.py
```

Expected: PASS; a wrong secret never calls the service.

- [ ] **Step 5: Commit the operator REST surface**

```powershell
git add dependecies/order_chat.py main.py routes/operator_chat.py scripts/check.ps1 tests/test_app.py tests/test_operator_chat_api.py
git commit -m "feat: expose operator order chat API"
```

### Task 5: Authenticate operator WebSockets before room registration

**Files:**
- Modify: `routes/operator_chat.py`
- Modify: `manager/chat_realtime.py`
- Create: `tests/test_operator_chat_websocket.py`
- Modify: `tests/test_chat_realtime.py`

**Interfaces:**
- Consumes: `OperatorChatAuthenticator.matches`, `OrderChatService.prepare_operator_order`, `RedisChatRealtime`.
- Produces: `RedisChatRealtime.register(room_id, websocket)`, `receive_operator_authentication(...) -> bool`, and `/api_v1/chat/operator/ws?room=<UUID>`.

- [ ] **Step 1: Write failing first-frame and registration tests**

```python
async def test_first_frame_authentication_accepts_only_exact_shape():
    socket = SocketStub(
        frames=[{"type": "authenticate", "secret": "expected"}]
    )
    assert await receive_operator_authentication(
        socket,
        OperatorChatAuthenticator("expected"),
        timeout_seconds=0.1,
    ) is True

    wrong = SocketStub(frames=[{"type": "authenticate", "secret": "no"}])
    assert await receive_operator_authentication(
        wrong,
        OperatorChatAuthenticator("expected"),
        timeout_seconds=0.1,
    ) is False


async def test_first_frame_timeout_fails_closed():
    assert await receive_operator_authentication(
        BlockingSocketStub(),
        OperatorChatAuthenticator("expected"),
        timeout_seconds=0,
    ) is False
```

Add route tests asserting invalid auth closes with `4401`, an unlinked room
closes with `4404`, success sends `{"type":"authenticated"}`, and
`realtime.register` is called only after `service.prepare_operator_order`.
Also reject a missing field, an extra field, a non-object JSON value, and
invalid JSON with `4401`; reject malformed room UUID and temporary MoySklad
lookup failure with `4404` without registering either socket. A disabled
feature flag closes `4404` before authentication or registration.
Keep the existing customer socket test proving its bearer-token behavior is
unchanged.

- [ ] **Step 2: Run WebSocket/realtime tests and confirm missing interfaces**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_operator_chat_websocket.py tests/test_chat_realtime.py tests/test_order_chat_api.py -q
```

Expected: FAIL because `receive_operator_authentication`, `register`, and the
operator socket route do not exist.

- [ ] **Step 3: Split socket acceptance from room registration**

```python
# manager/chat_realtime.py
class LocalChatHub:
    async def register(self, room_id: str, websocket) -> None:
        self.connections[str(room_id)].add(websocket)

    async def connect(self, room_id: str, websocket) -> None:
        await websocket.accept()
        await self.register(room_id, websocket)


class RedisChatRealtime:
    async def register(self, room_id: str, websocket) -> None:
        await self._local_hub.register(str(room_id), websocket)
```

Do not change `RedisChatRealtime.connect`; the customer socket still needs it to
accept and register in one call.

- [ ] **Step 4: Implement bounded first-frame authentication and the socket route**

```python
async def receive_operator_authentication(
    websocket: WebSocket,
    authenticator: OperatorChatAuthenticator,
    *,
    timeout_seconds: float = 5,
) -> bool:
    try:
        async with asyncio.timeout(timeout_seconds):
            frame = await websocket.receive_json()
    except (TimeoutError, ValueError, TypeError, WebSocketDisconnect):
        return False
    return (
        isinstance(frame, dict)
        and set(frame) == {"type", "secret"}
        and frame.get("type") == "authenticate"
        and isinstance(frame.get("secret"), str)
        and authenticator.matches(frame["secret"])
    )
```

The route must:

1. read the required `room` string without registering it;
2. call `await websocket.accept()`, verify the app-state feature flag, then
   parse the room as UUID and close `4404` if disabled, absent, or malformed;
3. call `receive_operator_authentication(..., timeout_seconds=5)`;
4. close `4401` on failure;
5. call `service.prepare_operator_order(order_id)` and close `4404` on
   `OrderChatNotFound`, `IntegrationNotConfigured`, or
   `MoySkladOrderLookupUnavailable`;
6. send `{"type":"authenticated"}`;
7. call `realtime.register(str(order_id), websocket)`;
8. reject every later inbound frame with
   `{"type":"error","code":"order_chat_http_required"}`;
9. disconnect in `finally` only when registration occurred.

- [ ] **Step 5: Run WebSocket and customer regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_operator_chat_websocket.py tests/test_chat_realtime.py tests/test_order_chat_api.py -q
.\.venv\Scripts\python.exe -m ruff check routes/operator_chat.py manager/chat_realtime.py tests/test_operator_chat_websocket.py
```

Expected: PASS; no invalid or unlinked socket is present in
`LocalChatHub.connections`.

- [ ] **Step 6: Commit authenticated realtime transport**

```powershell
git add manager/chat_realtime.py routes/operator_chat.py tests/test_chat_realtime.py tests/test_operator_chat_websocket.py
git commit -m "feat: authenticate operator chat sockets"
```

### Task 6: Remove the MoySklad comment/file projection runtime

**Files:**
- Delete: `manager/chat_outbox.py`
- Delete: `manager/moysklad_order_chat.py`
- Delete: `manager/order_chat_format.py`
- Delete: `routes/integration/order_chat_webhook.py`
- Delete: `scripts/register_moysklad_order_chat_webhook.py`
- Delete: `tests/test_chat_outbox.py`
- Delete: `tests/test_moysklad_order_chat.py`
- Delete: `tests/test_order_chat_format.py`
- Delete: `tests/test_order_chat_runtime.py`
- Delete: `tests/test_order_chat_webhook.py`
- Create: `tests/test_no_moysklad_chat_projection.py`
- Modify: `db/moysklad_order_chat_repository.py`
- Modify: `db/order_chat_repository.py`
- Modify: `db/schemas/chat.py`
- Modify: `dependecies/order_chat.py`
- Modify: `routes/bitrix.py`
- Modify: `main.py`
- Modify: `config.py`
- Modify: `manager/production_config.py`
- Modify: `tests/test_moysklad_order_chat_repository.py`
- Modify: `tests/test_chat_realtime.py`
- Modify: `tests/test_order_chat_config.py`
- Modify: `tests/test_production_config.py`
- Modify: `.env.example`
- Modify: `.env.production.example`
- Modify: `docs/ENVIRONMENT.md`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: operator/customer service from Tasks 3–5.
- Produces: an order-chat runtime that initializes only MinIO and realtime; no description renderer, file mirror, webhook receiver, outbox worker, or projection delivery event.

- [ ] **Step 1: Write the failing removal guard**

```python
# tests/test_no_moysklad_chat_projection.py
from pathlib import Path


REMOVED = (
    "manager/chat_outbox.py",
    "manager/moysklad_order_chat.py",
    "manager/order_chat_format.py",
    "routes/integration/order_chat_webhook.py",
    "scripts/register_moysklad_order_chat_webhook.py",
)


def test_projection_runtime_files_are_removed():
    assert [path for path in REMOVED if Path(path).exists()] == []


def test_active_runtime_has_no_projection_tokens():
    sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "main.py",
            "dependecies/order_chat.py",
            "routes/bitrix.py",
            "manager/order_chat.py",
        )
    )
    for token in (
        "sync_order",
        "process_moysklad_update",
        "OrderChatOutboxWorker",
        "MoySkladOrderChatSynchronizer",
        "order_chat_delivery",
    ):
        assert token not in sources
```

Add configuration assertions that active order chat no longer requires
`MOYSKLAD_ORDER_CHAT_WEBHOOK_SECRET`, `CHAT_OUTBOX_MAX_ATTEMPTS`, or
`CHAT_OUTBOX_BASE_DELAY_SECONDS`, but still requires MoySklad lookup
credentials, MinIO, and `MOYSKLAD_CHAT_EXTENSION_SECRET` in production.

- [ ] **Step 2: Run removal/config tests and confirm old runtime is active**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_no_moysklad_chat_projection.py tests/test_order_chat_config.py tests/test_production_config.py -q
```

Expected: FAIL because projection files/tokens/settings still exist.

- [ ] **Step 3: Remove projection creation and consumption code**

Apply these exact boundaries:

- Add a pure `build_order_chat_storage(settings: OrderChatSettings)` factory.
  Cached FastAPI dependencies call it with the configured global settings;
  `main.py` calls it with `settings.require_order_chat()` from the application
  factory before `ensure_bucket()`. This preserves injected test settings and
  prevents lifespan startup from silently reading a different global config.
- `main.py` initializes that storage when chat is enabled and never
  starts/stops an outbox worker.
- `dependecies/order_chat.py` retains storage, repository, client/operator
  policies, service, authenticator, realtime, and notification wiring only.
- `routes/bitrix.py` no longer imports or mounts the order-chat webhook router.
- `db/moysklad_order_chat_repository.py` retains the bounded authenticated
  `get_order(order_id)` lookup only; remove description updates, order-file
  methods, and webhook registration methods.
- `db/order_chat_repository.py` removes projection/outbox dataclasses and
  methods from active code while leaving SQLAlchemy table models untouched for
  the later separately approved cleanup migration.
- `db/schemas/chat.py` removes MoySklad webhook payload schemas and the obsolete
  delivery event shape.
- `manager/chat_realtime.py` retains only generic room publish/register logic;
  remove projection delivery-state tests.

Delete the five runtime/source files and their five projection-only test files.
Do not change historical migration tests in `tests/test_remove_telegram_migration.py`;
they must continue proving what the historical revision did.

- [ ] **Step 4: Retire projection configuration without weakening chat preflight**

Remove these fields from `OrderChatSettings`/`Settings` and environment docs:

```text
MOYSKLAD_ORDER_CHAT_WEBHOOK_SECRET
CHAT_OUTBOX_MAX_ATTEMPTS
CHAT_OUTBOX_BASE_DELAY_SECONDS
```

`Settings.require_order_chat()` must return MinIO connection fields and the two
attachment limits only. Production preflight must require:

```text
ENABLE_MOYSKLAD_ORDER_CHAT
MOYSKLAD_LOGIN
MOYSKLAD_PASSWORD
MOYSKLAD_CHAT_EXTENSION_SECRET
MINIO_ENDPOINT
MINIO_ACCESS_KEY
MINIO_SECRET_KEY
```

Update exact-key template tests and `$ruffTargets` to match the active files.
Do not remove obsolete database tables or their model declarations.

- [ ] **Step 5: Run the complete backend suite**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
.\.venv\Scripts\python.exe -m alembic history
git diff --check
```

Expected: Ruff and all backend tests PASS; Alembic has one head at
`e3b7c9d1a204`; no migration is applied.

- [ ] **Step 6: Commit projection removal**

```powershell
git add -A -- .env.example .env.production.example config.py db dependecies docs/ENVIRONMENT.md main.py manager routes scripts tests
git commit -m "refactor: replace MoySklad chat projection"
```

Review `git show --stat --oneline HEAD` and confirm it does not contain local
`.env`, credentials, compiled files, or the later destructive cleanup.

### Task 7: Simplify and share the website chat contract

**Files:**
- Create: `src/features/order-chat/model.ts`
- Create: `src/features/order-chat/model.test.ts`
- Create: `src/config/api.test.ts`
- Delete: `src/app/dashboard/orders/[id]/orderChat.ts`
- Delete: `src/app/dashboard/orders/[id]/orderChat.test.ts`
- Modify: `src/app/dashboard/orders/[id]/OrderChatPanel.tsx`
- Modify: `src/routes/routes.tsx`
- Modify: `tests/mock-backend.mjs`
- Modify: `tests/order-chat.spec.ts`

**Interfaces:**
- Consumes: backend `OrderChatMessageResponse` without `delivery_state`; unchanged customer REST and WebSocket URLs.
- Produces: reusable `OrderChatMessage`, `OrderChatPage`, `mergeOrderChatMessages`, and `validateSelectedFiles` imports for both website and extension.

- [ ] **Step 1: Write the failing shared-model test**

```typescript
// src/features/order-chat/model.test.ts
import { describe, expect, it } from "vitest";

import {
  mergeOrderChatMessages,
  validateSelectedFiles,
  type OrderChatMessage,
} from "./model";

const message = (id: string, createdAt: string): OrderChatMessage => ({
  id,
  order_id: "00000000-0000-0000-0000-000000000001",
  sender_kind: id === "client" ? "client" : "manager",
  sender_label: id === "client" ? "Клиент" : "Менеджер Pix Logistic",
  message: id,
  created_at: createdAt,
  attachments: [],
});

describe("order chat model", () => {
  it("has no projection delivery field", () => {
    expect(Object.keys(message("client", "2026-08-10T12:00:00Z"))).not.toContain(
      "delivery_state",
    );
  });

  it("merges REST and websocket copies once in chronological order", () => {
    const result = mergeOrderChatMessages(
      [message("manager", "2026-08-10T12:01:00Z")],
      [
        message("client", "2026-08-10T12:00:00Z"),
        message("manager", "2026-08-10T12:01:00Z"),
      ],
    );
    expect(result.map(({ id }) => id)).toEqual(["client", "manager"]);
  });

  it("keeps the existing count, extension, and 20 MiB client checks", () => {
    const file = (name: string, size: number) => ({ name, size }) as File;
    expect(
      validateSelectedFiles(
        Array.from({ length: 11 }, (_, index) => file(`${index}.txt`, 1)),
      ),
    ).toBe("Можно прикрепить не более 10 файлов");
    expect(validateSelectedFiles([file("program.exe", 2)])).toBe(
      "Тип файла program.exe не поддерживается",
    );
    expect(validateSelectedFiles([file("big.pdf", 20 * 1024 * 1024 + 1)])).toBe(
      "Файл big.pdf больше 20 МБ",
    );
  });
});
```

- [ ] **Step 2: Run unit tests and confirm the shared module is absent**

Run: `npm.cmd run test:unit -- src/features/order-chat/model.test.ts`

Expected: FAIL because `src/features/order-chat/model.ts` does not exist.

- [ ] **Step 3: Move the stable contract/helpers and remove projection fields**

Move the attachment/message/page/connection types, merge helper, and file
validator into `src/features/order-chat/model.ts`. The exact message type is:

```typescript
export type OrderChatMessage = {
  id: string;
  order_id: string;
  sender_kind: "client" | "manager";
  sender_label: "Клиент" | "Менеджер Pix Logistic";
  message: string;
  created_at: string;
  attachments: OrderChatAttachment[];
};
```

Delete `OrderChatDeliveryEvent`, `getDeliveryLabel`, and `applyDeliveryEvent`.
Update `OrderChatPanel.tsx` and `src/routes/routes.tsx` imports to use
`@/features/order-chat/model`. The WebSocket `onmessage` handler accepts only an
`OrderChatMessage | {type:"error"}` and merges objects that contain `id`.
Remove the delivery label paragraph from each rendered message. Move the
deleted helper test's `backendWebSocketUrl` assertion into
`src/config/api.test.ts`; keep proving `a+b/c` and the room are encoded in the
unchanged customer `ws://localhost:8000/api_v1/chat/ws` URL.

- [ ] **Step 4: Update browser fixtures and assertions**

Remove every `delivery_state` property from `tests/mock-backend.mjs` and
`tests/order-chat.spec.ts`. Rename the first browser test to
`shows immutable history, sends files, and receives an extension reply` and
replace the `Отправляется` assertion with an assertion that the submitted
message and its download button are visible exactly once.

- [ ] **Step 5: Run website checks for the changed contract**

Run:

```powershell
npm.cmd run test:unit -- src/features/order-chat/model.test.ts src/features/order-chat/useOrderChatAvailability.test.ts src/config/api.test.ts
npx.cmd playwright test tests/order-chat.spec.ts
npm.cmd run lint
```

Expected: PASS; the customer socket still includes encoded `auth` and `room`.

- [ ] **Step 6: Commit the website contract in `pix_frontend_v2`**

```powershell
git add -- src/config/api.test.ts src/features/order-chat src/routes/routes.tsx tests/mock-backend.mjs tests/order-chat.spec.ts 'src/app/dashboard/orders/[id]'
git commit -m "refactor: simplify order chat delivery contract"
```

### Task 8: Scaffold the independent Manifest V3 workspace and deterministic build

**Files:**
- Create: `moysklad-chat-extension/package.json`
- Create: `moysklad-chat-extension/tsconfig.json`
- Create: `moysklad-chat-extension/.eslintrc.json`
- Create: `moysklad-chat-extension/vite.config.ts`
- Create: `moysklad-chat-extension/vite.content.config.ts`
- Create: `moysklad-chat-extension/panel.html`
- Create: `moysklad-chat-extension/manifest.template.json`
- Create: `moysklad-chat-extension/scripts/build-manifest.mjs`
- Create: `moysklad-chat-extension/scripts/check-manifest.mjs`
- Create: `moysklad-chat-extension/scripts/build-manifest.test.ts`
- Create: `moysklad-chat-extension/src/config.ts`
- Create: `moysklad-chat-extension/src/content.ts`
- Create: `moysklad-chat-extension/src/panel/main.tsx`
- Create: `moysklad-chat-extension/src/panel/App.tsx`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: npm workspace support, React 18, Vite, build-time `PIX_EXTENSION_BACKEND_URL`.
- Produces: `moysklad-chat-extension/dist` containing `manifest.json`, `content.js`, `panel.html`, and bundled local assets.

- [ ] **Step 1: Add the workspace manifest and a failing manifest-builder test**

Add `"workspaces": ["moysklad-chat-extension"]` to the root `package.json`.
Create the extension package with exact pinned tool versions:

```json
{
  "name": "pix-moysklad-chat-extension",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "lint": "eslint . --ext .ts,.tsx,.mjs --ignore-pattern dist",
    "typecheck": "tsc -p tsconfig.json --noEmit",
    "test:unit": "vitest run --configLoader runner",
    "build": "vite build && vite build --config vite.content.config.ts && node scripts/build-manifest.mjs",
    "check:manifest": "node scripts/check-manifest.mjs",
    "check": "npm run lint && npm run typecheck && npm run test:unit && npm run build && npm run check:manifest"
  },
  "dependencies": {
    "react": "^18",
    "react-dom": "^18"
  },
  "devDependencies": {
    "@types/chrome": "0.2.6",
    "@types/node": "^20",
    "@types/react": "^18",
    "@types/react-dom": "^18",
    "typescript": "^5",
    "vite": "7.3.6",
    "vitest": "3.2.4"
  }
}
```

```typescript
// scripts/build-manifest.test.ts
import { describe, expect, it } from "vitest";
import { buildManifest } from "./build-manifest.mjs";

describe("buildManifest", () => {
  it("adds only the fixed API origin as host permission", () => {
    const manifest = buildManifest("https://pixlogistic.com/api_v1");
    expect(manifest.host_permissions).toEqual(["https://pixlogistic.com/*"]);
    expect(JSON.stringify(manifest)).not.toContain("<all_urls>");
  });

  it("rejects credentials, query strings, and non-api paths", () => {
    for (const value of [
      "https://user:secret@pixlogistic.com/api_v1",
      "https://pixlogistic.com/api_v1?secret=x",
      "https://pixlogistic.com/other",
    ]) {
      expect(() => buildManifest(value)).toThrow();
    }
  });
});
```

- [ ] **Step 2: Install workspace dependencies and confirm the missing builder failure**

Run:

```powershell
npm.cmd install --package-lock-only
npm.cmd ci
npm.cmd run test:unit --workspace pix-moysklad-chat-extension
```

Expected: dependency installation succeeds; the test FAILS because
`build-manifest.mjs` does not exist.

- [ ] **Step 3: Implement manifest generation and permission checking**

Use this exact manifest shape:

```json
{
  "manifest_version": 3,
  "name": "Pix Logistic — чат заказа",
  "version": "0.1.0",
  "minimum_chrome_version": "116",
  "permissions": ["storage"],
  "content_scripts": [
    {
      "matches": ["https://online.moysklad.ru/app/*"],
      "js": ["content.js"],
      "run_at": "document_idle"
    }
  ],
  "web_accessible_resources": [
    {
      "resources": ["panel.html", "assets/*"],
      "matches": ["https://online.moysklad.ru/*"]
    }
  ]
}
```

`buildManifest(apiBase)` must parse an absolute URL, require path exactly
`/api_v1`, reject credentials/query/fragment, allow HTTP only for `localhost`
or `127.0.0.1`, and return the template plus
`host_permissions: [origin + "/*"]`. The executable script uses
`PIX_EXTENSION_BACKEND_URL` or the safe local default
`http://localhost:8000/api_v1` and writes formatted JSON to
`dist/manifest.json`.

`check-manifest.mjs` reads `dist/manifest.json` and fails unless permissions are
exactly `["storage"]`, content matches are exactly the MoySklad application,
one API origin is present, and none of `<all_urls>`, `cookies`, `tabs`,
`webRequest`, `declarativeNetRequest`, `history`, `clipboardRead`,
`clipboardWrite`, or `downloads` occurs.

- [ ] **Step 4: Configure two Vite outputs and a minimal panel**

Use this standalone TypeScript boundary so the workspace also type-checks its
plain `.mjs` builder and the shared website model:

```json
// tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "types": ["chrome", "node", "vite/client", "vitest/globals"]
  },
  "include": [
    "src",
    "tests",
    "scripts",
    "vite.config.ts",
    "vite.content.config.ts",
    "playwright.config.ts",
    "../src/features/order-chat/model.ts"
  ]
}
```

```json
// .eslintrc.json
{
  "root": true,
  "extends": ["next/core-web-vitals"],
  "env": {"browser": true, "node": true, "es2022": true},
  "ignorePatterns": ["dist/"]
}
```

`vite.config.ts` builds `panel.html` to `dist` with `base: ""`, defines
`__PIX_API_BASE__` from the safe local default, and leaves no remote code:

```typescript
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const packageRoot = fileURLToPath(new URL(".", import.meta.url));
const apiBase =
  process.env.PIX_EXTENSION_BACKEND_URL ?? "http://localhost:8000/api_v1";

export default defineConfig({
  base: "",
  define: { __PIX_API_BASE__: JSON.stringify(apiBase) },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: { input: resolve(packageRoot, "panel.html") },
  },
});
```

`vite.content.config.ts` builds `src/content.ts` as one IIFE file named
`dist/content.js` without erasing the panel output:

```typescript
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const entry = fileURLToPath(new URL("./src/content.ts", import.meta.url));

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: false,
    lib: {
      entry,
      formats: ["iife"],
      name: "PixMoySkladChatContent",
      fileName: () => "content.js",
    },
  },
});
```

```typescript
// src/config.ts
declare const __PIX_API_BASE__: string;

export const API_BASE = __PIX_API_BASE__.replace(/\/+$/, "");

export function apiUrl(path: string): string {
  return `${API_BASE}/${path.replace(/^\/+/, "")}`;
}
```

Use a local `panel.html` with only `<div id="root"></div>` and a module script
for `/src/panel/main.tsx`; render a minimal `App` containing
`<main>Загрузка чата…</main>`. Add
`moysklad-chat-extension/dist/` to the root `.gitignore`.

- [ ] **Step 5: Run workspace checks and inspect the artifact**

Run:

```powershell
npm.cmd run check --workspace pix-moysklad-chat-extension
Get-ChildItem moysklad-chat-extension\dist -Recurse
rg -n "MOYSKLAD_CHAT_EXTENSION_SECRET|X-Pix-Chat-Secret" moysklad-chat-extension\dist
```

Expected: check PASS; artifact contains the manifest, panel, content IIFE, and
local assets; the final secret scan prints nothing.

- [ ] **Step 6: Commit the extension build scaffold in `pix_frontend_v2`**

```powershell
git add .gitignore package.json package-lock.json moysklad-chat-extension
git commit -m "build: scaffold MoySklad chat extension"
```

### Task 9: Detect MoySklad SPA routes and inject one isolated iframe panel

**Files:**
- Create: `moysklad-chat-extension/src/route.ts`
- Create: `moysklad-chat-extension/src/route.test.ts`
- Create: `moysklad-chat-extension/src/content/panelHost.ts`
- Modify: `moysklad-chat-extension/src/content.ts`

**Interfaces:**
- Consumes: `chrome.runtime.getURL("panel.html")`, browser `hashchange`/`popstate`.
- Produces: `isOrderId(value: string) -> boolean`, `orderIdFromMoySkladUrl(value: string) -> string | null`, `RouteController.update(value: string)`, and `IframePanelHost.show/hide`.

- [ ] **Step 1: Write failing pure route/controller tests**

```typescript
// src/route.test.ts
import { describe, expect, it, vi } from "vitest";

import { orderIdFromMoySkladUrl, RouteController } from "./route";

const one = "00000000-0000-0000-0000-000000000001";
const two = "00000000-0000-0000-0000-000000000002";

describe("orderIdFromMoySkladUrl", () => {
  it("accepts only exact customer-order edit hashes with UUID ids", () => {
    expect(
      orderIdFromMoySkladUrl(
        `https://online.moysklad.ru/app/#customerorder/edit?id=${one}`,
      ),
    ).toBe(one);
    expect(
      orderIdFromMoySkladUrl(
        `https://online.moysklad.ru/app/#counterparty/edit?id=${one}`,
      ),
    ).toBeNull();
    expect(
      orderIdFromMoySkladUrl(
        "https://online.moysklad.ru/app/#customerorder/edit?id=not-a-uuid",
      ),
    ).toBeNull();
    expect(orderIdFromMoySkladUrl("not a URL")).toBeNull();
    expect(
      orderIdFromMoySkladUrl(
        `https://example.com/app/#customerorder/edit?id=${one}`,
      ),
    ).toBeNull();
    expect(
      orderIdFromMoySkladUrl(
        `https://online.moysklad.ru/app/#customerorder/edit?id=${one}&extra=x`,
      ),
    ).toBeNull();
  });
});

it("mounts once, switches orders, and hides when leaving the route", () => {
  const host = { show: vi.fn(), hide: vi.fn() };
  const controller = new RouteController(host);
  controller.update(
    `https://online.moysklad.ru/app/#customerorder/edit?id=${one}`,
  );
  controller.update(
    `https://online.moysklad.ru/app/#customerorder/edit?id=${one}`,
  );
  controller.update(
    `https://online.moysklad.ru/app/#customerorder/edit?id=${two}`,
  );
  controller.update("https://online.moysklad.ru/app/#dashboard");
  expect(host.show.mock.calls).toEqual([[one], [two]]);
  expect(host.hide).toHaveBeenCalledOnce();
});
```

- [ ] **Step 2: Run unit tests and confirm missing route module**

Run: `npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- src/route.test.ts`

Expected: FAIL because `src/route.ts` does not exist.

- [ ] **Step 3: Implement exact URL parsing and transition idempotency**

```typescript
const orderIdPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isOrderId(value: string): boolean {
  return orderIdPattern.test(value);
}

export function orderIdFromMoySkladUrl(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.origin !== "https://online.moysklad.ru") return null;
  if (url.pathname !== "/app/") return null;
  const [route, query = ""] = url.hash.replace(/^#/, "").split("?", 2);
  if (route !== "customerorder/edit") return null;
  const params = new URLSearchParams(query);
  if ([...params.keys()].length !== 1 || !params.has("id")) return null;
  const id = params.get("id");
  return id && isOrderId(id) ? id.toLowerCase() : null;
}

export interface PanelHost {
  show(orderId: string): void;
  hide(): void;
}

export class RouteController {
  private activeOrderId: string | null = null;

  constructor(private readonly host: PanelHost) {}

  update(value: string): void {
    const next = orderIdFromMoySkladUrl(value);
    if (next === this.activeOrderId) return;
    this.activeOrderId = next;
    if (next) this.host.show(next);
    else this.host.hide();
  }
}
```

- [ ] **Step 4: Implement the fixed iframe host and collapse messaging**

`IframePanelHost.show(orderId)` must remove any previous root, create one
`div#pix-order-chat-extension-root`, set `display`, fixed right/top,
full-height, `z-index: 2147483647`, and width `min(420px, 100vw)` as inline
`!important` properties, and attach one open shadow root so MoySklad author CSS
cannot style the iframe. Append an iframe with an encoded `order_id` query
inside that shadow root. The iframe fills the host, has title
`Pix Logistic — чат заказа`, `allow=""`, and no sandbox relaxation.

Listen for `message` only when all checks pass:

```typescript
event.source === iframe.contentWindow
event.origin === new URL(chrome.runtime.getURL("/")).origin
event.data?.source === "pix-order-chat-extension"
event.data?.type === "resize"
typeof event.data?.collapsed === "boolean"
```

Set host width to `48px` when collapsed and back to `min(420px, 100vw)` when
expanded. `hide()` removes the message listener and root.

`src/content.ts` constructs `IframePanelHost` and `RouteController`, processes
`location.href` immediately, and registers one shared update callback for
`hashchange` and `popstate`. It unregisters neither listener during ordinary
SPA navigation and never injects a second root.

- [ ] **Step 5: Build and run injection unit checks**

Run:

```powershell
npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- src/route.test.ts
npm.cmd run typecheck --workspace pix-moysklad-chat-extension
npm.cmd run build --workspace pix-moysklad-chat-extension
```

Expected: PASS; `dist/content.js` contains the customer-order route literal and
no backend secret.

- [ ] **Step 6: Commit route injection in `pix_frontend_v2`**

```powershell
git add moysklad-chat-extension/src/content.ts moysklad-chat-extension/src/content moysklad-chat-extension/src/route.ts moysklad-chat-extension/src/route.test.ts
git commit -m "feat: inject chat on MoySklad orders"
```

### Task 10: Build fixed-origin REST, secret storage, and authenticated socket clients

**Files:**
- Create: `moysklad-chat-extension/src/panel/secretStore.ts`
- Create: `moysklad-chat-extension/src/panel/secretStore.test.ts`
- Create: `moysklad-chat-extension/src/panel/api.ts`
- Create: `moysklad-chat-extension/src/panel/api.test.ts`
- Create: `moysklad-chat-extension/src/panel/socket.ts`
- Create: `moysklad-chat-extension/src/panel/socket.test.ts`

**Interfaces:**
- Consumes: `apiUrl`, shared `OrderChatMessage`/`OrderChatPage`, `chrome.storage.local`, browser `fetch`/`WebSocket`.
- Produces: `SecretStore`, `OperatorChatApi`, `OperatorChatSocket`, and `reconnectDelay(attempt) -> number`.

- [ ] **Step 1: Write failing storage/API/socket tests**

```typescript
it("restricts storage and never syncs the shared secret", async () => {
  const chromeApi = chromeStorageStub();
  const store = new SecretStore(chromeApi);
  await store.initialize();
  await store.save("  shared-secret  ");
  expect(chromeApi.local.setAccessLevel).toHaveBeenCalledWith({
    accessLevel: "TRUSTED_CONTEXTS",
  });
  expect(chromeApi.local.set).toHaveBeenCalledWith({
    pixChatSecret: "shared-secret",
  });
  expect(chromeApi.sync).toBeUndefined();
});

it("builds only order-scoped operator requests with a header secret", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse({
    items: [],
    next_before: null,
  }));
  const api = new OperatorChatApi("shared", fetcher);
  await api.listMessages(ORDER_ID);
  expect(fetcher).toHaveBeenCalledWith(
    expect.stringContaining(`/chat/operator/orders/${ORDER_ID}/messages`),
    expect.objectContaining({
      headers: expect.objectContaining({
        "X-Pix-Chat-Secret": "shared",
      }),
    }),
  );
});

it("sends authentication before accepting room messages", () => {
  const socket = webSocketStub();
  const received = vi.fn();
  const connection = new OperatorChatSocket({
    orderId: ORDER_ID,
    secret: "shared",
    createWebSocket: () => socket,
    onMessage: received,
    onState: vi.fn(),
  });
  connection.start();
  socket.open();
  expect(socket.sent).toEqual([
    JSON.stringify({ type: "authenticate", secret: "shared" }),
  ]);
  socket.message(JSON.stringify(MESSAGE));
  expect(received).not.toHaveBeenCalled();
  socket.message(JSON.stringify({ type: "authenticated" }));
  socket.message(JSON.stringify(MESSAGE));
  expect(received).toHaveBeenCalledWith(MESSAGE);
});
```

- [ ] **Step 2: Run transport tests and confirm missing modules**

Run:

```powershell
npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- src/panel/secretStore.test.ts src/panel/api.test.ts src/panel/socket.test.ts
```

Expected: FAIL because the three client modules do not exist.

- [ ] **Step 3: Implement trusted local secret storage**

```typescript
const key = "pixChatSecret";

export class SecretStore {
  constructor(private readonly storage: Pick<typeof chrome.storage, "local">) {}

  async initialize(): Promise<void> {
    await this.storage.local.setAccessLevel({
      accessLevel: "TRUSTED_CONTEXTS",
    });
  }

  async load(): Promise<string | null> {
    const value = await this.storage.local.get(key);
    return typeof value[key] === "string" && value[key].trim()
      ? value[key]
      : null;
  }

  async save(value: string): Promise<void> {
    const normalized = value.trim();
    if (!normalized) throw new Error("Secret is required");
    await this.storage.local.set({ [key]: normalized });
  }

  async clear(): Promise<void> {
    await this.storage.local.remove(key);
  }
}
```

The secret store must never log, return from UI rendering, or write to
`chrome.storage.sync`.

- [ ] **Step 4: Implement the fixed-origin operator REST client**

`OperatorChatApi` accepts only `secret` and an injectable `fetch` function; it
does not accept an API origin or arbitrary absolute URL. Implement:

```typescript
listMessages(orderId: string, before?: string, signal?: AbortSignal): Promise<OrderChatPage>
sendMessage(orderId: string, message: string, files: File[], signal?: AbortSignal): Promise<OrderChatMessage>
downloadAttachment(orderId: string, attachmentId: string, signal?: AbortSignal): Promise<Blob>
```

Every method uses `apiUrl()` plus the exact `/chat/operator/orders/...` route
and `X-Pix-Chat-Secret`. `sendMessage` builds `FormData` and must not manually
set `Content-Type`. Map response failures to:

```typescript
export class OperatorApiError extends Error {
  constructor(public readonly status: number) {
    super(`Operator chat request failed with ${status}`);
  }
}
```

No response body or header value appears in the error message.

- [ ] **Step 5: Implement first-frame socket authentication and reconnect timing**

Convert `apiUrl("chat/operator/ws")` from HTTP(S) to WS(S), append only `room`,
and never append the secret. Export:

```typescript
export function reconnectDelay(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 30_000);
}
```

`OperatorChatSocket.start()` creates one socket; `onopen` sends the exact auth
frame. Ignore all room messages until the `authenticated` frame. On close,
report `reconnecting` and schedule one reconnect unless `stop()` was called.
`stop()` clears the timer, closes the active socket, and prevents later
callbacks. JSON parse failures call `onProtocolError` without echoing the frame.

- [ ] **Step 6: Run transport, type, and secret scans**

Run:

```powershell
npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- src/panel/secretStore.test.ts src/panel/api.test.ts src/panel/socket.test.ts
npm.cmd run typecheck --workspace pix-moysklad-chat-extension
npm.cmd run build --workspace pix-moysklad-chat-extension
rg -n "shared-secret|X-Pix-Chat-Secret=.*" moysklad-chat-extension\dist
```

Expected: tests/typecheck/build PASS; the scan prints no test secret or
credential assignment in the artifact.

- [ ] **Step 7: Commit extension transport in `pix_frontend_v2`**

```powershell
git add moysklad-chat-extension/src/panel/api.ts moysklad-chat-extension/src/panel/api.test.ts moysklad-chat-extension/src/panel/secretStore.ts moysklad-chat-extension/src/panel/secretStore.test.ts moysklad-chat-extension/src/panel/socket.ts moysklad-chat-extension/src/panel/socket.test.ts
git commit -m "feat: connect extension to operator chat API"
```

### Task 11: Implement the operator chat panel, files, and failure recovery

**Files:**
- Create: `moysklad-chat-extension/src/panel/orderContext.ts`
- Create: `moysklad-chat-extension/src/panel/orderContext.test.ts`
- Create: `moysklad-chat-extension/src/panel/panelState.ts`
- Create: `moysklad-chat-extension/src/panel/panelState.test.ts`
- Create: `moysklad-chat-extension/src/panel/useOrderChat.ts`
- Create: `moysklad-chat-extension/src/panel/AttachmentView.tsx`
- Create: `moysklad-chat-extension/src/panel/styles.css`
- Modify: `moysklad-chat-extension/src/panel/App.tsx`
- Modify: `moysklad-chat-extension/src/panel/main.tsx`

**Interfaces:**
- Consumes: `SecretStore`, `OperatorChatApi`, `OperatorChatSocket`, shared order-chat model/helpers.
- Produces: the complete first-run/chat/error UI and collapse resize messages.

- [ ] **Step 1: Write failing order-context/stale-result tests**

```typescript
// src/panel/orderContext.test.ts
import { describe, expect, it } from "vitest";
import { orderIdFromPanelUrl, RequestGeneration } from "./orderContext";

const orderId = "00000000-0000-0000-0000-000000000001";

describe("panel order context", () => {
  it("requires one UUID order_id query", () => {
    expect(orderIdFromPanelUrl(`chrome-extension://id/panel.html?order_id=${orderId}`)).toBe(orderId);
    expect(orderIdFromPanelUrl("chrome-extension://id/panel.html")).toBeNull();
    expect(orderIdFromPanelUrl("chrome-extension://id/panel.html?order_id=bad")).toBeNull();
  });

  it("invalidates late work after order/session replacement", () => {
    const generation = new RequestGeneration();
    const first = generation.next();
    const second = generation.next();
    expect(generation.isCurrent(first)).toBe(false);
    expect(generation.isCurrent(second)).toBe(true);
  });
});
```

Add pure reducer tests in `panelState.test.ts` proving that switching orders
clears messages/cursor/action errors and starts expanded, a failed send keeps
the draft and selected `File` objects, a successful send clears both and
merges the server response by ID, a repeated REST/WebSocket message is not
duplicated, and pagination prepends older immutable messages in chronological
order.

- [ ] **Step 2: Run panel unit tests and confirm missing context module**

Run: `npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- src/panel/orderContext.test.ts`

Expected: FAIL because `orderContext.ts` does not exist.

- [ ] **Step 3: Implement order context and the order-chat hook**

`orderContext.ts` imports `isOrderId` from `route.ts` instead of copying the
UUID expression and exports a
monotonic `RequestGeneration` whose `next()` increments an integer token.

`panelState.ts` owns those tested transitions; `useOrderChat(orderId, secret)`
owns the effects and these exact state values:

```typescript
type PanelStatus =
  | "loading"
  | "ready"
  | "unavailable"
  | "temporary-error";

type ConnectionState = "connecting" | "connected" | "reconnecting";
```

On mount/order/secret change it aborts old fetches, stops the old socket,
clears history/cursor/action errors, loads page one, then starts the socket. On
socket authentication set `connected`; on every reconnect completion reload
the current page to fill gaps. Merge POST, REST, and WebSocket messages by ID
through `mergeOrderChatMessages`.

Map `OperatorApiError(401)` to an `onUnauthorized` callback that clears stored
secret; map `404` to `unavailable`; map `503` and network errors to
`temporary-error`. Ignore every result whose request generation is stale.

`send(text, files)` validates files, rejects an empty payload, leaves draft
state untouched on failure, and clears it only after the POST succeeds.

- [ ] **Step 4: Implement safe attachment preview/download**

`AttachmentView` calls `api.downloadAttachment(orderId, attachment.id)`.
Images get a component-owned Blob URL, `<img alt={attachment.filename}>`, and
URL revocation during cleanup. A click downloads every type using a temporary
`<a download={attachment.filename}>`. Render filenames as React text only.
Show `Не удалось загрузить файл` after a failed preview/download.

- [ ] **Step 5: Implement the complete panel UI**

`App` must implement these mutually exclusive states:

- invalid/missing `order_id`: `Чат недоступен для этого заказа`;
- no stored secret: password input labeled `Общий секрет`, submit
  `Сохранить и открыть чат`, no network call before submit;
- unauthorized: return to the same secret form with `Неверный секрет`;
- unavailable order: `Чат недоступен для этого заказа`;
- temporary failure: `Не удалось загрузить переписку` and button `Повторить`;
- ready: header, connection label, paginated history, safe attachments, draft,
  selected-file chips, file picker, submit button, `Загрузить предыдущие`, and
  `Сменить секрет`.

Disable duplicate submission while POST is active. `Сменить секрет` stops the
current socket, clears only `pixChatSecret` through `SecretStore`, and returns
to the private first-run form without putting the old value into an input,
message, log, or URL.

The collapse button posts only:

```typescript
window.parent.postMessage(
  {
    source: "pix-order-chat-extension",
    type: "resize",
    collapsed,
  },
  "https://online.moysklad.ru",
);
```

It starts expanded on every new iframe/order. Selected files remain after a
failed request and are cleared only after a successful send. Use the shared
Russian validation strings from `validateSelectedFiles`.

`styles.css` sets a 420 px desktop panel, full height, white/slate accessible
contrast, keyboard focus rings, 320 px scrolling history, left manager bubbles,
right client bubbles, and a 48 px collapsed layout. Do not import MoySklad CSS,
remote fonts, or remote icons.

- [ ] **Step 6: Wire entry and run panel checks**

`main.tsx` imports `styles.css`, initializes `SecretStore(chrome.storage)`,
parses `location.href`, and renders `<App orderId={...} secretStore={...} />`
into `#root` with `createRoot`.

Run:

```powershell
npm.cmd run test:unit --workspace pix-moysklad-chat-extension -- src/panel/orderContext.test.ts src/panel/panelState.test.ts src/panel/api.test.ts src/panel/socket.test.ts
npm.cmd run lint --workspace pix-moysklad-chat-extension
npm.cmd run typecheck --workspace pix-moysklad-chat-extension
npm.cmd run build --workspace pix-moysklad-chat-extension
```

Expected: PASS; Vite reports no external runtime imports.

- [ ] **Step 7: Commit the operator UI in `pix_frontend_v2`**

```powershell
git add moysklad-chat-extension/src/panel moysklad-chat-extension/panel.html
git commit -m "feat: build MoySklad order chat panel"
```

### Task 12: Add an unpacked-extension smoke and integrate frontend checks

**Files:**
- Create: `moysklad-chat-extension/playwright.config.ts`
- Create: `moysklad-chat-extension/tests/extension-smoke.spec.ts`
- Create: `moysklad-chat-extension/README.md`
- Modify: `moysklad-chat-extension/package.json`
- Modify: `package.json`
- Modify: `package-lock.json`

**Interfaces:**
- Consumes: built unpacked extension, Playwright persistent Chromium context.
- Produces: automated proof of injection, first-run secret entry, linked history, collapse, order switch, and teardown.

- [ ] **Step 1: Write the failing extension smoke**

Configure a single Chromium project with a 60-second timeout and no frontend
global setup. In the smoke:

```typescript
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const profilePath = await mkdtemp(join(tmpdir(), "pix-extension-smoke-"));
const context = await chromium.launchPersistentContext(profilePath, {
  channel: "chromium",
  headless: true,
  args: [
    `--disable-extensions-except=${extensionPath}`,
    `--load-extension=${extensionPath}`,
  ],
});

// In the test's finally block:
await context.close();
await rm(profilePath, { recursive: true, force: true });
```

Fulfill `https://online.moysklad.ru/app/*` with a small local HTML document.
Fulfill operator requests at `http://localhost:8000/api_v1/**`. Return `401`
for `wrong-secret`; for `smoke-secret`, require the exact header and return two
paginated pages containing one repeated immutable message plus text/filename
values that look like HTML. Track POST and attachment requests without logging
their header values or multipart bodies.

Assert this sequence:

1. dashboard hash has no extension root;
2. customer-order hash creates exactly one iframe;
3. iframe shows the secret form and makes no API request before submission;
4. entering `wrong-secret` shows `Неверный секрет`, clears the stored value,
   and never shows the value in the DOM;
5. entering `smoke-secret` shows the fixture message, loading the older page
   preserves chronological order and deduplicates the repeated ID, HTML-like
   text remains literal, and no fixture script/global executes;
6. a failed POST preserves typed text and selected filename, while a succeeding
   retry clears them and renders the one canonical returned message;
7. `Сменить секрет` returns to a blank secret form; re-entry restores chat;
8. collapse changes the host width to `48px`, while hostile host-page CSS does
   not alter a checked panel style;
9. changing the hash to a second UUID creates fresh expanded context and the
   second order request;
10. changing to `#counterparty/edit` removes the extension root.

- [ ] **Step 2: Add the smoke script and confirm it fails before wiring**

Add `"test:smoke": "playwright test -c playwright.config.ts"` to the extension
package, then run:

```powershell
npm.cmd run build --workspace pix-moysklad-chat-extension
npm.cmd run test:smoke --workspace pix-moysklad-chat-extension
```

Expected: FAIL until the smoke fixture, iframe selectors, and request stubs are
complete.

- [ ] **Step 3: Complete the smoke and root check integration**

Add `@playwright/test: "1.62.1"` to extension dev dependencies. Change the
extension `check` script to:

```json
"check": "npm run lint && npm run typecheck && npm run test:unit && npm run build && npm run check:manifest && npm run test:smoke"
```

Add root script:

```json
"check:extension": "npm run check --workspace pix-moysklad-chat-extension"
```

Insert `npm run check:extension` into the root `check` before the Next.js build.
`README.md` documents unpacked installation, one-time secret entry, local build,
production build with `PIX_EXTENSION_BACKEND_URL`, secret rotation, and the
unencrypted `chrome.storage.local` limitation. It must contain no real secret.

- [ ] **Step 4: Reinstall from the lock and run extension checks**

Run:

```powershell
npm.cmd install --package-lock-only
npm.cmd ci
npm.cmd run check:extension
git diff --check
```

Expected: unit/type/lint/build/manifest/smoke all PASS from a clean lockfile
install.

- [ ] **Step 5: Commit smoke/check integration in `pix_frontend_v2`**

```powershell
git add package.json package-lock.json moysklad-chat-extension
git commit -m "test: verify MoySklad chat extension"
```

### Task 13: Add proxy limits, cutover documentation, and final cross-repository verification

**Files:**
- Create: `tests/test_nginx_operator_chat.py`
- Create: `docs/operations/moysklad-chat-extension-cutover.md`
- Modify: `conf.d/default.conf`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `docs/LOCAL_DEVELOPMENT.md`
- Modify: `docs/ENVIRONMENT.md`
- Modify: `scripts/check.ps1`

**Interfaces:**
- Consumes: finished backend/API, website contract, extension build and smoke.
- Produces: bounded NGINX routes, operator runbook, source-of-truth docs, and final verification evidence.

- [ ] **Step 1: Write a failing static NGINX contract test**

```python
# tests/test_nginx_operator_chat.py
from pathlib import Path


def test_operator_chat_proxy_has_upload_rate_and_websocket_rules():
    source = Path("conf.d/default.conf").read_text(encoding="utf-8")
    assert "zone=operator_chat_rest:10m rate=10r/s" in source
    assert "zone=operator_chat_ws:10m rate=5r/s" in source
    assert "location = /api_v1/chat/operator/ws" in source
    assert "location ^~ /api_v1/chat/operator/" in source
    assert "client_max_body_size 205m" in source
    assert "limit_req zone=operator_chat_rest burst=20 nodelay" in source
    assert "limit_req zone=operator_chat_ws burst=10 nodelay" in source
    assert "proxy_set_header Upgrade $http_upgrade" in source
```

- [ ] **Step 2: Run the proxy test and confirm missing rules**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_nginx_operator_chat.py -q`

Expected: FAIL because operator-specific limits and locations are absent.

- [ ] **Step 3: Add exact NGINX zones and operator locations**

At the top-level HTTP include, add:

```nginx
limit_req_zone $binary_remote_addr zone=operator_chat_rest:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=operator_chat_ws:10m rate=5r/s;
```

Inside the TLS server, before the generic `/api_v1/` location, add:

```nginx
location = /api_v1/chat/operator/ws {
    limit_req zone=operator_chat_ws burst=10 nodelay;
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

location ^~ /api_v1/chat/operator/ {
    client_max_body_size 205m;
    limit_req zone=operator_chat_rest burst=20 nodelay;
    proxy_pass http://backend;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Keep the existing customer upload and WebSocket locations.

- [ ] **Step 4: Write exact operational documentation**

The cutover runbook must contain these checked phases:

1. confirm PostgreSQL backup and MinIO volume health;
2. generate a 32+ byte random shared secret outside source control, install it
   in the approved backend secret store as
   `MOYSKLAD_CHAT_EXTENSION_SECRET`, and distribute that same value to trusted
   operator workstations through the approved private channel;
3. build the extension with
   `PIX_EXTENSION_BACKEND_URL=https://pixlogistic.com/api_v1`;
4. install the unpacked/packaged artifact and enter the shared secret;
5. inspect the active database URL without printing credentials;
6. manually review and apply only revision `e3b7c9d1a204` after explicit
   approval;
7. deploy backend with order chat enabled and confirm `/api_v1/health` and
   `/api_v1/capabilities` without printing configuration values;
8. smoke one linked order client-to-operator and operator-to-client with an
   image, PDF, notification, reconnect, and download;
9. list the existing webhook without printing its secret URL, then remove it
   only after explicit approval;
10. verify no new MoySklad description/file projection occurs;
11. rollback the backend artifact and webhook registration before any later
    cleanup if cutover fails.

State explicitly that historical rendered comments/files are not erased and
that dropping obsolete tables is a separate destructive operation excluded
from this runbook.

Update `docs/ARCHITECTURE.md` from MoySklad projection to Chrome operator
transport, update local setup/config documentation, and add extension check and
manual smoke expectations to `README.md`. The extension's own `README.md` from
Task 12 remains the operator/developer source for workspace commands and the
shared API boundary.

- [ ] **Step 5: Run final backend verification after the final backend edit**

Run from `pix_backend`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
.\.venv\Scripts\python.exe -m alembic history
.\.venv\Scripts\python.exe -c "import main; print(main.app.title)"
git diff --check
```

Expected: Ruff and all tests PASS; Alembic reports one head at
`e3b7c9d1a204`; fresh import prints `Pix Logistic API`; no migration runs.

- [ ] **Step 6: Run final frontend and extension verification after the final frontend edit**

Run from `pix_frontend_v2`:

```powershell
npm.cmd ci
npm.cmd run check
git diff --check
```

Expected: lint, guards, website Vitest, extension unit/type/build/manifest/smoke,
Next production build, and website Playwright all PASS. If Google Fonts fail
only because the network is restricted, record that external failure and rerun
the other deterministic commands; do not claim the full check passed.

- [ ] **Step 7: Inspect secret and permission boundaries**

Run from the two repository roots:

```powershell
rg -n "MOYSKLAD_CHAT_EXTENSION_SECRET=.*[^=]$|X-Pix-Chat-Secret=.*|type=authenticate.*secret" . -g '!*.md' -g '!package-lock.json' -g '!node_modules/**' -g '!dist/**'
rg -n '"(<all_urls>|cookies|tabs|webRequest|declarativeNetRequest|history|downloads)"' moysklad-chat-extension\dist\manifest.json
```

Expected: no credential-bearing assignments and no forbidden manifest
permissions. Source code may contain the header name and authentication frame
field separately; it must not contain a real value.

- [ ] **Step 8: Commit final documentation/proxy changes separately**

From `pix_backend`:

```powershell
git add conf.d/default.conf docs/ARCHITECTURE.md docs/ENVIRONMENT.md docs/LOCAL_DEVELOPMENT.md docs/operations/moysklad-chat-extension-cutover.md README.md scripts/check.ps1 tests/test_nginx_operator_chat.py
git commit -m "docs: add extension chat cutover runbook"
```

Review `git status --short` in both worktrees. Only user-owned pre-existing
changes outside the isolated worktrees may remain.

## Completion Evidence

Before reporting completion, record:

- backend commit IDs and frontend commit IDs from every task;
- `scripts/check.ps1` final exit code;
- `alembic history` head without applying it;
- `npm.cmd ci` and `npm.cmd run check` final exit codes;
- extension manifest permission-check output;
- automated extension smoke output;
- the fact that live signed-in MoySklad smoke, production migration, secret
  installation, deployment, and webhook removal remain manual approved
  operations.
