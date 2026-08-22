# Pix Logistic Backend

FastAPI service for authentication, users, orders, payments, organizations, website notifications, order-specific chat, and integrations with MoySklad, Bitrix, Privoz, and email delivery.

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
Its `moysklad-chat-extension` workspace builds the operator Chrome extension;
run `npm.cmd run check:extension` from that checkout for unit, Manifest, build,
and unpacked-Chromium smoke coverage.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Local development](docs/LOCAL_DEVELOPMENT.md)
- [Environment variables](docs/ENVIRONMENT.md)
- [Security notes](docs/SECURITY_NOTES.md)
- [MoySklad extension cutover](docs/operations/moysklad-chat-extension-cutover.md)
- [Order-chat inbox and email rollout](docs/operations/order-chat-inbox-email-rollout.md)
- [Agent guide](AGENTS.md)

External integrations are lazy: an endpoint that needs an unconfigured integration returns a sanitized service-unavailable error rather than breaking application startup.

The operator inbox is available through
`GET /api_v1/chat/operator/conversations`,
`POST /api_v1/chat/operator/orders/{order_id}/read`, and the authenticated
read-only `/api_v1/chat/operator/inbox/ws`. Durable client/manager email is a
separate opt-in feature and stays disabled until the staged rollout explicitly
enables it.

Email verification links the verified account to its MoySklad counterparty without a side notification. Website `ORDER_UPDATED` and `ORDER_MESSAGE` notifications remain active. The order-only chat stores immutable history in PostgreSQL and attachments in MinIO, serves the same rooms through the customer website and secret-authenticated Chrome extension, and publishes updates through Redis-backed WebSockets. New chat content is not mirrored to MoySklad comments/files. There is no general-support chat or `/bot` router.

Production preparation starts from `.env.production.example`. Merge only
missing keys into the existing ignored server `.env`, leave the feature flag
off for the first deployment, and run
`python scripts/check_production_config.py` before any container update. The
manual migration, feature enablement, extension installation, two-way
text/file smoke and legacy-webhook removal checkpoints are documented in the
extension cutover runbook. Live signed-in MoySklad smoke, migration, secret
installation, deployment, and webhook removal always remain manual approved
operations. The destructive historical revision `d4e5f6a7b8c9` keeps its own
backup/recovery runbook under `docs/operations/`.
