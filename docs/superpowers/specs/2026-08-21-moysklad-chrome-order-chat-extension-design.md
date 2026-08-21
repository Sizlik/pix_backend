# MoySklad Chrome Order Chat Extension Design

**Date:** 2026-08-21

**Status:** Approved

**Repositories:** `pix_backend`, `../pix_frontend_v2`

## Summary

Pix Logistic will replace the operator-facing MoySklad order-comment and
order-file projection with a dedicated Manifest V3 Chrome extension. When an
operator opens a linked customer order in MoySklad, the extension automatically
shows an order-chat panel over the right side of the page. The existing website
chat remains inside the customer's order page.

The extension and website use the same canonical PostgreSQL message history,
the same private MinIO attachment storage, and the same Redis room for realtime
delivery. Operators can send text and attachments from the extension. Customers
can continue to send text and attachments from the website. Neither direction
writes chat content into the MoySklad order description or MoySklad order files.

The first release uses one shared extension secret entered once on each trusted
workstation. It deliberately does not provide individual operator identity,
individual revocation, or per-operator audit.

## Current System

The backend already provides:

- immutable `order_chat_message` and `order_chat_attachment` history;
- a per-order client mapping in `order_chat_state`;
- private attachment storage in MinIO;
- customer REST and WebSocket endpoints under `/api_v1/chat`;
- Redis pub/sub fanout across backend workers;
- website `ORDER_MESSAGE` notifications;
- a website order-chat panel with file upload and download;
- a MoySklad projection worker, webhook receiver, order-description renderer,
  mirrored order files, and projection-specific outbox state.

The new design keeps the first six capabilities, updates the website panel, and
replaces the last capability with an operator API and Chrome extension.

## Goals

- Automatically show the chat when an operator opens a MoySklad customer order.
- Limit chat availability to orders whose counterparty is linked to a Pix user.
- Let operators and customers exchange text and supported attachments.
- Deliver persisted messages to open website and extension clients in realtime.
- Preserve all existing canonical message and attachment history.
- Keep MoySklad order descriptions and order files free of chat projections.
- Avoid exposing MoySklad credentials, cookies, or API tokens to the extension.
- Keep the extension as a separately built package inside `pix_frontend_v2`.

## Non-goals

- Global operator inbox or notifications outside the currently open order.
- Read receipts, typing indicators, reactions, search, edit, or delete.
- Individual operator accounts, names, authorization, or audit.
- Chat for MoySklad orders that are not linked to a registered Pix customer.
- A MoySklad Vendor API widget, public marketplace app, or MoySklad OAuth flow.
- A permanent fallback through the MoySklad order description or order files.
- Automatic database migration, production deployment, secret rotation, or
  webhook deletion by an agent.

## Accepted Product Decisions

- The operator UI is an injected fixed panel, not Chrome's native side panel.
  Chrome's native side panel cannot be opened on navigation without a user
  gesture, so it cannot satisfy automatic opening on every order.
- The panel opens only for
  `https://online.moysklad.ru/app/#customerorder/edit?id=<UUID>`.
- Operators share one secret. They enter it once; it is never compiled into the
  extension bundle.
- The extension source lives at
  `../pix_frontend_v2/moysklad-chat-extension/` as an independent package.
- The existing MoySklad description/file projection is fully replaced after
  cutover. It is not retained as a permanent fallback.
- Messages from the extension display to customers as
  `Менеджер Pix Logistic`.
- Existing limits remain: at most 10 attachments per message, at most 20 MiB
  per attachment, with JPEG, PNG, WebP, PDF, DOC, DOCX, XLS, XLSX, TXT, and ZIP
  accepted after server-side content validation.

## Architecture

### Components

1. **MoySklad route observer**
   - A narrowly scoped content script runs only on
     `https://online.moysklad.ru/app/*`.
   - It parses the hash route, requires the exact `customerorder/edit` route,
     validates `id` as a UUID, and never reads page state, cookies, storage, or
     network traffic.
   - It observes initial load, `hashchange`, and `popstate`. Repeated processing
     of the same order ID is idempotent.
   - It creates and removes a single panel host as the route enters, changes, or
     leaves a supported customer-order page.

