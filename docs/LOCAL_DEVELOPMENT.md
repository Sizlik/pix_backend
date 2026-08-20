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

`ENABLE_MOYSKLAD_ORDER_CHAT=false` is the local default. With it disabled, imports and tests do not require MinIO or contact MoySklad. The order-chat unit tests use fakes; the explicit migration suite uses only loopback PostgreSQL and disposable schemas.

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

Set `ENABLE_SCHEDULER=true` only for an approved integration run with all MoySklad, Privoz, PostgreSQL, and Redis settings. It can read and mutate external state and create website `ORDER_UPDATED` notifications.

### Tests show deprecation warnings

Known warnings currently come from passlib packaging, SQLAlchemy `as_scalar()`, and the pinned FastAPI/httpx test stack. They are recorded debt; new warnings from touched code should still be investigated.

## Production rollout and removal migration

This is an operator workflow, not an automated setup sequence. Ordinary local
checks never mutate a deployed database or register a webhook.

1. Merge only missing keys from `.env.production.example` into the ignored
   production environment. Preserve working values and keep
   `ENABLE_MOYSKLAD_ORDER_CHAT=false` during the initial image rollout.
2. Build and deploy the frontend and backend images first. Record their exact
   tags, validate the base production configuration, and verify `/api_v1/health`.
3. The order-chat preflight requires MoySklad, webhook, MinIO, PostgreSQL,
   Redis, authentication, and HTTPS/CORS settings. It has no side-notification
   provider requirement:

   ```bash
   python scripts/check_production_config.py --require-order-chat
   ```

4. Revision `d4e5f6a7b8c9` backfills eligible legacy order messages, rewrites
   their `ORDER_MESSAGE` notification targets, and removes the obsolete schema.
   It is destructive and manual. Follow its production runbook under
   `docs/operations/` for target review, count-only
   audits, validated backup, the separately approved exact upgrade command, and
   post-migration checks. Do not use `alembic upgrade head` for this change.
5. Enable order chat only after MinIO persistence and the MoySklad projection
   have been validated. Webhook preview performs a live MoySklad request; apply
   registration only with separate approval.
6. In a staging order, verify site text/files, the MoySklad comment and
   `[КЛИЕНТ]` reply format, website `ORDER_MESSAGE` notification, Redis/WebSocket
   fanout, owner isolation, deduplication, and immutable history controls.

The application exposes only order-specific chat. There is no general-support
chat fallback. Before the removal migration, application rollback uses the
captured image tags. After it, deleted values require the validated backup;
the downgrade recreates empty compatibility structures only.
