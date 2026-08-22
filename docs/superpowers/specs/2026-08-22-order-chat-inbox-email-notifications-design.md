# Order Chat Inbox and Email Notifications Design

**Date:** 2026-08-22

**Status:** Approved

**Repositories:** `pix_backend`, `../pix_frontend_v2`

## Summary

Pix Logistic will extend the order-specific chat with an operator inbox,
global operator unread state, clearer customer notifications, and durable
email notifications. Customers continue to chat inside a website order.
Operators use the existing Chrome extension in MoySklad, but the extension is
available throughout the MoySklad application and can switch between active
order conversations.

Every message has exactly one email recipient:

- a customer message emails the configured manager mailbox;
- a manager message emails the customer who owns the order.

Email delivery is decoupled from the message request through a PostgreSQL
outbox. A temporary SMTP.BZ failure never rolls back a chat message, and a
committed email job is retried without creating duplicate jobs.

## Current System

The current implementation already provides:

- immutable order-specific messages and attachments in PostgreSQL and MinIO;
- customer and operator REST/WebSocket transports over one canonical history;
- a shared extension secret and live linked-order verification;
- website `ORDER_MESSAGE` notifications when a manager sends a message;
- a realtime website unread-notification count;
- a notification row that opens the related website order;
- an extension panel that exists only while a customer-order route is open.

The gaps addressed by this design are:

- website message notifications do not identify the order by name/number;
- opening a notification does not explicitly expand and focus the order chat;
- the extension has no inbox or navigation between conversations;
- operators have no unread state for customer messages;
- chat messages do not produce email notifications;
- the existing verification-code email function is not a reusable, durable
  delivery boundary for chat notifications.

## Accepted Product Decisions

- Only the recipient is emailed. The sender never receives their own message
  by email.
- Each message produces its own immediate email job; messages are not batched
  into a digest.
- Email contains the order name/number, an HTML-escaped preview of at most 300
  characters, attachment count, and a button that opens the order.
- The manager recipient is configured as `Pixtool22@gmail.com` in production,
  through environment configuration rather than a hard-coded application
  constant.
- The operator inbox contains only orders with at least one canonical chat
  message and is ordered by latest message first.
- Selecting an inbox item navigates the main MoySklad application to that
  customer order and opens its chat in the extension panel.
- The extension provides a Back control that returns to the inbox without
  navigating the main MoySklad page away from the selected order.
- Operator unread state is global. Opening a conversation in any trusted
  extension installation clears its unread count for every manager.
- The website uses the existing Notifications section and menu counter. A
  separate unread badge in the website order list is outside this scope.
- No chat attachment is included as an email attachment.

## Goals

- Tell customers which order has a new manager message and let them open the
  expanded chat with one click.
- Give operators a realtime inbox of active order conversations.
- Let an operator move from the inbox into a MoySklad order and return to the
  inbox without losing the MoySklad order page.
- Track a global unread count for customer messages in each operator
  conversation and across the inbox.
- Notify the correct email recipient for every newly inserted message.
- Preserve successful message creation when email or Redis is unavailable.
- Retry email delivery durably and deduplicate jobs by canonical message ID.
- Preserve the current room-scoped authorization, history, attachment limits,
  and shared-secret security model.

## Non-goals

- Per-manager identities, unread state, names, assignments, or audit trails.
- A general support-chat room independent of an order.
- Email digests, user email preferences, unsubscribe controls, or marketing
  mail.
- Emailing attachment bytes or rendering untrusted HTML from a message.
- Showing a message badge on every website order card.
- Search, archive, pin, assign, edit, delete, typing indicators, or read
  receipts visible to the other party.
- Replacing SMTP.BZ, changing registration/reset emails, or renaming the
  existing credential in the same release.
- Destructive removal of retained MoySklad projection tables or old messages.

## Architecture

### Components

1. **Order-chat persistence** atomically stores a canonical message and its
   recipient-side effects: operator unread state and one email outbox job for a
   customer message, or a website notification and one email outbox job for a
   manager message.
2. **Operator inbox service** lists durable conversation summaries, clears
   global operator unread state, and publishes summary changes after commit.
3. **Operator inbox realtime** uses a dedicated shared-secret WebSocket. The
   existing room WebSocket remains mandatory and room-scoped for message
   history while a conversation is open.
4. **Email outbox dispatcher** claims pending jobs from PostgreSQL, renders a
   fixed HTML/plain-text template, calls SMTP.BZ with a bounded timeout, and
   records success or a retry schedule.
