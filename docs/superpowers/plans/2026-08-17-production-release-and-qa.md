# Production Release And QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure the missing MoySklad workflow/template, release the verified backend/frontend and NGINX fixes, prove the corrected production flows, and remove only the authorized QA records.

**Architecture:** Production changes are staged behind immutable Docker tags and timestamped backups. MoySklad configuration is repaired before exercising the fixed flow; backend and frontend containers are replaced without database migrations, NGINX is validated before reload, and rollback artifacts remain available throughout the observation period.

**Tech Stack:** SSH, Docker Engine/Compose, PostgreSQL, NGINX, Redis, Chrome, MoySklad, FastAPI, Next.js.

## Global Constraints

- Do not stop, delete, reconfigure, or retire the old server.
- Do not stop the old-server Telegram bridge until direct Telegram access from the new host is independently proven.
- Do not run Alembic, delete Docker volumes, prune images, replace `.env`, or recreate PostgreSQL/Redis/MinIO storage.
- Never print or copy secrets into terminal output, commits, plan files, browser notes, or chat responses.
- Back up the new-server database, `.env`, active NGINX file, Compose file, and current image IDs before mutation.
- Delete only QA records positively matched by ID and QA markers after all tests pass.
- A failed health check triggers rollback; it does not trigger cleanup or deletion.

---

### Task 1: Pre-release production inventory and backups

**Files:**
- Create remotely: `/root/pix_release_backups/${PIX_RELEASE_TS}/`, where `PIX_RELEASE_TS=$(date -u +%Y%m%dT%H%M%SZ)` is set once for the release.
- Copy remotely: active `.env`, Compose file, active NGINX virtual host, PostgreSQL custom dump, image inventory.

**Interfaces:**
- Consumes: current production deployment on `158.255.5.86` and existing SSH authorization.
- Produces: root-only rollback directory and exact current service/image inventory.

- [ ] **Step 1: Re-discover active paths without displaying secrets**

Use Docker Compose labels to print only the project working directory and config-file path, then inspect container names, image IDs, health, restart counts, and host service status. Do not run `cat`, `env`, `docker inspect .Config.Env`, or any command that renders `.env` values.

Required evidence:

```text
backend container and image ID
frontend container and image ID
database container and image ID
MinIO container and health
Compose working directory and config filename
active NGINX virtual-host filename
Docker, NGINX, Redis service state
free disk, RAM, and swap
```

- [ ] **Step 2: Create a root-only rollback directory**

On the new server run the equivalent of:

```bash
umask 077
PIX_RELEASE_BACKUP=/root/pix_release_backups/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$PIX_RELEASE_BACKUP"
chmod 700 "$PIX_RELEASE_BACKUP"
```

Resolve and verify the printed absolute path before copying any file into it.

- [ ] **Step 3: Back up configuration without rendering it**

Copy the discovered `.env`, Compose file, and active NGINX file with preserved mode into the rollback directory. Record only filenames, byte sizes, modes, and SHA-256 hashes. Save `docker ps --no-trunc` and the image-ID mapping as non-secret text.

- [ ] **Step 4: Create and validate a PostgreSQL logical backup**

Run `pg_dump` inside the existing database container using its environment-provided user/database, write custom format to `/tmp/pix-pre-release.dump`, copy it to the rollback directory, remove only the temporary container copy, and validate the backup with `pg_restore --list`. Do not restart or lock the database.

- [ ] **Step 5: Tag current application images for rollback**

Apply timestamped rollback tags to the exact current backend and frontend image IDs:

```text
backend:rollback-${PIX_RELEASE_TS}
frontend_v2:rollback-${PIX_RELEASE_TS}
```

Verify both tags resolve to the original IDs before any new build.

### Task 2: Repair MoySklad account configuration

**Files:**
- No repository files.
- Modify in authenticated MoySklad: customer-order state list and embedded print templates.

**Interfaces:**
- Produces: exact state `Изменен клиентом` and at least one embedded customer-order template visible to the existing metadata endpoint.

- [ ] **Step 1: Verify the current account and absence before mutation**

In the authenticated `pixlogistic` MoySklad account, open customer-order settings and confirm the exact state is absent. Open customer-order print-template settings and confirm the embedded-template list used by order printing is empty. Capture screenshots containing no credentials.

- [ ] **Step 2: Create the missing state exactly once**

Create a customer-order state named exactly:

```text
Изменен клиентом
```

