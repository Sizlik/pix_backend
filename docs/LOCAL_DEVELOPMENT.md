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

Setup creates `.venv`, installs `requirements-dev.txt`, and copies `.env.example` to ignored `.env` only when necessary. Compose starts PostgreSQL 16 on host port 5431 and Redis 7 on port 6379 with named volumes and health checks.

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

`down` preserves named volumes. Do not add `--volumes` unless deleting local database/Redis data is explicitly intended.

## Checks

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

This runs the scoped Ruff baseline and all pytest tests. Tests cover settings, production-secret validation, offline import, health, 503 mapping, and missing integration credentials.

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

Start Docker Desktop, wait for `docker info` to succeed, then rerun `scripts/start-services.ps1`. Use `docker compose -f local-docker-compose.yml ps` and require both services to show `healthy`.

### Port 5431 or 6379 is busy

Identify the existing process/container before changing ports. If a port changes, update both Compose and the corresponding backend setting.

### Missing integration error

Offline local startup intentionally leaves integration values empty. Endpoints that need an integration return HTTP 503. Add only the specific local credential to ignored `.env`; never commit it.

### Production-like scheduled sync is needed

Set `ENABLE_SCHEDULER=true` only for an approved integration run with all MoySklad, Privoz, Telegram, PostgreSQL, and Redis settings. It can read and mutate external state.

### Tests show deprecation warnings

Known warnings currently come from passlib packaging, SQLAlchemy `as_scalar()`, and the pinned FastAPI/httpx test stack. They are recorded debt; new warnings from touched code should still be investigated.