5. **Website notifications UI** displays the cached order name and routes the
   customer to an explicitly expanded chat within the existing order page.
6. **Extension inbox UI** remains an isolated extension-origin iframe and owns
   inbox/detail navigation, unread rendering, MoySklad route changes, and the
   two WebSocket lifecycles.

### Customer-to-Operator Flow

1. The authenticated customer submits text and/or attachments through the
   existing order-scoped website endpoint.
2. The backend performs the current ownership and attachment checks and
   obtains the live MoySklad order name while resolving access.
3. After attachment objects are stored, one PostgreSQL transaction inserts the
   message and attachment metadata, updates the chat state's latest-message
   pointer and cached order name, increments `operator_unread_count`, and
   inserts one manager email outbox row.
4. After commit, the backend publishes the canonical room message and an
   operator inbox summary event through Redis.
5. Open extension inboxes reorder the conversation and update their global
   badge. An open matching room also merges the canonical message by ID.
6. The email dispatcher sends a notification to the configured manager
   mailbox with a direct MoySklad customer-order link.

### Operator-to-Customer Flow

1. The extension submits text and/or attachments through the existing
   operator order endpoint.
2. The backend authenticates the shared secret and performs current linked-
   order verification.
3. After attachment objects are stored, one PostgreSQL transaction inserts the
   message and attachment metadata, updates the latest-message pointer and
   cached order name, creates the customer's `ORDER_MESSAGE` notification, and
   inserts one customer email outbox row addressed to the order owner.
4. After commit, the backend publishes the room message, the customer's
   absolute notification count, and an operator inbox summary event.
5. The website menu count changes in realtime. The notification list shows the
   order name and preview. The email dispatcher sends the same safe summary to
   the customer's current email address captured in the outbox row.

## Persistence Model

### `order_chat_state`

An additive Alembic revision adds:

- `order_name VARCHAR(255) NULL` — cached MoySklad order name/number;
- `latest_message_id UUID NULL` — the canonical latest message used for inbox
  ordering and summary lookup;
- `operator_unread_count INTEGER NOT NULL DEFAULT 0` with a non-negative check.

Every successful new-message transaction updates `latest_message_id` and the
state timestamp. A customer-message transaction atomically increments the
operator count. `POST .../read` locks the state row and sets that count to zero.
Manager messages do not change operator unread state.

The migration backfills `latest_message_id` from existing canonical history
using PostgreSQL only. Historical conversations start with zero operator
unread messages so deployment does not present old messages as newly unread.
Order names are not fetched from MoySklad inside Alembic. They are filled
lazily with bounded concurrency when an inbox page encounters missing names,
and are refreshed whenever normal live order access already returns a name.

### `order_chat_email_outbox`

The new table contains:

- `id UUID` primary key;
- `message_id UUID NOT NULL UNIQUE` referencing the canonical message;
- `recipient_email VARCHAR(320) NOT NULL`;
- `recipient_kind VARCHAR(16)` constrained to `client` or `manager`;
- `status VARCHAR(16)` constrained to `pending`, `processing`, `sent`, or
  `dead`;
- `attempts INTEGER NOT NULL DEFAULT 0`;
- `available_at`, `locked_at`, `sent_at`, and `created_at` timestamps;
- `last_error VARCHAR(255) NULL`, containing only a safe error category and no
  message body, email response body, credential, or full upstream payload.

The unique message reference encodes the accepted rule that each message has
exactly one email recipient. The outbox stores the recipient captured at
message time, while the email subject/body are derived from canonical data by
the renderer. This keeps the message transaction idempotent and prevents a
later profile/configuration change from silently redirecting a pending job.

The dispatcher claims jobs with PostgreSQL row locking and `SKIP LOCKED`, so
multiple application workers cannot send the same pending row concurrently.
Successful delivery marks the row `sent`. Failures retry with delays of one
minute, five minutes, fifteen minutes, one hour, and then up to six hours,
capped at ten total attempts. Exhausted jobs become `dead` and remain visible
for operational diagnosis and an explicit replay operation in a later scope.

## Operator Inbox API

All paths are relative to `/api_v1` and preserve the existing
`X-Pix-Chat-Secret` REST header. Inbox results include only states with a
non-null latest message.

### `GET /chat/operator/conversations`

Query parameters:

- `before`: optional latest-message UUID cursor;
- `limit`: 1–50, default 50.

Response:

