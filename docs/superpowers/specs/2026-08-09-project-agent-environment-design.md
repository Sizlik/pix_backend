# Project Agent Environment Design

## Context

Pix Logistic consists of two adjacent Git repositories:

- `pix_backend`: FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, APScheduler, FastAPI Users, Telegram, MoySklad, Bitrix, Privoz, and email integrations.
- `pix_frontend_v2`: Next.js 14 App Router, React 18, TypeScript, Tailwind CSS, Axios, and WebSocket-based support chat.

Neither repository currently has project-level Codex instructions. Backend has no meaningful project README or automated test suite. Frontend still has the generated Next.js README and hard-codes the production API URL. Local Python and Node dependencies are not installed. Application imports currently instantiate integration clients and call external services, so the backend cannot start safely without production credentials.

## Goals

1. Give Codex durable, repository-specific guidance through a separate `AGENTS.md` in each repository.
2. Document the current architecture, module boundaries, data flows, local development workflow, environment variables, and known technical debt.
3. Make backend and frontend applications run locally with reproducible Windows-first setup, run, and check commands.
4. Keep PostgreSQL and Redis in a local Docker Compose stack while running FastAPI and Next.js directly on the host.
5. Centralize and validate backend configuration without requiring production integrations during local startup.
6. Add a minimal, useful verification baseline for both repositories.
7. Remove credentials from source configuration and local Git remote URLs without copying their values into documentation or output.
8. Provide an exact production environment-variable inventory with descriptions and formats, but no production values.
9. Install only the official Codex skills that materially support recurring work on this project.

## Non-goals

- Rewriting business workflows or changing API contracts unrelated to configuration and health reporting.
- Replacing the repository/manager architecture.
- Applying database migrations automatically.
- Rewriting Git history, revoking credentials, or inventing replacement secret values.
- Fixing every item recorded in the technical-debt inventory.
- Containerizing FastAPI or Next.js for the primary local workflow.

## Repository Guidance

Each repository receives a concise root `AGENTS.md`. The files describe:

- repository purpose and important directories;
- architectural boundaries and source-of-truth documents;
- supported setup, run, lint, test, and build commands;
- rules for database migrations and external integrations;
- verification expectations for common changes;
- secret-handling and production-safety constraints;
- cross-repository contract considerations.

Backend guidance must point to the shared system documentation. Frontend guidance must identify `src/routes/routes.tsx` as the current API-client boundary and explain that public environment variables are build-time values.

## Documentation Structure

The backend repository is the source of truth for shared project documentation:

- `README.md`: project overview and fast local start.
- `docs/ARCHITECTURE.md`: system context, backend layers, frontend structure, data stores, REST/WebSocket flows, external integrations, deployment topology, and known boundaries.
- `docs/LOCAL_DEVELOPMENT.md`: prerequisites, first setup, service startup, application startup, checks, troubleshooting, and safe migration commands.
- `docs/ENVIRONMENT.md`: local and production variables grouped by core backend, integrations, scheduler, frontend build-time configuration, and PgAdmin infrastructure.
- `docs/SECURITY_NOTES.md`: credential locations and rotation actions without secret values, plus relevant configuration risks.

The frontend README is replaced with project-specific setup, run, verification, environment, and backend-contract information.

## Target Architecture and Data Flow

The existing logical flow remains:

```text
Next.js UI
  -> REST and WebSocket requests under /api_v1
  -> FastAPI route modules
  -> dependency factories and managers
  -> SQLAlchemy repositories or external-service adapters
  -> PostgreSQL, Redis, MoySklad, Bitrix, Privoz, Telegram, and email services
```

PostgreSQL remains the local system of record for users, organizations, order metadata, order items/actions, chat, notifications, transactions, and imported Privoz order states. Redis remains responsible for authentication-token strategy and FastAPI cache state. MoySklad remains the authoritative external source for logistics documents, positions, payments, and document exports.

## Backend Configuration

Backend settings are centralized in a typed configuration module. Core application settings and optional integration settings have explicit boundaries.

Required behavior:

- `.env` is loaded consistently for local development.
- Database, Redis, authentication-token lifetime, CORS, and scheduler settings have validated types.
- Integration credentials are optional at process startup.
- No module performs network I/O merely because it is imported.
- Telegram and MoySklad clients are created lazily after their settings are validated.
- Endpoints that require an unconfigured integration return a sanitized `503 Service Unavailable` response.
- The hourly synchronization scheduler runs only when `ENABLE_SCHEDULER` is true.
- Production CORS origins come from `CORS_ORIGINS`; local examples allow only the local frontend origin.
- The canonical MoySklad variable is `MOYSKLAD_PASSWORD`. The legacy misspelling `MOYSKLAD_PASWORD` is accepted temporarily as a compatibility alias and is documented as deprecated.
- Bitrix has no credential-bearing default URL.
- Privoz username and password come from environment settings.
- Logs and error responses never contain secret values.

The environment inventory includes every variable consumed by application or production Compose configuration. Variables added by this design include `APP_ENV`, `CORS_ORIGINS`, `ENABLE_SCHEDULER`, `PRIVOZ_USERNAME`, and `PRIVOZ_PASSWORD`. Frontend uses `NEXT_PUBLIC_BACKEND_URL` as a build-time variable.