2. **Extension panel**
   - A packaged extension HTML page is exposed only to the MoySklad origin as a
     Manifest V3 web-accessible resource and is embedded in an iframe created
     with `chrome.runtime.getURL()`.
   - The panel has extension origin, bundled scripts/styles, and no remotely
     hosted executable code.
   - It owns secret setup, API calls, WebSocket lifecycle, pagination, message
     rendering, file selection, file download, retry state, and the current
     draft.
   - The MoySklad page cannot read the iframe document or the stored secret.

3. **Operator transport routes**
   - New FastAPI routes under `/api_v1/chat/operator` authenticate the shared
     secret and delegate use-case decisions to the manager layer.
   - Operator routes never reuse the customer bearer-token dependency.
   - Customer and operator transports use the same repository, object storage,
     response models, and realtime room after their distinct authorization
     checks pass.

4. **Order-chat manager**
   - The existing order-chat use case gains explicit operator operations:
     resolve a linked order, list messages, create a manager message, and fetch
     an order-scoped attachment.
   - Manager-created messages also create a website `ORDER_MESSAGE`
     notification for the linked customer.

5. **Canonical stores and realtime**
   - PostgreSQL remains the canonical immutable history.
   - MinIO remains the canonical private attachment store.
   - Redis remains required for multi-worker room publication and notification
     count publication, but its failure never rolls back a committed message.

### Panel Placement and Lifecycle

The panel host is fixed to the right edge with a maximum width of 420 px, a
width that does not exceed the viewport, full viewport height, and a z-index
above the MoySklad application. It overlays rather than rewrites or resizes the
MoySklad DOM. A collapse control reduces it to a narrow visible tab.

The panel starts expanded for each newly opened order. A collapse choice lasts
for the current order in the current tab; navigating to a different order opens
the new order's panel expanded. Mobile-specific layout and drag-to-resize are
not part of the first release.

On order change, the panel must cancel in-flight REST work, close the previous
WebSocket, discard the previous order's messages and pagination cursor, then
load the new order. A late response for the old order must be ignored even if
request cancellation loses a race.

### Customer-to-Operator Flow

1. The authenticated customer submits text and/or files on the website.
2. The backend verifies order ownership through the current customer access
   policy and validates every attachment.
3. Attachment objects are written to MinIO, then the message and attachment
   metadata are committed to PostgreSQL.
4. The committed message is published to the order's Redis room.
5. Every open website tab and authenticated extension panel for that room
   merges the message by immutable message ID.
6. There is no outbox event, order-description update, or MoySklad file upload.

### Operator-to-Customer Flow

1. The panel sends text and/or files to the order-scoped operator endpoint.
2. The backend authenticates the shared secret, loads the MoySklad order, maps
   its counterparty to a local Pix user, and rejects unlinked orders.
3. Attachment objects are written to MinIO.
4. The manager message, attachment metadata, and customer `ORDER_MESSAGE`
   notification are committed in one PostgreSQL transaction.
5. After commit, the backend publishes the message to the order room and
   publishes the customer's new absolute notification count.
6. Redis publication failure is logged without bodies, filenames, or secrets;
   the REST response still succeeds because the message is durable.

## API Contract

All routes are relative to `/api_v1`.

### REST

| Method | Path | Result |
| --- | --- | --- |
| `GET` | `/chat/operator/orders/{order_id}/messages?before=&limit=` | Paginated canonical history |
| `POST` | `/chat/operator/orders/{order_id}/messages` | Create a manager text/file message from multipart form data |
| `GET` | `/chat/operator/orders/{order_id}/attachments/{attachment_id}` | Download an attachment only when it belongs to the selected order |

Every operator REST request includes `X-Pix-Chat-Secret`. The server returns:

- `401` for a missing or invalid secret, with one generic error body;
- `404` when the order does not exist, is malformed, is not linked to a local
  Pix user, or the attachment does not belong to that order;
- `422` for an empty message or rejected attachment batch;
- `503` when required chat storage, MoySklad verification, or extension
  configuration is unavailable;
- `201` only after the message is durably committed.

The list and create responses use the existing message shape after removing the
projection-specific `delivery_state` field. The public response does not expose
`client_id`, source/origin internals, object keys, hashes, MoySklad file IDs, or
the shared secret.

### WebSocket

The operator socket is `/api_v1/chat/operator/ws?room={order_id}`. The shared
secret is never a query parameter. After the server accepts the transport, the
panel must send the following frame within five seconds:

```json
{"type":"authenticate","secret":"<shared secret>"}
```