```json
{
  "items": [
    {
      "order_id": "uuid",
      "order_name": "12345",
      "last_message": {
        "id": "uuid",
        "sender_kind": "client",
        "sender_label": "Клиент",
        "message": "Короткий текст",
        "created_at": "2026-08-22T12:00:00Z",
        "attachment_count": 0
      },
      "unread_count": 2
    }
  ],
  "next_before": null,
  "total_unread": 2
}
```

The list is ordered by latest message `(created_at, id)` descending. The
preview is plain text, bounded in length, and never includes object keys or
attachment filenames. If a cached name cannot be refreshed because MoySklad
is temporarily unavailable, the item uses a neutral shortened order-ID label
and remains selectable.

### `POST /chat/operator/orders/{order_id}/read`

The endpoint authenticates the shared secret, requires an existing
conversation, clears its global operator unread count, and returns:

```json
{"order_id":"uuid","unread_count":0,"total_unread":4}
```

It is idempotent. Opening a detail view calls it after the history request
succeeds. It does not mark the customer's website notification as read.

### `WS /chat/operator/inbox/ws`

The shared secret is sent in the first frame using the same five-second
authentication deadline and frame shape as the existing room socket. The
secret is never placed in a URL.

After authentication, events have this shape:

```json
{
  "type": "conversation_updated",
  "item": {"order_id":"uuid", "order_name":"12345", "last_message":{}, "unread_count":1},
  "total_unread": 3
}
```

The event is an optimization, not the source of truth. Initial load, focus,
reconnect, malformed event, or a detected version gap triggers a full REST
reload. Redis publication failure never rolls back the database transaction.

The existing `/chat/operator/ws?room={order_id}` remains unchanged for room
messages. The inbox socket cannot send messages or subscribe to attachment
content.

## Website Experience

The existing notification menu count remains the global entry point. An
`ORDER_MESSAGE` item displays:

> Новое сообщение по заказу №{order_name}

followed by a bounded plain-text preview or `Прикреплены файлы`, if the message
contains no text. Unread styling and current optimistic read handling remain.

Clicking the row serializes the existing read mutation and navigates to:

`/dashboard/orders/{order_id}?openChat=1#order-chat`

The order page passes this intent to the existing chat panel, expands it when
necessary, scrolls/focuses the chat heading, and then removes or ignores the
one-shot query flag. Direct order URLs without the flag keep their current
layout. The backend notification response adds `order_name` and keeps existing
fields for backward compatibility.

## Extension Experience

### Host Lifecycle

The content script remains restricted to `https://online.moysklad.ru/app/*`,
but it keeps one panel host mounted throughout the MoySklad application. A
collapsed launcher is therefore available outside customer-order routes. The
content script still does not read MoySklad cookies, page state, or network
traffic.

The iframe remains mounted while the content script reports route changes with
a narrow `route_context` message. The panel owns a view state of `inbox` or
`conversation`. Opening a MoySklad order directly selects its conversation
automatically when the order has a linked chat. On other routes the panel opens
to the inbox.

Cross-origin navigation uses a second narrow message in the opposite direction:
the panel posts only `{type: "navigate_order", orderId: "<uuid>"}`. The content
script verifies the iframe window, extension origin, exact message shape, and
UUID before assigning the exact customer-order hash. It never accepts an
arbitrary URL from the panel or host page.

### Inbox View

Each row shows:

- cached order name/number;
- sender label and bounded last-message preview;
- attachment indicator when applicable;
- formatted last-message time;
- unread badge when greater than zero.

The panel header shows the summed global unread badge. Rows are ordered by the
server and loaded in pages. Empty, loading, temporary-error, unauthorized, and
reconnecting states are explicit. Only conversations with messages appear.

Selecting a row asks the validated content-script bridge to change the main
page location to the exact supported route:

`https://online.moysklad.ru/app/#customerorder/edit?id={order_id}`

The panel then opens the conversation detail, loads room history, starts the
room socket, and clears the global unread state after successful access. The
Back control closes only the detail lifecycle and returns to the inbox; it does
not navigate MoySklad away from the order. Selecting another row closes the
old room socket, cancels stale REST work, navigates MoySklad, and opens the new
conversation.

The inbox socket remains connected while the panel is open. Collapse state
does not stop inbox updates. The room socket exists only for the selected
conversation. Draft text/files remain scoped to one conversation and are
discarded only after explicit navigation confirmation when non-empty; browser
security still prevents restoring selected `File` objects after reload.

## Email Delivery

### Templates

Manager subject:

`Новое сообщение клиента по заказу №{order_name}`

Customer subject:

`Новое сообщение по заказу №{order_name}`