## Local Development Workflow

Applications run on the Windows host. PostgreSQL and Redis run through the local Compose file.

Backend scripts:

- `scripts/setup-local.ps1`: create `.venv`, install runtime and development requirements, and copy the safe environment template only when `.env` does not exist.
- `scripts/start-services.ps1`: start the local PostgreSQL and Redis services.
- `scripts/run-local.ps1`: run Uvicorn from the project virtual environment.
- `scripts/check.ps1`: run Ruff and pytest with the project virtual environment.

Frontend scripts:

- `scripts/setup-local.ps1`: install the locked dependency tree with `npm.cmd ci` and install the Playwright Chromium runtime.
- `scripts/run-local.ps1`: run the Next.js development server through `npm.cmd`.
- `scripts/check.ps1`: run ESLint, the production build, and Playwright smoke tests.

PowerShell scripts fail fast, use paths relative to their repository roots, do not overwrite existing `.env` files, do not run migrations implicitly, and do not contact production services as part of setup or checks.

The same setup, run, and check commands are registered as local Codex Desktop actions using the app's supported project environment configuration.

## Verification Baseline

Backend development dependencies include Ruff, pytest, pytest-asyncio, and HTTPX-compatible FastAPI testing support. Tests cover:

- typed environment parsing and safe defaults;
- compatibility behavior for the legacy MoySklad password name;
- importing/creating the application without external network calls;
- sanitized `503` behavior for an unconfigured integration;
- an application liveness endpoint that does not depend on external services.

Backend checks must not apply Alembic migrations. Documentation explains how to inspect the migration graph and how to run upgrades deliberately against a confirmed local database.

Frontend verification includes:

- ESLint and TypeScript checks through the Next.js build;
- a Playwright configuration and public-page smoke test;
- a source check ensuring production API URLs are not hard-coded in the API-client boundary.

The API base URL is read from `NEXT_PUBLIC_BACKEND_URL`, with a documented local default suitable for development and an explicit production value requirement at build time.

## Health and Error Handling

The backend exposes a liveness endpoint under the API prefix. It confirms that the FastAPI process is running without probing third-party systems or leaking configuration. Integration configuration failures use one project exception mapped to HTTP 503 with a stable, non-secret message. Unexpected upstream failures keep their existing API behavior unless a configuration guard is required for safe local startup.

## Skills

Install these official curated Codex skills into the user's Codex skills directory:

- `security-best-practices` for recurring secure implementation and review guidance;
- `security-threat-model` for the project's multiple external trust boundaries;
- `playwright` for browser-based frontend verification.

Do not duplicate capabilities already installed through system skills or plugins, including OpenAI Docs, GitHub workflows, and screenshot support. Newly installed skills become available to Codex on a subsequent turn.

## Security Remediation

Known credential-bearing locations are documented by file or configuration category only. The implementation:

- replaces embedded Bitrix and Privoz credentials with environment-backed settings;
- removes embedded credentials from both local Git `origin` URLs while retaining ordinary HTTPS remotes;
- adds `.env`, virtual environments, caches, local data, and generated test artifacts to appropriate ignore files;
- does not print, copy, commit, or preserve credential values in project documentation;
- records that affected Bitrix, Privoz, and Git credentials must be rotated manually because removal from the current working tree does not invalidate previously exposed values.

Git history is not rewritten. Credential revocation and production secret insertion remain manual operator actions.

## Technical-Debt Inventory

Architecture documentation records, without broad unrelated fixes:

- import-time creation of external clients and network calls;
- permissive wildcard CORS;
- missing automated tests and backend lint configuration;
- generated frontend README and hard-coded production API URLs;
- simultaneous `package-lock.json` and `yarn.lock`, with npm selected as the supported package manager;
- the legacy `MOYSKLAD_PASWORD` spelling;
- empty or currently unused invoice modules;
- the unusual self-include call on the root API router;
- synchronous HTTP calls inside async request paths;
- current deployment assumptions and manual migration risks.

Only items required for safe configuration, local startup, documentation, or the agreed verification baseline are changed in this effort.

## Acceptance Criteria

1. Both repositories contain a project-specific `AGENTS.md` that Codex can discover from the repository root.
2. Shared architecture, local-development, environment, and security documentation accurately reflects the inspected code.
3. Backend setup creates an isolated Python 3.11 environment and installs locked runtime plus development dependencies.
4. Frontend setup installs dependencies using npm and the committed npm lockfile.
5. PostgreSQL and Redis can be started locally without running either application in a container.
6. FastAPI imports and starts without contacting or requiring production integrations when they are disabled.
7. Frontend uses the environment-provided backend URL and contains no active hard-coded production API base.
8. Backend Ruff/pytest checks and frontend lint/build/Playwright smoke checks pass, or any environment-level blocker is reported with its exact command and output.
9. Production environment documentation lists every required and optional variable with purpose and format but no secret value.
10. Embedded source credentials and credential-bearing local Git remote URLs are removed without rewriting history.
11. The three selected curated Codex skills are installed successfully and reported as available for the next turn.
12. Repository changes contain no `.env`, credential value, virtual environment, dependency directory, database data, or generated browser artifact.
