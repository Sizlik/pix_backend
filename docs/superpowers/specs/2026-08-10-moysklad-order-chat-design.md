# MoySklad Order Chat Design

## Summary

Pix Logistic will move order-specific manager replies from Telegram into the
standard `description` ("Комментарий") field of each MoySklad customer order.
The site remains the client-facing chat. Telegram remains a notification
channel in both directions, while order replies sent from Telegram are no
longer accepted.

This design does not use a MoySklad Vendor API widget or private solution. It
uses the existing JSON API access, a customer-order update webhook, the
standard order comment, and the standard order file collection.

PostgreSQL is the canonical, immutable message history. MinIO stores canonical
attachment bytes. MoySklad holds a rendered recent transcript, a manager reply
area, chat attachment copies, and a generated full-history text file when the
transcript no longer fits in the comment.

## Goals

- A client sends text, photos, or files from the chat on a specific site order.
- The manager sees that conversation in the standard comment of the matching
  MoySklad customer order.
- The manager writes beneath a reply marker in that comment and saves the
  order; the reply appears on the client's order page.
- Client and manager replies are delivered to an open site chat in real time.
- Complete message history is immutable and survives retries, reconnects, and
  edits to the rendered MoySklad comment.
- Telegram continues to notify the support chat about client messages and the
  linked client account about manager messages.
- The existing general support chat continues to use its current Telegram
  workflow.
- Each message can contain up to ten allowed attachments of at most 20 MiB
  each.

## Non-goals

- A MoySklad embedded widget or private Vendor API solution.
- Moving the general support chat into MoySklad.
- Replying to an order chat from Telegram.
- Editing or deleting sent messages or attachments.
- Audio/video calls, typing indicators, reactions, read receipts, or message
  search.
- Executing database migrations, registering a production webhook, deleting
  data, or removing Docker volumes automatically.

## Constraints and Product Decisions

- The MoySklad order comment is reserved exclusively for the chat integration.
  Staff must not use it for operational notes.
- Site replies from MoySklad are displayed as `Менеджер Pix Logistic`; the
  MoySklad employee's identity is not exposed to the client.
- The manager may need to refresh an already-open MoySklad order card to see a
  newly rendered client message. JSON API access cannot force the standard
  MoySklad UI to repaint.
- The site receives a manager reply as soon as MoySklad delivers the webhook
  and backend processing succeeds.
- Attachments are allowed for JPEG, PNG, WebP, PDF, DOC, DOCX, XLS, XLSX, TXT,
  and ZIP. Executable content is rejected.
- Manager files intended for the client must have a `[КЛИЕНТ]` filename prefix.
  Other order files remain internal and are never exposed as chat attachments.

## Architecture

### Canonical data

PostgreSQL is the only canonical message history. Existing `Message` rows are
preserved. The chat data model is extended so that a message has an explicit
sender kind (`client` or `manager`), source (`site`, `moysklad`, or legacy),
order identifier, optional text, and delivery state. A file-only message is
valid.

New persistence concepts are:

- `ChatAttachment`: immutable attachment metadata and the MinIO object key,
  linked to one message. It includes original filename, detected MIME type,
  byte size, SHA-256 digest, origin, and optional MoySklad file ID.
- `OrderChatSync`: per-order synchronization state, including initialization,
  the hash of the last backend-rendered comment, and the current history-file
  version.
- `MoySkladChatFile`: every observed MoySklad file ID and its classification:
  baseline/internal, client copy, imported manager attachment, or generated
  system file. This prevents old files and retries from becoming messages.
- `OutboxEvent`: durable, idempotent work for MoySklad comment/file delivery,
  Telegram notification, and retryable real-time publication.

The existing message schema is migrated rather than replaced. Legacy order
messages whose room ID is a MoySklad order UUID are mapped into the new sender
model. Legacy replies from the technical bot user display as manager messages.

### Attachment storage

MinIO runs as a separate Docker service with a named persistent volume. Its
bucket is private. PostgreSQL stores no file bytes. Object keys are generated
UUID paths and do not reuse user-controlled filenames.

Downloads require an authenticated backend request that verifies order access.
The backend may redirect to a short-lived signed MinIO URL after authorization.
Images use safe inline responses for previews. Other allowed types use
`Content-Disposition: attachment`.