Both HTML and plain-text bodies contain the sender label, an escaped preview
of at most 300 Unicode characters, attachment count, and one absolute HTTPS
button/link. Empty text uses `Прикреплены файлы`. Newlines are preserved as
text formatting; message markup is never interpreted as HTML.

Manager links target the exact MoySklad customer-order route. Customer links
target the one-shot expanded website chat route. Attachments are never embedded
or linked directly from email because downloads require authenticated,
order-scoped application access.

### Sender Boundary

A dedicated email client replaces direct chat use of the verification helper.
It uses the existing SMTP.BZ API credential, a bounded connect/read timeout,
and a safe result/error model. The dispatcher invokes the blocking HTTP client
outside the async event loop. It never prints provider response bodies,
recipient addresses, message previews, or credentials.

The dispatcher starts from the FastAPI lifespan when chat email delivery is
enabled. It is independent of the existing business scheduler flag. Shutdown
stops claiming new rows and gives the current bounded request a short grace
period. PostgreSQL locking makes the design safe if deployment later adds
multiple backend workers.

## Configuration

`config.py` remains the only environment boundary. Add:

- `ENABLE_ORDER_CHAT_EMAIL_NOTIFICATIONS`, default `false` locally;
- `ORDER_CHAT_MANAGER_EMAIL`, required when email notifications are enabled;
- `PIX_PUBLIC_SITE_URL`, required HTTPS origin in production.

Production sets `ORDER_CHAT_MANAGER_EMAIL=Pixtool22@gmail.com`. The existing
SMTP.BZ token setting remains the credential source for compatibility. No real
token, recipient, or credential-bearing URL is committed to `.env.example`,
logs, tests, bundles, or documentation examples beyond the explicitly
approved non-secret manager mailbox.

The production preflight requires all three email-delivery settings when the
feature is enabled. Local/test environments use an injected fake sender and do
not contact SMTP.BZ.

## Error Handling and Recovery

- Message/notification/outbox persistence is one transaction after attachment
  upload. A database failure triggers the existing MinIO compensation path.
- Redis room, inbox, or notification-count publication is post-commit and best
  effort. Reconnect reloads durable state.
- SMTP.BZ failures affect only the outbox row. Chat REST still returns success
  for the committed message.
- Customer identities already require a validated email. If unexpected legacy
  data still contains an invalid recipient, the message and outbox row remain
  durable, the dispatcher classifies the job as `dead` without contacting the
  provider, and operations receives a safe recipient-data error category. Chat
  sending is not rolled back and the invalid address is never logged.
- Missing manager email or provider credential fails production preflight when
  delivery is enabled.
- A stale `processing` lease is returned to `pending` after a bounded timeout,
  allowing recovery after process termination. Provider ambiguity after a
  timeout can still produce an unavoidable duplicate email; the database
  guarantees one job and at-most-one concurrent attempt, while provider-level
  idempotency is used if SMTP.BZ supports it.
- Inbox order-name hydration failure degrades to a neutral order identifier and
  never hides the conversation or bypasses room authorization.

## Security and Privacy

- Operator inbox REST and WebSocket routes use the existing constant-time
  shared-secret authenticator.
- Possession of the shared secret continues to grant access to all linked Pix
  order chats; this design does not imply individual manager authorization.
- Conversation detail still performs live linked-order verification. Inbox
  summaries come only from canonical states/messages created through those
  checks and reveal no client email, client ID, object key, or MoySklad
  credential.
- Email templates escape all customer/manager text and order names.
- Email previews are capped at 300 characters and contain no attachment names
  or bytes.
- Client order links still require website authentication. Operator links
  require the manager's existing MoySklad session.
- Logs contain outbox/message identifiers, attempt number, status category, and
  safe correlation IDs only. They exclude recipients, bodies, filenames,
  secrets, provider response bodies, and auth query strings.
- The extension manifest gains no new permissions. It still does not request
  tabs, cookies, downloads, webRequest, browsing history, or MoySklad API host
  access.

## Testing Strategy

### Backend

Use test-driven development for:

- message, recipient side effects, and outbox creation in one transaction;
- one email job per message and replay/idempotency behavior;
- customer messages incrementing global operator unread state;
- manager messages leaving operator unread state unchanged;
- idempotent mark-read and total-unread responses;
- conversation ordering, pagination, previews, attachment counts, and empty
  histories being excluded;
