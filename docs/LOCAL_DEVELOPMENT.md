# Local Development

## Prerequisites

- Windows with PowerShell.
- Python 3.11 available as `python`.
- Docker Desktop with Compose.
- Node.js is needed only for the adjacent frontend; Node.js 20 LTS is recommended there.

## First setup

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-services.ps1
```

Setup creates `.venv`, installs `requirements-dev.txt`, and copies `.env.example` to ignored `.env` only when necessary. Compose starts PostgreSQL 16 on host port 5431, Redis 7 on port 6379, and source-built pinned MinIO on ports 9000/9001 with named volumes and health checks. The MinIO S3 API is `http://127.0.0.1:9000`; its development console is `http://127.0.0.1:9001`.

`ENABLE_MOYSKLAD_ORDER_CHAT=false` is the local default. With it disabled, imports and tests do not require MinIO or contact MoySklad/Telegram. The order-chat tests use fakes only; passing them is not evidence of a live integration.

No Alembic migration is run automatically. A fresh database therefore has no application tables until a developer deliberately reviews and applies migrations.

## Start and stop

Start FastAPI on the host:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
```

Check it:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api_v1/health
```

Inspect or stop infrastructure:

```powershell
docker compose -f local-docker-compose.yml ps
docker compose -f local-docker-compose.yml down
```

`down` preserves named volumes. Do not add `--volumes` unless deleting local PostgreSQL, Redis, and MinIO data is explicitly intended.

To build or start only the pinned MinIO service deliberately:

```powershell
docker compose -f local-docker-compose.yml build minio
docker compose -f local-docker-compose.yml up -d minio
docker compose -f local-docker-compose.yml ps minio
```

The source build downloads the pinned Git tag and Go modules, so the first build needs approved network access. Never replace the pin with `latest` during an incident.

## Checks

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

This runs the scoped Ruff baseline and all pytest tests. Tests cover settings, production-secret validation, offline import, health, 503 mapping, missing integration credentials, immutable order chat, projection/retry rules, webhook deduplication, and multi-worker fanout using local fakes.

For a manual startup smoke:

```powershell
& .\.venv\Scripts\python.exe -c "import main; print(main.app.title)"
```

Import and health checks must not contact external integrations.

## Alembic workflow

Inspect before changing a database:

```powershell
& .\.venv\Scripts\alembic.exe history
& .\.venv\Scripts\alembic.exe current
```

Only after checking `POSTGRES_HOST`, `DB_PORT`, database identity, backup/recovery, and the migration body should a developer deliberately run `alembic upgrade head`. Never make it part of setup or agent startup actions.

## Troubleshooting

### PowerShell blocks npm.ps1

Use `npm.cmd` and `npx.cmd` in the frontend. Project scripts already do this.

### Docker daemon is unavailable

Start Docker Desktop, wait for `docker info` to succeed, then rerun `scripts/start-services.ps1`. Use `docker compose -f local-docker-compose.yml ps` and require PostgreSQL, Redis, and MinIO to show `healthy`.

### Port 5431, 6379, 9000, or 9001 is busy

Identify the existing process/container before changing ports. If a port changes, update both Compose and the corresponding backend setting.

### Missing integration error

Offline local startup intentionally leaves integration values empty. Endpoints that need an integration return HTTP 503. Add only the specific local credential to ignored `.env`; never commit it.

### Production-like scheduled sync is needed

Set `ENABLE_SCHEDULER=true` only for an approved integration run with all MoySklad, Privoz, Telegram, PostgreSQL, and Redis settings. It can read and mutate external state.

### Tests show deprecation warnings

Known warnings currently come from passlib packaging, SQLAlchemy `as_scalar()`, and the pinned FastAPI/httpx test stack. They are recorded debt; new warnings from touched code should still be investigated.

## MoySklad order-chat production rollout

This is an operator runbook, not an automated setup sequence. None of these
commands belongs in ordinary local checks.

1. Copy only missing keys from `.env.production.example` into the existing
   ignored server `.env`. Preserve every working value and keep
   `ENABLE_MOYSKLAD_ORDER_CHAT=false`. Restrict the resulting file to the
   deployment account.
2. Validate the base configuration and Compose without printing `.env` or
   starting containers:

   ```bash
   docker build -t backend .
   docker run --rm --env-file .env backend python scripts/check_production_config.py
   docker-compose --env-file .env config --quiet
   ```

3. Resolve the exact production PostgreSQL container and Compose volume names.
   Record the restore owner, retention and storage location. Back up PostgreSQL
   before the schema change. Back up the resolved `pix-minio-data` volume in the
   same retention set if it already contains data. Never use `down --volumes`.
4. Deploy code with the feature disabled. Build the pinned MinIO source image,
   scan it, start MinIO and inspect health:

   ```bash
   docker-compose --env-file .env build minio
   docker-compose --env-file .env up -d minio
   docker-compose --env-file .env ps minio
   ```

   If the prebuilt frontend image is refreshed for this release, supply its
   public API origin during the image build (runtime `env_file` is too late):

   ```bash
   docker build --build-arg NEXT_PUBLIC_BACKEND_URL=https://pixlogistic.com/api_v1 -t frontend_v2:latest ../pix_frontend_v2
   ```

   Upload one uniquely named disposable object through an approved S3 client,
   restart only MinIO, verify the same bytes, then delete only that object. Keep
   the named volume.
5. Inspect the active database host/name without displaying its password and
   review both migration history and
   `alembic/versions/c8f2a4e6d901_order_chat_delivery.py`:

   ```bash
   docker-compose run --rm backend alembic current
   docker-compose run --rm backend alembic history
   ```

   After the PostgreSQL backup and separate migration approval, apply only:

   ```bash
   docker-compose run --rm backend alembic upgrade c8f2a4e6d901
   ```

6. Add the production MoySklad, Telegram, webhook and MinIO values to the
   ignored `.env`, set `ENABLE_MOYSKLAD_ORDER_CHAT=true`, then require the full
   order-chat configuration before restarting only the backend:

   ```bash
   docker run --rm --env-file .env backend python scripts/check_production_config.py --require-order-chat
   docker-compose --env-file .env up -d --no-deps --force-recreate backend
   curl -fsS https://pixlogistic.com/api_v1/health
   ```

7. Make one authenticated order-history request, then preview webhook
   registration:

   ```bash
   docker-compose exec backend python scripts/register_moysklad_order_chat_webhook.py --base-url https://pixlogistic.com
   ```

   This preview is not offline: it performs a live MoySklad webhook-list
   request. Review only its redacted target and obtain separate approval before
   repeating the command with `--apply`.
8. In a staging order, send site text, a photo and a PDF. Verify the standard
   MoySklad comment/files and Telegram group alert. Reply below the marker with
   text and a `[КЛИЕНТ]` file; verify site realtime/history and the client
   Telegram alert.
9. Verify that a second client gets `404`, an internal manager file is hidden,
   a repeated webhook `requestId` does not duplicate history, immutable table
   triggers reject update/delete, and two open tabs both receive one reply.

For incident rollback, first restore
`ENABLE_MOYSKLAD_ORDER_CHAT=false` in the ignored `.env` and recreate only the
backend container. After separate approval, disable/delete only the exact
registered order-chat webhook. Keep the PostgreSQL tables and MinIO volume
intact and continue the existing general-support chat. Do not downgrade the
append-only migration during incident rollback.
