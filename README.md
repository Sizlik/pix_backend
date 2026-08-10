# Pix Logistic Backend

FastAPI service for authentication, users, orders, payments, organizations, notifications, support chat, and integrations with MoySklad, Bitrix, Privoz, Telegram, and email delivery.

## Local quick start

Prerequisites: Python 3.11, Docker Desktop with Compose, and PowerShell.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-services.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
```

The application runs directly on Windows; PostgreSQL, Redis, and a source-built pinned MinIO run in Docker. Local setup does not run Alembic and does not require external integration credentials. MoySklad order chat stays disabled by default, so ordinary setup and checks remain offline.

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

The order-only chat stores immutable history in PostgreSQL and attachments in MinIO, mirrors client messages to MoySklad customer-order comments/files, and keeps Telegram as a side notification channel. See the architecture, environment, local-development, and security documents above before enabling it or registering its webhook.