The backend validates the secret and linked-order access before registering the
socket with the room hub. Success yields `{"type":"authenticated"}`. Missing,
late, or invalid authentication closes with `4401`; malformed or inaccessible
rooms close with `4404`. Inbound chat messages over WebSocket remain forbidden;
message creation uses REST so multipart limits and persistence have one path.

The existing customer WebSocket keeps mandatory `auth` and `room` query
parameters and its current ownership checks. Both sockets receive the same
persisted message event. The obsolete `order_chat_delivery` event is removed.

## Authorization and Order Resolution

Possession of the shared secret grants operator access to every linked Pix
order, so order linkage is the only per-room authorization boundary.

For every initial REST operation and WebSocket connection, the operator access
policy:

1. requests the MoySklad customer order by UUID with its agent metadata;
2. extracts the counterparty UUID from `order.agent.meta.href`;
3. finds the local user by `moysklad_counterparty_id`;
4. creates or verifies `order_chat_state(order_id, client_id)` without changing
   an existing order-to-client association;
5. returns a generic not-found result for missing or ambiguous linkage.

If an existing state row points to a different client, access fails closed and
the mismatch is logged without customer details. A MoySklad lookup failure does
not fall back to trusting the URL or a stale client supplied by the extension.

## Persistence and Migration

### Retained Canonical Data

- `order_chat_message` remains append-only.
- `order_chat_attachment` remains append-only.
- `order_chat_state` retains `order_id` and `client_id` as the durable mapping.
- Existing `source=moysklad` manager messages and `origin=moysklad`
  attachments remain visible and downloadable.
- Existing legacy message IDs and external keys remain available for audit and
  historical uniqueness.

### Additive Migration Required Before Cutover

A new Alembic revision, rather than an edit to an already shipped revision,
updates check constraints to allow:

- `order_chat_message.source = 'extension'`;
- `order_chat_attachment.origin = 'extension'`.

The revision preserves all rows and append-only triggers. It is reviewed with
`alembic history` and static/manual migration inspection. It is never applied
automatically by setup, tests, or an agent action.

### Obsolete Projection State

After the extension has operated successfully for an agreed observation
period, a separate explicitly approved cleanup revision may remove:

- `moysklad_order_file`;
- `chat_outbox_event`;
- projection-only columns from `order_chat_state` such as rendered-description
  hashes and generated MoySklad file IDs.

The cleanup revision is destructive metadata cleanup and therefore requires a
database backup, explicit production approval, and a recovery plan. It is not a
prerequisite for extension cutover. Until cleanup, no new projection outbox or
MoySklad file-observation rows are created.

## Backend Configuration

`config.py` remains the only environment boundary. The implementation adds:

- `MOYSKLAD_CHAT_EXTENSION_SECRET`: required secret with no credential-bearing
  default;
- extension/operator enablement within the existing order-chat capability;
- a refactored order-chat settings object that no longer requires a webhook
  secret merely to use PostgreSQL/MinIO chat.

The existing `MOYSKLAD_ORDER_CHAT_WEBHOOK_SECRET` and outbox retry settings are
retired only when their code paths are removed. Environment inventories and
production examples are updated without real values. Missing configuration
fails through `IntegrationNotConfigured` and returns a safe `503`.

The public feature flag and capability response remain backward compatible for
the website during the cutover; renaming them is unrelated to the operator
transport and is excluded from this feature.

## Extension Security Model

### Secret Handling

- The operator enters the shared secret in the panel's first-run setup.
- The extension stores it only in `chrome.storage.local`, never
  `chrome.storage.sync`, and restricts storage access to trusted extension
  contexts.
- The content script does not receive the secret. Network calls originate in
  the extension panel or another trusted extension context.
- The Pix API origin is a non-secret build-time value and is not editable by an
  operator. Request helpers accept route and order identifiers, not arbitrary
  absolute URLs.
- The secret is not compiled into JavaScript, emitted in source maps, appended
  to URLs, written to logs, included in analytics, or rendered back into the
  DOM after entry.
- Backend comparison uses `hmac.compare_digest` or an equivalent constant-time
  comparison.
- Rotation invalidates every installed copy and requires every operator to
  enter the replacement secret.

Chrome documents that local extension storage is not encrypted. This accepted
design therefore protects against the MoySklad page and ordinary remote web
content, but not against a person or malware with access to the operator's OS
account or Chrome profile. Installation is limited to trusted workstations.

### Permissions

The production manifest requests only:

