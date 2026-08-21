# MoySklad Chrome order-chat extension cutover

This is a manual production runbook. It does not authorize an agent, CI job, or
setup script to install secrets, run migrations, deploy artifacts, contact a
live MoySklad account, or remove webhooks. Name one operator and one approver,
record the backend/frontend artifact IDs, and keep the rollback artifact
available throughout the change window.

Never paste database URLs with credentials, the shared extension secret,
MoySklad credentials, webhook target URLs, message bodies, filenames, or
attachment bytes into tickets, chat, screenshots, shell history, or logs.

## 1. Preconditions and recovery

- [ ] Confirm a current PostgreSQL backup, record its opaque backup ID, and
  confirm that a restore was tested in an isolated environment.
- [ ] Confirm the production MinIO volume is healthy, persistent, included in
  the same recovery point as PostgreSQL, and has a tested restore procedure.
- [ ] Record current backend/frontend artifact IDs and feature-flag state.
- [ ] Confirm the previous backend artifact and its existing legacy webhook
  configuration can be restored without printing the webhook URL or secret.
- [ ] Confirm the existing legacy MoySklad order-chat webhook is still present;
  record only its opaque MoySklad ID and enabled/disabled state.
- [ ] Keep `ENABLE_MOYSKLAD_ORDER_CHAT=false` until the database and service
  preflight below are complete.

Do not continue if either PostgreSQL or MinIO cannot be restored. They form one
canonical chat retention set.

## 2. Create and distribute the shared secret

- [ ] Use the approved secret manager's cryptographic generator to create at
  least 32 random bytes outside source control and shell history.
- [ ] Install the generated value in the approved backend secret store as
  `MOYSKLAD_CHAT_EXTENSION_SECRET` without displaying it in deployment output.
- [ ] Distribute the same value to named trusted operator workstations through
  the approved private credential channel. Do not send it in ordinary chat or
  email.
- [ ] Confirm production preflight can see the setting by success/failure only:

  ```bash
  docker compose exec -T backend python scripts/check_production_config.py --require-order-chat
  ```

`chrome.storage.local` is not encrypted. A copied or compromised Chrome profile
is a credential incident and requires backend rotation plus re-entry on every
trusted workstation.

## 3. Verify and build the extension artifact

From the adjacent `pix_frontend_v2` checkout, first run the deterministic local
check with no production build variable set:

```powershell
npm.cmd ci
npm.cmd run check:extension
```

Then build the production artifact with only the public API base:

```powershell
$env:PIX_EXTENSION_BACKEND_URL = "https://pixlogistic.com/api_v1"
npm.cmd run build --workspace pix-moysklad-chat-extension
Remove-Item Env:PIX_EXTENSION_BACKEND_URL
```

- [ ] Review `moysklad-chat-extension/dist/manifest.json`: host permission is
  only `https://pixlogistic.com/*`; content injection is only
  `https://online.moysklad.ru/app/*`; forbidden broad permissions are absent.
- [ ] Record an artifact checksum and distribute the identical unpacked or
  packaged artifact through the approved internal channel.
- [ ] Install it on each trusted profile, open one linked customer order, enter
  the shared secret once, and confirm the secret never appears in the address.

Do not put `MOYSKLAD_CHAT_EXTENSION_SECRET` in
`PIX_EXTENSION_BACKEND_URL`, any build argument, Manifest, package, or source
file.

## 4. Inspect and apply only the extension-source revision

Inspect the active database identity without rendering a credential-bearing
URL. This prints only driver, host, port, and database name:

```bash
docker compose exec -T backend python -c "from config import Settings; s=Settings(); print(f'{s.postgres_driver}://{s.postgres_host}:{s.db_port}/{s.postgres_db}')"
docker compose exec -T backend alembic current
docker compose exec -T backend alembic show e3b7c9d1a204
```

- [ ] Two people confirm this is the intended production database.
- [ ] Manually review
  `alembic/versions/e3b7c9d1a204_allow_extension_chat_source.py` from the exact
  backend artifact.
- [ ] Confirm `alembic current` is exactly `d4e5f6a7b8c9`. If it is anything
  else, stop. In particular, do not let Alembic implicitly apply the destructive
  predecessor `d4e5f6a7b8c9`; that migration has its own runbook.