MinIO is the canonical attachment store even though chat files are also copied
to the MoySklad order. This keeps the client experience independent from
MoySklad's temporary download URLs and lets access control remain in Pix
Logistic.

### MoySklad representation

The backend owns the entire customer-order `description` value. It renders a
transcript of at most 4,096 characters, including a fixed manager reply marker
and reserved reply space. A representative layout is:

```text
ПЕРЕПИСКА С КЛИЕНТОМ — НЕ РЕДАКТИРОВАТЬ

[10.08.2026 14:20] Клиент:
Когда поступит заказ?
Файлы: photo.jpg

[10.08.2026 14:24] Менеджер Pix Logistic:
Ожидаем поступление завтра.

------------------------------
ОТВЕТ МЕНЕДЖЕРА:
Напишите ответ ниже этой строки и сохраните заказ.
```

Only text entered after `ОТВЕТ МЕНЕДЖЕРА:` and after the instructional line is
eligible to become a manager message. Changes elsewhere are ignored and then
replaced by the canonical rendering. The renderer reserves space for the reply
area and includes the newest complete messages that fit within MoySklad's
comment limit; it never cuts a message in the middle.

When the complete transcript no longer fits, the order files contain a system
file named `[PIX] История переписки.txt`. The backend replaces that system file
with the latest full UTF-8 transcript after every subsequent message. The file
is excluded from manager-attachment discovery and is never presented to the
client as a new message.

Client attachment copies use a deterministic prefix containing the message ID,
for example `[ЧАТ-КЛИЕНТ][<message-id>] photo.jpg`. That lets webhook processing
recognize its own uploads without echoing them back to the client.

### Real-time delivery

REST owns message creation and file upload. WebSockets are used for receiving
chat events and connection recovery, not for transporting large file bodies.
The site submits a multipart request to an order-scoped message endpoint.

The connection registry permits multiple sockets per order and per user.
Redis Pub/Sub distributes committed message IDs between backend processes. A
worker that owns an interested socket loads the authorized message DTO and
sends it to that socket. Reconnect always performs a REST history fetch, so a
missed Pub/Sub event cannot lose a message.

## Data Flows

### Client to manager

1. The authenticated client submits optional text and zero to ten files to the
   order-scoped message endpoint. At least text or one file is required.
2. The backend verifies that the MoySklad order belongs to the current user's
   counterparty.
3. It validates filename, extension, detected MIME type, and the 20 MiB per-file
   limit while streaming files to MinIO.
4. One database transaction creates the message, attachment rows, and outbox
   work. A database failure removes newly written unreferenced objects or leaves
   them for a bounded orphan cleanup job.
5. Redis publishes the committed message so all open client tabs update.
6. The outbox worker renders the order comment and copies attachments into the
   MoySklad order file collection.
7. A separate outbox effect notifies the configured Telegram support chat with
   the order link, client information, text summary, and attachment names.
8. MoySklad or Telegram failure does not remove the saved message. MoySklad
   delivery is shown as pending/failed on the site and retries automatically.

### Manager to client

1. The manager enters text beneath `ОТВЕТ МЕНЕДЖЕРА:` and optionally attaches
   one or more order files whose names begin with `[КЛИЕНТ]`, then saves the
   order. A prefixed file may also be sent without text.
2. MoySklad sends a customer-order update webhook. The public handler validates
   its secret, validates the event shape, records an idempotency key, queues the
   order, and responds promptly.
3. A worker takes a PostgreSQL per-order lock and fetches the current order and
   file collection from MoySklad. It never trusts message content supplied in
   the webhook body.
4. The worker extracts only the reply area and finds new, unclassified
   `[КЛИЕНТ]` files. Existing baseline files, backend-created client copies, and
   `[PIX]` system files are ignored.
5. Manager files pass the same type, MIME, size, and count validation as client
   files. The prefix is stripped from the filename shown on the site.
6. The text and files observed together become one immutable manager message.
   If webhook ordering exposes them separately, a valid file-only message is
   created rather than holding the file indefinitely.
7. After PostgreSQL and MinIO persistence succeeds, the backend clears the reply
   area by rebuilding the canonical comment, classifies imported file IDs, and
   records the processed input fingerprint.
8. Redis publishes the new message. The site displays it as
   `Менеджер Pix Logistic`, creates the existing site notification, and sends
   the linked client's existing Telegram notification.

### Initialization and legacy data

Synchronization is lazy per order: the first new chat action or a dedicated
non-destructive initialization command creates its `OrderChatSync` state.