- `storage`;
- a content-script match for `https://online.moysklad.ru/app/*`;
- a host permission for the single configured HTTPS Pix API origin;
- web-accessible panel assets restricted to the MoySklad origin.

The production manifest must not request `<all_urls>`, `cookies`, `tabs`,
`webRequest`, `declarativeNetRequest`, browsing history, clipboard, downloads,
or MoySklad API hosts. File downloads use browser Blob URLs created from the
authenticated backend response.

### Transport and Rate Limits

Production API and WebSocket traffic uses HTTPS/WSS only. NGINX applies an
operator-route limit of 10 REST requests per second per source IP with a burst
of 20, plus a connection-attempt limit of 5 per second with a burst of 10 for
the operator WebSocket. Existing order-chat upload body limits continue to
cover the maximum allowed batch.

Authentication failures log only route, status, and a safe request correlation
identifier. Message bodies, filenames, object keys, secrets, extension storage,
and customer identifiers are excluded from authentication and projection logs.

### Accepted Limitations

- The shared secret cannot prove which operator sent a message.
- One compromised workstation compromises the shared credential.
- One operator cannot be revoked without rotating the credential for everyone.
- The extension has access to every linked Pix order chat.

These limitations are accepted for the first release. Device pairing or
individual operator accounts require a separate design.

## Website Changes

The chat remains within `dashboard/orders/[id]` and continues to support text,
images, files, pagination, authenticated downloads, and reconnect recovery.

The website removes projection-only behavior:

- `delivery_state` from the TypeScript message contract;
- `order_chat_delivery` event handling;
- pending/synced/failed delivery labels tied to MoySklad projection.

A successful REST response means the server durably accepted the message.
Realtime remains best effort; reconnect always reloads history to fill gaps.
The website's owner authorization and order-specific `room` parameter remain
unchanged.

## Error Handling and Recovery

### Panel States

- **Unconfigured:** show secret entry and do not call the backend.
- **Unauthorized:** clear the usable in-memory value, keep the input private,
  and request a replacement secret.
- **Unavailable order:** show `Чат недоступен для этого заказа` without
  revealing whether the order or user linkage is missing.
- **Temporary integration failure:** show a retry control and keep the current
  route context.
- **Loading/empty/history error:** match the website chat's explicit states.
- **Disconnected:** show `Переподключаемся`, reconnect with exponential delay
  capped at 30 seconds, and reload current history after reconnect.

### Drafts and Requests

The panel disables duplicate submission while a request is active. Text and
selected files remain in the form until the backend returns `201`; an error
leaves them available for retry. A full browser reload cannot restore selected
`File` objects and makes no attempt to bypass that browser security boundary.

The UI does not optimistically invent a canonical message ID. It merges the
POST response and subsequent WebSocket event by the server-generated immutable
ID, so either arrival order produces one message.

### Attachment Safety

Both clients perform fast filename/size checks for feedback, but backend
content validation is authoritative. The backend uses generated UUID object
keys, sanitized response headers, allowlisted content types, archive container
validation, and the existing compensation path that deletes uploaded objects
when the database transaction fails.

Messages and filenames render as text. Image previews use authenticated Blob
responses and revoke object URLs on cleanup. The extension does not use
`innerHTML`, execute attachment content, or render remote HTML.

## Removal of the MoySklad Projection

At cutover, customer message creation stops adding `sync_order` outbox events.
The projection worker no longer updates order descriptions or uploads mirror
and history files. The webhook receiver no longer imports description edits or
prefixed MoySklad files as chat messages. The webhook registration script and
projection-specific dependencies are removed or replaced by an explicit
de-registration runbook.

The production webhook itself is removed manually only after a successful
extension smoke test. Until it is removed, the deployed backend rejects or
ignores the obsolete webhook path without creating messages, so the old and new
mechanisms never process the same operator action concurrently.

Existing chat text that was rendered into a MoySklad description is not
automatically erased: the extension stops managing that field, and clearing
historical rendered comments would be a separate production data mutation.
Existing mirrored MoySklad files are likewise not deleted automatically.

## Testing Strategy

### Backend

Add unit and route tests for:

- missing, incorrect, and correct shared secrets;
- constant-time guard behavior at the dependency boundary;
- WebSocket authentication success, invalid input, five-second timeout, and
  no room registration before authorization;
