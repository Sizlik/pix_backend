# Pix Logistic Backend

FastAPI service for authentication, users, orders, payments, organizations, notifications, support chat, and integrations with MoySklad, Bitrix, Privoz, Telegram, and email delivery.

## Local quick start

Prerequisites: Python 3.11, Docker Desktop with Compose, and PowerShell.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-services.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
```

The application runs directly on Windows; only PostgreSQL and Redis run in Docker. Local setup does not run Alembic and does not require external integration credentials.

- Swagger UI: `http://127.0.0.1:8000/docs`
- Liveness: `http://127.0.0.1:8000/api_v1/health`
- Full checks: `powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1`

The frontend lives in the adjacent `../pix_frontend_v2` checkout and defaults to this local API.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Local development](docs/LOCAL_DEVELOPMENT.md)
- [Environment variables](docs/ENVIRONMENT.md)
- [Security notes](docs/SECURITY_NOTES.md)
- [Agent guide](AGENTS.md)

External integrations are lazy: an endpoint that needs an unconfigured integration returns a sanitized service-unavailable error rather than breaking application startup.