Use the same workflow category as other active customer-confirmation states. Save once, refresh, and confirm only one exact-name entry exists. Do not rename, reorder, or remove existing states.

- [ ] **Step 3: Configure one embedded customer-order PDF template**

Select the standard MoySklad customer-order print form available to the account and expose it as an embedded customer-order template. Do not upload a third-party document or replace templates for invoices and purchase orders.

Confirm through the existing backend repository/API diagnostic that `read_embedded_templates()` returns at least one row before proceeding. If MoySklad does not offer an embedded standard form, stop this step and report the exact UI limitation rather than uploading an unreviewed file.

### Task 3: Build immutable release images

**Files:**
- Transfer: Git-tracked backend archive from the verified backend commit.
- Transfer: Git-tracked frontend archive from the verified frontend commit.
- Preserve remotely: existing `.env`, data directories, Compose file, certificates, and uploads.

**Interfaces:**
- Consumes: successful local checks from the backend and edge/frontend plans.
- Produces: `backend:release-${PIX_BACKEND_SHA}` and `frontend_v2:release-${PIX_FRONTEND_SHA}`, using the exact short SHAs recorded in Step 1.

- [ ] **Step 1: Confirm clean release scope locally**

In each repository record `git rev-parse --short HEAD` as `PIX_BACKEND_SHA` or `PIX_FRONTEND_SHA`, run `git status --short`, and create the release archive with `git archive HEAD`. Git archives intentionally exclude ignored `.env`, `.venv`, `.next`, `node_modules`, `db_data`, caches, and unrelated uncommitted files.

- [ ] **Step 2: Transfer and verify release archives**

Copy both archives to a root-only staging directory on the new server. Compare local and remote SHA-256 values before extraction. Keep the archives until production verification finishes.

- [ ] **Step 3: Update code without replacing runtime state**

Back up the current tracked source tree, then extract the backend and frontend Git archives into their discovered build directories. Preserve the existing `.env`, Compose file if it contains host-specific edits, database directory, MinIO volume, TLS files, and all non-Git runtime state.

- [ ] **Step 4: Build the backend release image**

From the backend build directory:

```bash
docker build --pull=false -t "backend:release-${PIX_BACKEND_SHA}" .
```

Do not pass `.env` as a build argument and confirm the image starts with the production command defined by the reviewed Dockerfile.

- [ ] **Step 5: Build the frontend release image with explicit public inputs**

From the frontend build directory:

```bash
docker build --pull=false \
  --build-arg NEXT_PUBLIC_BACKEND_URL=https://pixlogistic.com/api_v1 \
  --build-arg NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT=false \
  -t "frontend_v2:release-${PIX_FRONTEND_SHA}" .
```

Verify the build completes and no secret is passed to a `NEXT_PUBLIC_*` argument.

### Task 4: Replace application containers and NGINX safely

**Files:**
- Modify remotely: active backend/frontend image tags used by Compose.
- Modify remotely: the active NGINX virtual-host file.

**Interfaces:**
- Consumes: release images and repository notification WebSocket block.
- Produces: running release containers and a validated notification WebSocket proxy.

- [ ] **Step 1: Point Compose at immutable release tags**

Edit only the backend and frontend `image:` values in the discovered production Compose file. Preserve database, MinIO, network, restart, environment, and volume configuration. Run `docker compose config --quiet` without printing the interpolated configuration.

- [ ] **Step 2: Replace backend and verify before frontend**

Run `docker compose up -d --no-deps backend`, then require:

```text
container running
restart count 0
OOMKilled false
GET http://127.0.0.1:8000/api_v1/health returns 200
no startup traceback in sanitized recent logs
```

If any check fails, restore the rollback backend tag and recreate only that service.

- [ ] **Step 3: Replace frontend and verify**

Run `docker compose up -d --no-deps frontend`, then require loopback HTTP 200, restart count 0, OOMKilled false, and no startup error. If it fails, restore the rollback frontend tag and recreate only that service.

- [ ] **Step 4: Patch the active host NGINX file**

Copy the notification WebSocket location from the verified repository configuration, but retain the active host file's existing `proxy_pass` upstream style. Place it before the generic `/api_v1/` location and preserve its `Upgrade`, `$connection_upgrade`, `Host`, and `X-Forwarded-For` headers.

- [ ] **Step 5: Validate and reload NGINX**

Run:

```bash
nginx -t
systemctl reload nginx
systemctl is-active nginx
```

