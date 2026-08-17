# Production QA Remediation Design

Date: 2026-08-17

## Goal

Remove the production defects confirmed during end-to-end testing of PIX Logistic while preserving all real customer data and keeping the previous server available as a rollback and Telegram bridge until the new host can reach Telegram directly.

## Confirmed problems

1. A completed checkout waits for Telegram delivery. When Telegram is unreachable from the new host, NGINX returns 504 even though the order already exists in MoySklad.
2. A normalized duplicate address reaches the database uniqueness constraint but the asyncpg constraint name is not extracted, so the API returns 500 instead of the existing conflict response.
3. Order editing creates new MoySklad products before verifying that the required `Изменен клиентом` state exists. A missing state therefore leaves orphan products and produces an unhandled 500.
4. NGINX upgrades `/api_v1/chat/ws` but not `/api_v1/notifications/ws`, so realtime notifications receive an HTTP 404 handshake response.
5. The order-chat frontend is visible while `ENABLE_MOYSKLAD_ORDER_CHAT=false`, exposing a deliberately disabled feature as a broken UI.
6. The MoySklad account has neither the `Изменен клиентом` order state nor an embedded customer-order print template, preventing successful order edits and PDF export.

## Chosen approach

Use targeted, reversible fixes instead of a broad notification/outbox refactor.

- Make Telegram a bounded best-effort side effect for user-facing order operations.
- Preserve database uniqueness as the source of truth and improve asyncpg error classification.
- Validate all required MoySklad metadata before creating external entities.
- Add the missing explicit WebSocket proxy location.
- Gate the frontend order-chat UI with a production build setting.
- Repair the two missing MoySklad account settings.

This approach is smaller than introducing a durable notification queue or a runtime feature-capabilities API, while directly addressing every observed failure.

## Backend design

### Bounded Telegram delivery

Add one shared best-effort Telegram delivery function. It will:

- await the existing notifier through `asyncio.wait_for`;
- read a short timeout from `config.Settings`, with a production-safe default of three seconds;
- catch timeout and transport exceptions;
- log failure without secrets or message credentials;
- never convert an already successful business operation into an HTTP failure.

Order creation, order editing, state confirmation, and cancellation will use this boundary. Existing idempotency completion remains before the optional notification. User-verification notification behavior may reuse the helper where doing so does not change the verification transaction.

### Address conflict classification

Replace the single-level `exc.orig.diag.constraint_name` lookup with a small cycle-safe exception-chain traversal. It will inspect SQLAlchemy, asyncpg-adapter, cause, and context layers for either `diag.constraint_name` or `constraint_name`. Only the known `uq_address_user_normalized_name` constraint maps to `AddressNameConflict`; unknown integrity errors still propagate.

The existing route-level conflict mapping will continue to return HTTP 409 with the current public error contract.

### MoySklad order-change preflight

Resolve the `Изменен клиентом` state metadata before calling product creation. If state metadata is missing:

- no product or order mutation is attempted;
- the backend raises a typed integration-configuration error;
- the route returns a controlled service/configuration response instead of an internal traceback.

After preflight succeeds, the current position replacement and state update flow remains unchanged. Telegram delivery runs only after the MoySklad update and follows the bounded best-effort rule.

No database schema or Alembic migration is required.

## Proxy and frontend design

### Notification WebSocket

Add an explicit `/api_v1/notifications/ws` NGINX location matching the proven chat WebSocket upgrade headers and forwarding rules. Keep the ordinary `/api_v1/` HTTP proxy unchanged.

The repository NGINX configuration and the host-managed production configuration must be kept equivalent. Before production replacement, copy the active configuration to a timestamped backup, then run `nginx -t` before reload.

### Disabled order chat

Add a public frontend build flag whose production value follows the disabled backend integration. When false, order-chat controls are not rendered and no chat history or chat WebSocket request is started. The normal enabled path remains covered by existing tests.

## MoySklad account configuration

Using the already authenticated production account:

1. Create the exact customer-order state `Изменен клиентом` if it is still absent.
2. Configure or select an embedded customer-order print template that MoySklad can export as PDF.
3. Do not modify unrelated states, workflows, counterparties, products, or documents.

The code must still handle either setting becoming unavailable later.

## Verification

Implementation follows test-driven development:

- reproduce asyncpg-style nested constraint extraction with a failing unit test;
- prove a Telegram timeout returns the successful order/change result and records the timeout only in logs;
- prove a missing MoySklad state makes zero product-creation calls and returns the controlled error;
- prove the frontend disabled-chat flag prevents rendering and network startup;
- run backend `scripts/check.ps1` after final backend changes;
- run frontend `npm.cmd run check` after final frontend changes;
- validate the composed/repository NGINX configuration and production `nginx -t`;
- deploy immutable backend and frontend images while retaining the prior image tags;
- verify health, restart counts, logs, HTTP pages, notification WebSocket upgrade, address duplicate response, one idempotent checkout retry, one order edit, PDF download, and Telegram timeout behavior on production.

## Cleanup and rollback

After successful verification, delete only the QA entities created in the earlier test: customer order number 2512 and the two explicitly identified example products, subject to checking that they are still the same QA records and are not referenced by other documents. The already removed QA address requires no action.

Do not delete volumes, databases, real customer records, old images, or old-server data. Keep the old server and its Telegram bridge running until direct Telegram connectivity from the new host is independently proven. Rollback consists of restoring the saved NGINX configuration and restarting the previously tagged backend/frontend images.

## Out of scope

- Database migrations or data repair unrelated to the named QA records.
- A durable notification outbox or queue.
- Enabling the full MoySklad order-chat integration and scheduler.
- Turning off or deleting the previous server.
