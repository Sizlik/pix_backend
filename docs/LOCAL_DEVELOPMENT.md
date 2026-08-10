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

This is an operator runbook, not an automated setup sequence:

1. Back up PostgreSQL and the `pix-minio-data` volume. Record tested restore commands, retention, storage location, and the responsible owner.
2. Deploy code and containers with `ENABLE_MOYSKLAD_ORDER_CHAT=false`. Build the pinned MinIO source image and scan the resulting image before promotion.
3. Inspect `alembic history`, the active database host/name without printing its password, and the SQL in migration `c8f2a4e6d901`. Obtain explicit approval before `alembic upgrade c8f2a4e6d901`.
4. Start MinIO, verify its health, upload one disposable object, restart only MinIO, and confirm the object remains. Delete only that object; keep the named volume.
5. Set production MinIO and webhook secrets, enable the feature, restart the backend, verify `/api_v1/health`, and make one authenticated order-history request.
6. Run `python scripts/register_moysklad_order_chat_webhook.py --base-url https://pixlogistic.com` without `--apply`. This preview performs a live webhook-list request. Review only the redacted plan, obtain approval, then rerun with `--apply`.
7. In a staging order, send site text, a photo, and a PDF; verify the standard MoySklad comment/files and Telegram group alert. Reply below the marker with text and a `[КЛИЕНТ]` file; verify site realtime/history and the client Telegram alert.
8. Verify that a second client gets `404`, an internal manager file is hidden, a repeated webhook `requestId` does not duplicate history, and two open tabs both receive one reply.

For incident rollback, first set `ENABLE_MOYSKLAD_ORDER_CHAT=false` and restart the backend. After separate approval, disable/delete only the exact registered order-chat webhook. Keep the PostgreSQL tables and MinIO volume intact and continue the existing general-support chat. Do not downgrade the append-only migration during incident rollback.