Require successful syntax, a successful reload, and active state. On failure, restore the timestamped NGINX backup, re-run `nginx -t`, and reload the restored file.

### Task 5: Production smoke and regression tests

**Files:**
- Create temporarily in PIX/MoySklad: one uniquely marked QA address, order, and product.
- No local repository changes.

**Interfaces:**
- Consumes: deployed release, authenticated PIX account, authenticated MoySklad account.
- Produces: evidence for each confirmed bug fix and exact IDs for authorized cleanup.

- [ ] **Step 1: Verify infrastructure and public routing**

Require public frontend and `/api_v1/health` HTTP 200, Redis `PING`, PostgreSQL readiness, MinIO health, zero application restart loops, sufficient disk, and enabled swap. Sanitize any URL containing `auth=` before displaying logs.

- [ ] **Step 2: Verify notification WebSocket upgrade**

Open the authenticated notification page in Chrome and confirm the `/api_v1/notifications/ws` request upgrades instead of returning 404. Backend logs must show the notification WebSocket route accepted or an application-level auth result, and NGINX must not log an HTTP/1.0 404 for the route.

- [ ] **Step 3: Verify disabled chat makes no network calls**

Open an order detail page and confirm the `Комментарии по заказу` region is absent. Confirm the page initiates neither `/api_v1/chat/orders/` HTTP traffic nor `/api_v1/chat/ws` connections.

- [ ] **Step 4: Verify address duplicate handling**

Create a unique address with a QA marker, then submit the same normalized name with changed whitespace/case. Require HTTP 409 with detail code `address_name_conflict`, no HTTP 500, and exactly one stored address. Record the address ID for cleanup.

- [ ] **Step 5: Verify bounded checkout and idempotency**

Create a one-position QA order using a unique `example.net` URL/comment and a newly generated idempotency key. On the new host's known Telegram network failure, require a successful order response within the NGINX timeout and one MoySklad order. Retry the exact body and idempotency key and require the same order ID with no second order or product. Record the order and product IDs.

- [ ] **Step 6: Verify order edit and missing-side-effect fix in production**

Move the QA order to `Подтвержден менеджером` in MoySklad, then change only the existing position quantity in PIX and save. Require HTTP 200, state `Изменен клиентом`, one updated position, and no new product. This validates the configured state while unit tests cover the missing-state no-product branch.

- [ ] **Step 7: Verify PDF export**

Download the customer-order document from PIX. Require HTTP 200, `Content-Type: application/pdf`, a non-empty file beginning with the PDF signature, and the expected attachment filename. Do not accept an HTML error page renamed as PDF.

- [ ] **Step 8: Re-run server health checks after mutations**

Repeat container restart/OOM checks, public health, NGINX errors, backend tracebacks, Redis idempotency counts, disk, RAM, and swap. Confirm no new 500/502/504 response occurred in the tested routes.

### Task 6: Authorized QA cleanup and final rollback retention

**Files:**
- Delete only verified QA entities in PIX/MoySklad.
- Keep all backups, rollback image tags, and old-server data.

**Interfaces:**
- Consumes: successful Task 5 evidence and exact QA entity IDs.
- Produces: production account without test data and with rollback still available.

- [ ] **Step 1: Re-identify the earlier QA records before deletion**

Verify all of these immutable IDs still represent the previously created QA records:

```text
customer order 2512: b1f149b4-99ed-11f1-0a80-1a5800b0518e
product https://example.com/: b1a2076e-99ed-11f1-0a80-083800ad22cc
orphan product https://example.org/: a6a986f8-99ee-11f1-0a80-036200b0d987
```

Require the QA delivery comment/order context and confirm the two products are not referenced by any non-QA document. A mismatch stops deletion.

- [ ] **Step 2: Delete the new QA run in dependency order**

Delete the newly created QA order first, verify it is absent from active order search, then delete only its recorded product if no other document references it. Delete the unique QA address through PIX and verify it is absent.

- [ ] **Step 3: Delete the earlier QA order and products**

Delete order 2512 first. After confirming it no longer references products, delete the two exact product IDs above. Do not empty MoySklad trash globally and do not delete counterparty `Артем Клиент #40`.

- [ ] **Step 4: Verify cleanup and retain rollback**

Search PIX and MoySklad for all recorded QA IDs/markers and require no active matches. Retain the timestamped PostgreSQL/config backup, release archives, rollback Docker tags, and the running old server/Telegram bridge. Report that old-server retirement remains a separate future decision.
