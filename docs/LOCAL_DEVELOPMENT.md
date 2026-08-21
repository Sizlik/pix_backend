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

This runs the scoped Ruff baseline and all pytest tests. Tests cover settings,
production-secret validation, offline import, health, 503 mapping, missing
integration credentials, immutable site/operator order chat, attachment
isolation, removal of the MoySklad projection runtime, NGINX operator limits,
and multi-worker fanout using local fakes.

The adjacent frontend owns the Chrome extension workspace. Its deterministic
check includes unit/type/lint, Manifest validation, production builds and an
unpacked-extension Chromium smoke:

```powershell
Push-Location ..\pix_frontend_v2
npm.cmd ci
npm.cmd run check:extension
Pop-Location
```

The extension defaults to `http://localhost:8000/api_v1`. Loading it unpacked
is documented in `../pix_frontend_v2/moysklad-chat-extension/README.md`.
Entering a local shared secret and exercising a real order requires deliberate
local MoySklad credentials, MinIO, Redis, a linked user/order and
`ENABLE_MOYSKLAD_ORDER_CHAT=true`; ordinary checks use fakes and keep the flag
false.

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

## Production rollout

Production activation is an operator workflow, not an automated setup
sequence. Ordinary local checks never mutate a deployed database, install a
secret, deploy an artifact, or remove a webhook.

Follow
`docs/operations/moysklad-chat-extension-cutover.md` for the Chrome-extension
cutover, including backup/MinIO checks, exact-revision review, staged enablement,
two-way text/file smoke, legacy webhook removal and rollback. The runbook may
apply only `e3b7c9d1a204` when production is already exactly at
`d4e5f6a7b8c9`; it never runs `alembic upgrade head`.

Revision `d4e5f6a7b8c9` remains a separate destructive historical migration with
its own removal runbook. If production has not already applied it, stop the
extension cutover and complete that independent approval/recovery process
first. Later removal of retained projection-only tables is another destructive
operation and is outside both local setup and the extension cutover.

The application exposes only order-specific chat. There is no general-support
chat fallback. New messages and attachments remain in PostgreSQL/MinIO and are
transported by the website and Chrome extension; they are not rendered into
MoySklad comments/files.