- lazy order-name hydration and safe fallback during MoySklad outages;
- inbox shared-secret REST and WebSocket authentication;
- Redis event publication after commit and durable behavior on Redis failure;
- email template escaping, preview truncation, links, and attachment wording;
- dispatcher claim locking, success, retry schedule, stale-lease recovery, and
  terminal dead-letter behavior;
- provider timeout and sanitized logging;
- production configuration validation;
- additive PostgreSQL migration, latest-message backfill, constraints, and
  preservation of immutable chat triggers/data.

Run `scripts/check.ps1`, `alembic history`, migration static/manual review, and
disposable PostgreSQL migration tests. Do not run Alembic against production as
part of automated verification.

### Website

Add coverage for:

- order-name rendering and safe file-only fallback;
- optimistic read behavior followed by order navigation;
- the expanded-chat URL and one-shot expansion/focus behavior;
- backward-compatible notification fields;
- unchanged absolute unread-count reconciliation.

Run the frontend root `npm.cmd run check` after final contract changes.

### Extension

Add unit/component/smoke coverage for:

- a persistent host on MoySklad non-order and order routes;
- inbox loading, pagination, sorting, empty/error/reconnect states;
- shared-secret inbox API and first-frame WebSocket authentication;
- full REST reload after reconnect or invalid events;
- global and per-row unread badges;
- selecting a row changing the exact MoySklad hash route;
- automatic detail selection on a directly opened order;
- mark-read only after successful conversation access;
- Back returning to inbox without changing the MoySklad route;
- closing stale room work when selecting another conversation;
- safe draft handling across navigation;
- unchanged chat history, upload, download, and narrow manifest permissions.

The Playwright extension smoke uses a persistent Chromium context and a
MoySklad-origin fixture. A final manual smoke uses a real signed-in MoySklad
session only after the user installs the new unpacked build.

## Deployment and Migration

1. Build and verify backend, website, and extension artifacts.
2. Review the additive Alembic revision, database URL, current production
   revision, and recovery procedure.
3. Create and validate a fresh PostgreSQL dump before migration.
4. Manually apply only the reviewed new revision with explicit production
   approval.
5. Deploy backend with email delivery initially disabled and verify health,
   existing room chat, inbox REST/WebSocket, and outbox persistence using
   controlled test data.
6. Deploy the website notification changes.
7. Build a versioned extension ZIP, install/reload it, and run inbox/detail
   smoke tests.
8. Configure the manager recipient and public site URL, enable chat email
   delivery, and send one explicitly approved controlled test message in each
   direction.
9. Verify website notification navigation, both email links, global operator
   unread clearing, and retry observability without printing private content.

The old extension remains compatible during rollout because current room
endpoints stay unchanged. The new extension can fall back to explicit retry if
the inbox endpoints are temporarily unavailable.

Rollback disables the email dispatcher first, restores the previous frontend
and extension artifacts, and restores the previous backend image. The additive
columns/table may remain unused; production downgrade is unnecessary and is
not automatic. No old messages, attachments, or website notifications are
deleted.

## Acceptance Criteria

- A manager message creates one customer `ORDER_MESSAGE` notification and one
  customer email job in the same transaction as the canonical message.
- A customer message increments the global operator unread count and creates
  one manager email job in the same transaction as the canonical message.
- The sender never receives an email for their own message.
- A temporary SMTP.BZ failure does not fail chat sending and is retried from
  durable state.
- A website notification names the order and opens the matching expanded chat.
- The extension launcher is available throughout the MoySklad application.
- The inbox lists only conversations with messages, newest first, with last
  preview, time, and unread badge.
- Selecting an inbox item opens the matching MoySklad order and chat.
- Back returns to the inbox without navigating MoySklad away from the order.
- Opening a conversation clears its operator unread count globally.
- Inbox and room realtime reconnects reconstruct state from REST without
  duplicate messages or stale unread counts.
- Email content is escaped, bounded, contains no attachment bytes/names, and
  links to the correct authenticated order page.
- Existing customer/operator room authorization and attachment isolation
  remain unchanged.
- The migration is additive, preserves all existing chat data, and is never
  applied automatically.
- Backend, frontend, extension, migration, and Chrome smoke checks pass before
  deployment.

## References

- Repository architecture: `docs/ARCHITECTURE.md`
- Existing canonical chat design:
  `docs/superpowers/specs/2026-08-10-moysklad-order-chat-design.md`
- Existing Chrome extension design:
  `docs/superpowers/specs/2026-08-21-moysklad-chrome-order-chat-extension-design.md`
- Existing unread notification count design:
  `docs/superpowers/specs/2026-08-11-unread-notification-count-design.md`
