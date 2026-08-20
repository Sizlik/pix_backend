# Remove Telegram Integration Design

**Date:** 2026-08-20

**Status:** Approved

## Goal

Remove Telegram from the active Pix Logistic product, source code, runtime
configuration, deployment topology, API contracts, and browser UI. Remove the
legacy general-support chat that depends on Telegram while preserving the
order-specific chat backed by PostgreSQL, MinIO, MoySklad, Redis, and browser
WebSockets.

## Context

The production host can no longer reach Telegram reliably. User verification
currently persists `is_verified=true` and then waits for a Telegram side
notification. That wait outlives the NGINX response timeout, so the browser
receives `504` or disconnects even though verification succeeded. Telegram is
also coupled to order creation and changes, status notifications, the legacy
support chat, order-chat outbox events, a separate bot container, public API
routes, account linking, production validation, environment variables, and
frontend presentation.

The product already has durable replacements for the important user-facing
flows:

- account state and email verification in PostgreSQL and Redis;
- orders and operator workflows in MoySklad;
- order status and message notifications in the website notification system;
- order-specific conversation history in PostgreSQL and MinIO, projected to
  MoySklad and streamed to browsers through Redis/WebSockets.

The general support chat has no non-Telegram manager channel and will be
removed rather than left as a user-facing dead end.

## Scope

### Backend runtime

Remove all Telegram construction and send paths, including:

- `bot/sender.py` and the remaining active `bot` package;
- the `/api_v1/bot/*` router;
- `PUT /api_v1/users/telegram/{telegram_id}`;
- verification-time group notifications;
- group notifications for order creation, edits, confirmation, and
  cancellation;
- user notifications in the scheduler and MoySklad webhook paths;
- legacy support-chat forwarding and bot replies;
- order-chat Telegram outbox events and their handlers;
- the Telegram notifier adapter and its dependency wiring.

Email verification will still link a newly verified user to a MoySklad
counterparty on a best-effort basis, but it will perform no Telegram work. A
successful local verification must not wait for any notification channel.

Order use cases will no longer accept notifier dependencies. Their business
result depends only on the existing address, product, MoySklad, idempotency,
and persistence boundaries. Website notifications already produced for order
status and order-chat changes remain in place.

### Public API contracts

Remove these legacy endpoints:

- `/api_v1/bot/*`;
- `/api_v1/users/telegram/{telegram_id}`;
- legacy general-chat collection, message, room, reply, and support-WebSocket
  behavior under `/api_v1/chat`.

Keep these order-chat endpoints:

- `GET /api_v1/chat/orders/{order_id}/messages`;
- `POST /api_v1/chat/orders/{order_id}/messages`;
- `GET /api_v1/chat/attachments/{attachment_id}`;
- `/api_v1/chat/ws` for an authenticated order room.

The order-chat WebSocket will require an explicit `room` query parameter. A
missing room is rejected as an application-level bad request/close rather than
falling back to the user's general-support room. Order ownership checks and
the existing HTTP-only client-send rule remain unchanged.

`OrderChangesResponse` changes from
`{order, changed, notification_sent}` to `{order, changed}`. The frontend is
compatible with a rolling deployment because old responses may contain an
ignored extra field and the old frontend treats an absent
`notification_sent` as a non-warning result.

### Order chat

Order chat remains enabled independently of Telegram:

- client messages and attachments are committed to PostgreSQL and MinIO;
- `sync_order` remains the only outbox event produced for a client message;
- manager replies from MoySklad are committed, notified in the website, and
  published to connected browsers without a Telegram event;
- projection failures are logged with order ID and a bounded error code rather
  than enqueued for Telegram;
- no Telegram event type is registered in `OrderChatOutboxWorker`.

The existing generic outbox worker stays because it drives MoySklad
synchronization. Only Telegram-specific handlers and event production are
removed.

### General support chat

Remove the legacy general-support chat completely:

- remove its frontend widget and API client;
- remove its HTTP and WebSocket behavior;
- remove `ChatRoom`, `Message`, their managers, and their dependency factories;
- remove notification type `MESSAGE` and its response-enrichment branch;
- retain notification types `ORDER_MESSAGE` and `ORDER_UPDATED`.

The order-specific chat uses `order_chat_*` tables and remains supported. Code
that lazily imports legacy order messages at read time will be removed after
the migration provides an eager, reviewed backfill.

### Frontend

Remove:

- the Telegram social icon and links from public/authenticated pages;
- the bot promotion block and `t.me` links;
- `src/app/telegram/[telegram_id]/page.jsx`;
- the floating support-chat component and its hard-coded WebSocket URL;
- general-chat API helpers and types;
- Telegram warning presentation after an order edit;
- Telegram-specific mocks and browser tests.

Preserve the order detail `OrderChatPanel`, its HTTP requests, and its
room-scoped WebSocket connection.

### Configuration, dependencies, and deployment

Remove active settings and environment inventory for:

- `BOT_TOKEN`;
- `CHAT_ID`;
- `HELP_CHAT_ID`;
- `TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS`.

Production preflight will no longer require Telegram for MoySklad order chat.
Remove the `aiogram` dependency and dependencies that are present solely for
it; retain `aiohttp`, which is used by link preview fetching.

Remove the `bot` service from the repository Compose topology. Removing the
already-running production bot container and deleting Telegram variables from
the production environment are explicit deployment actions, not import,
test, setup, or migration side effects.

## Database migration

Create a new reviewed Alembic revision. Do not edit or delete historical
revisions: they are required to reproduce the database schema from an empty
database.

The upgrade performs these operations in one transaction where PostgreSQL
allows it:

1. Identify legacy messages that are unambiguously associated with an order
   chat. Account for both historical encodings seen in this schema: a message
   targeting `chat_room.id` and a message targeting the room's `order_id`.