- Existing database messages are rendered into the history.
- Every file already present on the MoySklad order is recorded as baseline and
  cannot become a client-visible chat attachment.
- If the existing order comment is non-empty and does not contain the chat
  marker, it is preserved as an internal MoySklad file named
  `[PIX] Комментарий до подключения чата.txt` before the backend replaces the
  comment. This backup is not copied to MinIO and is not client-visible.
- Initialization is idempotent and never overwrites an unbacked-up legacy
  comment.

## API and Contract Changes

The contract provides:

- `POST /api_v1/chat/orders/{order_id}/messages`, an authenticated multipart
  endpoint with optional `message` text and repeated `files` parts. It returns
  the committed message DTO.
- `GET /api_v1/chat/orders/{order_id}/messages`, an authenticated cursor-based
  history endpoint. It accepts `before` and `limit` (default 50, maximum 100)
  and returns sender, timestamps, text, attachments, and MoySklad delivery
  status.
- `GET /api_v1/chat/attachments/{attachment_id}`, an authenticated download
  endpoint that rechecks order ownership before returning or redirecting.
- The existing `/api_v1/chat/ws` endpoint with its current token and room query
  semantics, upgraded for multiple connections and cross-process publication.
- `POST /api_v1/integration/webhooks/order-chat/{secret}`, the MoySklad
  customer-order update webhook. Its reverse-proxy location suppresses access
  logging and its handler uses a constant-time secret comparison.

Existing order message reads remain compatible during frontend migration, but
must gain ownership checks. The frontend derives its WebSocket origin from the
configured backend base instead of the currently hard-coded production host.

The legacy technical-bot send endpoint remains available for the general
support room. When its target is a MoySklad order, it rejects the reply while
the new order-chat feature is enabled. This prevents Telegram and MoySklad from
being simultaneous manager-authoring channels.

## Idempotency and Concurrency

- Webhook event IDs are the primary idempotency keys when supplied. A stable
  hash of account/entity/action/timestamp is the fallback.
- A per-order database lock serializes comment parsing, file discovery, message
  creation, and comment reconstruction.
- The last backend-rendered comment hash distinguishes a self-generated webhook
  from manager input.
- A processed reply fingerprint prevents retries from creating a second
  message. Clearing and then re-entering identical text later is still a valid
  new reply because it belongs to a later order revision.
- MoySklad file IDs are unique records. Re-upload or webhook replay cannot
  import one file twice.
- Outbox effects have stable deduplication keys based on message ID and effect
  kind.

## Failure Handling

- If MinIO is unavailable during a site upload, the request fails without
  creating a message. Partial objects are deleted or collected as orphans.
- If MinIO is unavailable while importing a manager file, the reply area is not
  cleared and the event retries. No attachment is announced before its bytes
  are durable.
- MoySklad delivery retries use bounded exponential backoff with jitter. After
  the retry threshold, the message remains visible on the site with a failed
  warehouse-delivery state and an operational log entry.
- Telegram notification retries are independent and never ask the client to
  resend a successfully persisted message.
- Redis failure can delay live display but cannot lose history; reconnect and
  periodic history refresh recover it.
- A missing or malformed reply marker never sends arbitrary comment text to the
  client. The backend restores the canonical comment and alerts the support
  Telegram chat.
- More than ten new `[КЛИЕНТ]` files, an oversized file, or a disallowed file
  is not partially delivered. The manager reply remains recoverable, and the
  support Telegram chat receives a concise correction instruction.
- If a MoySklad order does not exist or is not associated with a Pix Logistic
  user, the webhook is acknowledged idempotently and no client data is created.

## Security

- Every site history, send, WebSocket-room, and attachment request verifies the
  order's MoySklad agent against the current user's counterparty ID.
- The MoySklad webhook uses a high-entropy secret stored only in
  `config.Settings`. The dedicated reverse-proxy location redacts or disables
  access logging so the secret URL is not persisted.
- Webhook input identifies an order only. The backend re-fetches authoritative
  content with its configured MoySklad credentials.
- MinIO uses a private bucket and distinct non-default production credentials.
  Neither MinIO credentials nor MoySklad credentials reach browser code.
- User filenames are normalized for display only and are never used as paths.
- MIME detection, extension allowlisting, byte limits, attachment count limits,
  and `Content-Disposition` prevent executable or active document delivery.
