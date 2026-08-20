# Pix Backend Agent Guide

## Purpose and Scope

This repository is the FastAPI backend for Pix Logistic. These instructions apply to the entire repository. The adjacent frontend checkout is `../pix_frontend_v2`; coordinate changes that affect URLs, payloads, authentication, cookies, or WebSocket behavior.

## Architecture Boundaries

- `main.py` owns the application factory, middleware, mounted routers, lifespan, scheduler gate, and liveness route.
- `routes/` owns HTTP/WebSocket transport and FastAPI dependencies. Keep business decisions out of route functions.
- `dependecies/` is the existing, intentionally misspelled dependency-wiring package. Do not rename it without a repository-wide migration.
- `manager/` owns use-case logic and external-service orchestration.
- `db/repository.py` and manager-specific repositories own persistence and external API calls.
- `db/models/` is the SQLAlchemy persistence model; `db/schemas/` is the Pydantic API/integration model.
- `config.py` is the only supported environment boundary. Add settings there instead of reading `os.getenv` elsewhere.
- See `docs/ARCHITECTURE.md` before changing cross-layer behavior.

## Local Setup and Commands

Run from the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-services.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

FastAPI runs on the host at `http://127.0.0.1:8000`; Compose runs only PostgreSQL and Redis. Setup creates `.env` from `.env.example` only when `.env` is absent.

## Verification Matrix

| Change | Minimum verification |
| --- | --- |
| Python, configuration, routes, managers, repositories | `scripts/check.ps1` |
| Startup/lifespan | Check `/api_v1/health` and import `main` in a fresh process |
| Database model or migration | Tests, `alembic history`, manual migration review |
| API contract | Backend checks plus frontend `npm.cmd run check` |
| Environment/docs only | `git diff --check` and compare against `config.Settings` |

Do not claim success from an earlier run; execute the relevant command after the final edit.

## Database and Migration Safety

- Never run Alembic migrations automatically as part of setup, tests, or an agent action.
- Inspect the active database URL and migration before `alembic upgrade`, `downgrade`, or revision generation.
- Treat production migration, data repair, volume deletion, and Compose volume removal as destructive operations requiring explicit approval and a recovery plan.
- Do not use the generic SQLite upsert path as proof of PostgreSQL compatibility.
- Revision `d4e5f6a7b8c9` removes obsolete messaging data and must follow its production runbook under `docs/operations/`; never apply it automatically.

## External Integrations and Secrets

- Ordinary import, setup, tests, and local startup must not contact production services.
- Missing optional integration values must fail through `IntegrationNotConfigured`; never add credential-bearing defaults.
- Use `MOYSKLAD_PASSWORD`. `MOYSKLAD_PASWORD` exists only as a temporary legacy input alias.
- Never print or commit `.env`, webhook URLs, tokens, passwords, external account identifiers, or credential-bearing Git URLs.
- Keep `ENABLE_SCHEDULER=false` locally unless a deliberate integration test is approved.

## Cross-Repository Contract

- Public API prefix: `/api_v1`.
- Liveness: `GET /api_v1/health`.
- Browser API base comes from frontend `NEXT_PUBLIC_BACKEND_URL` at build time.
- Chat is order-specific only. The WebSocket endpoint `/api_v1/chat/ws` requires both authentication and an order `room`; token and room semantics are shared with the frontend hook.
- Preserve website notification types `ORDER_UPDATED` and `ORDER_MESSAGE`; there is no general-support chat API.
- Coordinate backend schema/path changes with `../pix_frontend_v2/src/routes/routes.tsx` and browser tests.

## Source-of-Truth Documentation

- `README.md` — verified quick start.
- `docs/ARCHITECTURE.md` — components, flows, routes, data, deployment, debt.
- `docs/LOCAL_DEVELOPMENT.md` — setup, operation, checks, troubleshooting.
- `docs/ENVIRONMENT.md` — local and production variable inventory without secrets.
- `docs/SECURITY_NOTES.md` — credential rotation and trust boundaries.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — accepted design and implementation record.