- [ ] Obtain explicit migration approval for this database and revision.
- [ ] Only then apply the exact revision, never `head`:

  ```bash
  docker compose exec -T backend alembic upgrade e3b7c9d1a204
  docker compose exec -T backend alembic current
  ```

Expected current revision: `e3b7c9d1a204`. Do not run its downgrade during an
incident after extension messages have been created.

## 5. Deploy and enable the operator transport

- [ ] Deploy the reviewed backend/NGINX artifact while the chat flag remains
  off; record its immutable artifact ID.
- [ ] Confirm the operator REST location has the 205 MiB cap and 10 r/s zone,
  and the exact operator WebSocket location has upgrade headers and the 5 r/s
  zone.
- [ ] Run the sanitized configuration preflight again.
- [ ] Set `ENABLE_MOYSKLAD_ORDER_CHAT=true` in the approved environment store
  and restart only the required backend service.
- [ ] Confirm liveness and the public capability without printing settings:

  ```powershell
  Invoke-RestMethod https://pixlogistic.com/api_v1/health
  Invoke-RestMethod https://pixlogistic.com/api_v1/capabilities
  ```

Expected: health succeeds and capability contains
`"moysklad_order_chat": true`.

## 6. Linked-order acceptance smoke

Use a dedicated linked staging order and non-sensitive fixture content.

- [ ] Website client sends text plus one valid image and one valid PDF;
  operator panel receives one copy of each message without a refresh.
- [ ] Operator sends text plus one valid image and one valid PDF; website gets
  one canonical manager message and one `ORDER_MESSAGE` notification.
- [ ] Both sides download the image and PDF and verify the expected safe fixture
  bytes and filenames.
- [ ] Load older history and confirm chronological order with no duplicate IDs.
- [ ] Disconnect/reconnect the operator network and confirm history plus
  realtime recover without a duplicate.
- [ ] Open a second order and confirm a fresh expanded panel and isolated room.
- [ ] Open a non-order MoySklad page and confirm the injected panel is removed.
- [ ] Confirm an unlinked order is unavailable and no cross-order attachment can
  be downloaded.

Do not use real customer documents for this smoke.

## 7. Retire the legacy webhook and projection

Only after all acceptance checks pass:

- [ ] List active MoySklad webhooks using the approved admin UI or secret-aware
  operator tooling. Do not print or copy target URLs; compare only the captured
  opaque legacy webhook ID.
- [ ] Obtain separate explicit approval to remove that one legacy order-chat
  webhook. Do not delete other webhooks.
- [ ] Remove it and verify by ID that it is absent. The old registration script
  and backend order-chat webhook route no longer exist in this artifact.
- [ ] Send one additional website and operator fixture message. Confirm no new
  customer-order `description` text, reply marker, `[КЛИЕНТ]` file, mirror file,
  or history file appears in MoySklad.
- [ ] Confirm PostgreSQL/MinIO history, website notification and both WebSocket
  transports still work.

Historical comments and files already rendered in MoySklad are not erased by
this cutover. Retained projection-only database tables are also not dropped.
Dropping obsolete tables is a separate destructive operation, requires its own
backup/recovery plan and approval, and is explicitly excluded from this
runbook.

## 8. Rollback

If any acceptance condition fails:

1. Stop extension use and set `ENABLE_MOYSKLAD_ORDER_CHAT=false`.
2. Roll back the backend/NGINX artifact to the captured previous artifact.
3. If the legacy webhook was already removed, restore its approved previous
   registration through the private secret-aware process before relying on the
   old backend. Never reconstruct or paste its credential-bearing URL in logs.
4. Confirm the previous site's health and legacy flow using safe fixtures.
5. Preserve PostgreSQL and MinIO evidence. Do not delete messages, objects,
   volumes, or tables, and do not downgrade `e3b7c9d1a204` during incident
   response.
6. Remove or disable the extension artifact on operator profiles until the
   incident is reviewed.

Application rollback precedes any later cleanup. If data integrity is in
question, stop writes and execute the validated PostgreSQL/MinIO recovery plan
under separate destructive-action approval.