- Image preview is limited to JPEG, PNG, and WebP. SVG and HTML are not allowed.
- Logs contain IDs and status codes, not message bodies, attachment contents,
  webhook secrets, tokens, passwords, or signed download URLs.

## Configuration and Deployment

All new environment handling lives in `config.py`. The settings are:

- `ENABLE_MOYSKLAD_ORDER_CHAT=false` by default;
- `MOYSKLAD_ORDER_CHAT_WEBHOOK_SECRET`, required when the feature is enabled;
- `MINIO_ENDPOINT`, required when the feature is enabled;
- `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`, required secrets when enabled;
- `MINIO_BUCKET=pix-order-chat`;
- `MINIO_SECURE=false` locally and explicitly set for production;
- `CHAT_ATTACHMENT_MAX_BYTES=20971520`;
- `CHAT_ATTACHMENT_MAX_COUNT=10`;
- `CHAT_OUTBOX_MAX_ATTEMPTS=8`;
- `CHAT_OUTBOX_BASE_DELAY_SECONDS=5`.

The local default keeps the integration disabled so imports, setup, tests, and
ordinary local startup do not contact MoySklad or Telegram. MinIO is added to
Compose with a health check and named persistent volume. The volume must be
included in production backups.

Rollout order:

1. Review the Alembic migration without applying it automatically.
2. Deploy the database-compatible application and MinIO service with the
   feature disabled.
3. Create the private bucket and verify read/write health without exposing it
   publicly.
4. Configure the webhook secret and register the customer-order update webhook
   using a documented, explicit command after inspecting the target account and
   callback URL.
5. Initialize and smoke-test one test order in both directions, including one
   image and one document.
6. Enable the feature for production order chat.
7. Monitor outbox failures, webhook replays, MinIO capacity, and Telegram
   failures.

Disabling the feature stops MoySklad order-chat processing without deleting
messages or objects. The general support chat remains available.

## Frontend Behavior

Only the order page chat changes. The floating general support chat remains as
it is.

- Text and selected files are submitted together.
- The composer shows selected filenames, sizes, removal controls, and the
  ten-file/20 MiB constraints before submission.
- JPEG, PNG, and WebP appear as image previews. Other allowed files appear as
  download cards with filename and size.
- The UI supports text-only and file-only messages.
- Messages render `Клиент` or `Менеджер Pix Logistic` consistently rather than
  inferring direction from `first_name == "bot"`.
- Pending/failed MoySklad synchronization is visible without implying that the
  local message was lost.
- Reconnect reloads paginated history and deduplicates by message ID.

## Verification

Backend unit tests cover:

- bounded comment rendering without partial messages;
- reply-marker parsing and damage recovery;
- initial legacy-comment backup and existing-file baseline;
- manager filename-prefix classification;
- MIME, extension, size, and count validation;
- file-only messages;
- webhook replay, self-generated webhooks, and identical later replies;
- per-order concurrency and outbox deduplication;
- MoySklad, MinIO, Redis, and Telegram failure semantics;
- client/order ownership and attachment authorization;
- rejection of order replies through the legacy Telegram path while preserving
  the general support path.

Integration/API tests use fakes or local services and cover:

- multipart message creation and cleanup after failure;
- manager reply plus attachments flowing from a webhook to REST history;
- multiple WebSocket connections receiving one event without disconnecting one
  another;
- Redis publication across application instances;
- short-lived authorized downloads;
- no external HTTP during import, setup, or disabled-feature startup.

Frontend tests cover attachment selection, previews, downloads, sender labels,
delivery states, reconnect deduplication, and file-only messages. A browser
smoke test exercises one text message and attachments in both directions on a
test order.

After the final implementation edit, verification includes:

- backend `powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1`;
- a fresh-process `import main` and `GET /api_v1/health`;
- `alembic history` plus manual migration review, without running migrations;
- frontend `npm.cmd run check` and its browser tests;
- `git diff --check` and a secret/configuration audit.

## Documentation Sources

- [MoySklad JSON API 1.2](https://dev.moysklad.ru/doc/api/remap/1.2/)
  documents customer-order comments, files, temporary download links,
  additional fields, authentication, and webhook entities.
- [MoySklad Vendor API](https://dev.moysklad.ru/doc/api/vendor/1.0/)
  documents private embedded solutions; this design intentionally does not use
  them.