2. Abort with a clear migration error if an order association is ambiguous or
   if a preserved order message has no usable `chat_room.client_id`.
3. Insert missing rows into `order_chat_message` with source `legacy`, the
   original body and timestamp, the resolved client ID, and the original
   message ID in `legacy_message_id`. Existing rows with that
   `legacy_message_id` are not duplicated.
4. Update `ORDER_MESSAGE` notification `object_id` values from the legacy
   message ID to the corresponding new `order_chat_message.id`.
5. Verify that every eligible legacy order message is either newly inserted or
   already represented before destructive statements run.
6. Delete notifications of type `MESSAGE`, which belong only to the removed
   general-support chat.
7. Delete every outbox row whose event type is
   `telegram_client_alert`, `telegram_manager_alert`, or
   `telegram_projection_error`, regardless of delivery status.
8. Drop `message`, then `chat_room`, respecting their foreign-key order.
9. Drop `user.telegram_id`.

`order_chat_message.legacy_message_id` remains as migration provenance and a
deduplication guard. `ORDER_MESSAGE` and `ORDER_UPDATED` notifications and all
`order_chat_*` data remain intact.

The downgrade recreates the legacy tables and nullable `user.telegram_id`
column only. It cannot recreate deleted general-support history, Telegram
outbox rows, or Telegram IDs. Restoring those values requires the pre-migration
database backup.

The dedicated `bot@pixlogistic.com` account is not blindly deleted by the
migration. The deployment runbook may remove it only after a read-only
foreign-key/reference audit proves it is the exact obsolete bot account and no
retained row depends on it.

## Deployment and rollback

No agent, setup script, test, application startup, or container entrypoint may
apply the migration automatically.

Production rollout requires a separately authorized operation:

1. Record the current backend/frontend image tags and create a validated
   PostgreSQL backup.
2. Audit legacy order-message counts, migration eligibility, notification
   mappings, and the obsolete bot account without printing customer content or
   secrets.
3. Build and verify immutable backend and frontend release images.
4. Deploy the Telegram-free frontend and backend. Extra legacy tables and the
   `telegram_id` column are harmless during this short compatibility window;
   the new backend performs no new writes to them.
5. Manually review the exact Alembic revision and active database URL, then run
   `alembic upgrade` only with explicit approval.
6. Verify health, registration/verification latency, order create/edit/state
   transitions, website notifications, order-chat HTTP/WebSocket/MoySklad
   round trips, and absence of Telegram network attempts.
7. Remove only the obsolete production bot service/container and remove the
   four Telegram variables from the protected production environment.

Before the migration, rollback is an image-tag restore. After the destructive
migration, code rollback also requires the schema downgrade; restoring deleted
support history or Telegram identity data requires the validated backup.

## Error handling and observability

- Email verification returns according to local verification and MoySklad
  linking behavior only; no Telegram timeout can delay the response.
- Order mutations retain their existing domain and integration error mapping.
  They no longer return notification-channel warnings.
- Order-chat projection errors are logged without message bodies, attachment
  contents, tokens, webhook secrets, or customer credentials.
- Unknown historical Telegram outbox rows are removed by migration instead of
  being retried or marked dead by the new worker.
- Requests to removed endpoints return the normal FastAPI `404` response.

## Documentation and historical records

Update active documentation and templates:

- backend and frontend README files;
- both `AGENTS.md` files where they describe active architecture;
- `docs/ARCHITECTURE.md`, `docs/ENVIRONMENT.md`,
  `docs/LOCAL_DEVELOPMENT.md`, and `docs/SECURITY_NOTES.md`;
- active environment examples, production preflight tests, Compose files, and
  API URL guards.

Historical Alembic revisions and archived design/plan documents remain
unchanged. A repository-wide search may contain `telegram` only in those
historical records after implementation.

## Testing

### Backend

- Add migration tests proving legacy order messages and `ORDER_MESSAGE`
  notification links survive while support messages, `MESSAGE` notifications,
  Telegram outbox events, legacy tables, and `user.telegram_id` are removed.
- Add an ambiguity/preflight migration test that fails before destructive
  statements.
- Update verification tests to prove no notification sender is called or
  required.
- Update order creation, changes, confirmation, and cancellation tests for the
  notifier-free signatures and `{order, changed}` response.
- Update order-chat service, synchronizer, outbox, API, notification, config,
  production-preflight, import, and app-route tests.
- Delete Telegram-only tests and ensure no live external integration is called.
- Run `scripts/check.ps1`, `alembic history`, and manually review the generated
  migration.

### Frontend

- Update unit and Playwright coverage to prove no Telegram UI, bot-link page,
  support widget, general-chat API call, or Telegram warning remains.
- Preserve order-chat HTTP/WebSocket tests and website notification tests.
- Update the mock backend and source guards.
- Run `npm.cmd run check` and the build/API URL checks required by the frontend
  agent guide.

### Cross-repository acceptance

- Registration and a correct verification code complete well below the NGINX
  timeout when Telegram is unreachable.
- Creating, editing, confirming, and cancelling an order makes no Telegram
  request and preserves its existing MoySklad result.
- Order-chat messages, files, browser updates, MoySklad projection, and website
  notifications continue to work.
- The general support widget and all Telegram-facing UI/routes are absent.
- Active configuration and deployment files contain no Telegram credential or
  service requirement.
- Final static search finds Telegram references only in immutable historical
  migrations and archived specs/plans.

## Non-goals

- Replacing Telegram with another messaging provider.
- Replacing the removed general support chat with email or a new operator UI.
- Redesigning the order-chat UI or MoySklad projection protocol.
- Automatically applying a production migration or deleting a production
  container, secret, user, or backup.