- malformed, missing, unlinked, correctly linked, and linkage-conflict orders;
- manager text, file-only, and mixed messages;
- attachment count, size, extension, signature, and archive validation;
- order-scoped attachment download and cross-order rejection;
- one transaction containing manager message metadata and `ORDER_MESSAGE`;
- post-commit chat and notification publication;
- durable success when Redis publication fails;
- MinIO compensation when persistence fails;
- pagination and merge-compatible response shape;
- unchanged customer ownership checks;
- removal of projection outbox creation and webhook imports;
- additive migration constraint and append-only trigger preservation.

Run `scripts/check.ps1` after the final backend edit. Also run `alembic history`
and manually review every migration statement. Do not run `alembic upgrade` or
`downgrade` as part of development verification.

### Website

Update and add Vitest coverage for:

- the message type without `delivery_state`;
- removal of projection delivery events and labels;
- persisted-message merge and reconnect reconciliation;
- existing upload validation and authenticated downloads;
- continued inclusion of the order-specific WebSocket room.

Run `npm.cmd run check` after the final cross-repository contract edit.

### Extension

The extension package provides lint, typecheck, unit-test, build, and manifest
permission-guard commands. Unit tests cover:

- exact MoySklad hash parsing and UUID validation;
- initial load, duplicate route events, order changes, and leaving the route;
- stale-response rejection after order changes;
- first-run secret entry, invalid-secret recovery, and rotation;
- API URL construction that cannot target an arbitrary origin;
- WebSocket authentication, reconnection, and history reconciliation;
- pagination and duplicate message merging;
- file validation and form preservation after failures;
- safe message and filename rendering;
- the production manifest's narrow permission set.

A Playwright Chromium persistent-context smoke loads the unpacked production
build and intercepts a document at the real MoySklad origin with a local fixture.
It verifies automatic injection only on customer-order routes, expansion,
collapse, order changes, teardown, and isolation from host-page styles. A manual
smoke on a signed-in real MoySklad order remains required because CI does not
receive production MoySklad credentials.

The root frontend check invokes the extension check so contract drift cannot
pass while the main website succeeds.

## Production Cutover

1. Build and verify backend, website, and extension artifacts.
2. Generate a random production shared secret outside source control and add it
   to the approved secret-management/deployment path.
3. Install the packaged extension on operator workstations and enter the secret.
   Before backend cutover it shows a temporary-unavailable state.
4. Back up PostgreSQL and manually apply only the reviewed additive migration.
5. Deploy the backend version that enables operator routes and stops producing
   or consuming MoySklad chat projections.
6. Test one linked order in both directions, including one image and one
   non-image attachment, website notification, reconnect, and download.
7. Manually remove the old MoySklad webhook using an explicit operations
   runbook.
8. Observe logs, error rates, message history, and MinIO objects before
   considering projection metadata cleanup.
9. Schedule the separate destructive cleanup migration only with explicit
   approval, backup confirmation, and a recovery plan.

Rollback before cleanup restores the previous backend artifact and webhook
configuration. Rollback after cleanup requires the cleanup migration's
documented recovery path. The extension can remain installed but must fail
closed when the operator API is unavailable.

## Acceptance Criteria

- Opening a linked MoySklad customer-order URL automatically displays the
  expanded extension panel for that UUID.
- Opening a non-customer-order page removes the panel.
- Opening an unlinked customer order displays the unavailable state and no
  history.
- A customer text/file message appears in an already open extension panel
  without refreshing MoySklad.
- An operator text/file message appears on an already open website order chat
  and creates an `ORDER_MESSAGE` notification.
- Refreshing either client reconstructs the same immutable history from REST.
- Attachment downloads succeed only for an authorized room and never reveal
  object-storage keys.
- Invalid extension authentication cannot list, send, download, or subscribe.
- No new message updates the MoySklad order description or order files.
- No secret appears in source, bundles, source maps, URLs, logs, or test output.
- Backend checks, frontend checks, extension checks/build, and the extension
  smoke pass after the final edits.

## References

- Repository architecture: `docs/ARCHITECTURE.md`
- Existing chat design:
  `docs/superpowers/specs/2026-08-10-moysklad-order-chat-design.md`
- Chrome content-script isolation:
  <https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts>
- Chrome cross-origin extension requests:
  <https://developer.chrome.com/docs/extensions/develop/concepts/network-requests>
- Chrome extension storage warning:
  <https://developer.chrome.com/docs/extensions/reference/api/storage>
- Chrome Manifest V3 web-accessible resources:
  <https://developer.chrome.com/docs/extensions/reference/manifest/web-accessible-resources>
