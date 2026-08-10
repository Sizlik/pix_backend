# Production Order Chat Deployment Preparation Implementation Plan

> **For Codex:** Execute this plan task by task. Use test-driven development for validation code, keep the production feature disabled, and do not contact production or real integrations.

**Goal:** Prepare copy-safe production environment data, Docker build boundaries, MinIO startup, and a non-destructive deployment pipeline for the already-running Pix Logistic server.

**Architecture:** `config.Settings` remains the only environment boundary. A pure production validator reports variable names without values, while a thin CLI turns those results into a CI exit code. The current Compose topology remains intact; MinIO is added to it with persistent storage and health-gated backend startup. Frontend API origin becomes an explicit build input rather than an accidental `.env.local` input.

**Tech stack:** Python 3.11, Pydantic Settings, pytest, Docker/Compose, GitHub Actions, Next.js 14, Node 18.

---

## Safety constraints for every task

- Do not read or print the contents of the ignored production `.env`.
- Use synthetic values in tests and temporary validation files only.
- Do not run `alembic upgrade`, `alembic downgrade`, webhook registration, production SSH, or any external integration call.
- Do not start, stop, or restart production containers.
- Do not remove Docker volumes or run Docker prune.
- Preserve the existing modified tracked `alembic/versions/__pycache__/*.pyc` files and exclude them from every commit.
- Keep `ENABLE_MOYSKLAD_ORDER_CHAT=false` in the tracked production example and ordinary deployment preflight.

### Task 1: Add a sanitized production configuration validator

**Files:**

- Create: `tests/test_production_config.py`
- Create: `manager/production_config.py`
- Modify: `config.py`
- Modify: `scripts/check.ps1`

**Step 1: Write failing tests**

Create synthetic production settings helpers and tests proving:

- base mode accepts strong PostgreSQL/authentication values, HTTPS CORS, and `https://pixlogistic.com/api_v1` while order chat is disabled;
- base mode rejects non-production `APP_ENV`, local/default secrets, wildcard or non-HTTPS production CORS, and an invalid frontend API URL;
- order-chat mode requires `ENABLE_MOYSKLAD_ORDER_CHAT=true`, `MOYSKLAD_LOGIN`, correctly spelled `MOYSKLAD_PASSWORD`, `BOT_TOKEN`, `CHAT_ID`, `HELP_CHAT_ID`, a long URL-safe webhook secret, MinIO endpoint/access/secret/bucket, and positive attachment/outbox limits;
- invalid reports contain variable names and stable reasons but never contain supplied passwords, tokens, login values, Telegram IDs, Redis credentials, or webhook secrets;
- the deprecated `MOYSKLAD_PASWORD` alias is never presented as the production key.

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_production_config.py -v
```

Expected: fail because the production validator does not exist.

**Step 2: Extend the environment boundary**

Add only deployment-facing settings that are currently documented but absent from `Settings`:

```python
next_public_backend_url: str | None = None
pgadmin_default_email: str | None = None
pgadmin_default_password: SecretStr | None = None
```

Do not add `os.getenv` reads outside `config.py`.

**Step 3: Implement the pure validator**

Create an immutable issue type with `variable` and `reason` fields and:

```python
def validate_production_settings(
    settings: Settings,
    *,
    require_order_chat: bool,
) -> tuple[ProductionConfigIssue, ...]:
    ...
```

Validation must inspect values but return only variable names and generic rules. Require an HTTPS origin for CORS and an HTTPS `NEXT_PUBLIC_BACKEND_URL` with no credentials, query, fragment, or trailing path other than `/api_v1`. Require strong deployment secrets without returning their length or content. Accept `MINIO_ENDPOINT=localhost:9000` for the agreed host-network topology.

Add the new module and test to the scoped Ruff/check list.

**Step 4: Run focused tests**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_production_config.py tests/test_config.py tests/test_order_chat_config.py -v
& ".\.venv\Scripts\python.exe" -m ruff check config.py manager/production_config.py tests/test_production_config.py
```

Expected: pass with no secret values in output.

**Step 5: Commit**

```powershell
git add config.py manager/production_config.py tests/test_production_config.py scripts/check.ps1
git commit -m "feat: validate production deployment settings"
```

### Task 2: Add the non-mutating production preflight CLI

**Files:**

- Create: `scripts/check_production_config.py`
- Modify: `tests/test_production_config.py`
- Modify: `scripts/check.ps1`

**Step 1: Write failing CLI tests**

Test `main(argv)` with monkeypatched `Settings` construction or an injected settings object. Cover:

- base mode exit `0` and a short success line;
- `--require-order-chat` exit `0` only for complete synthetic chat configuration;
- invalid configuration exit `1`, output containing only safe variable names/reasons;
- unexpected settings parsing failure exit `1` with a generic message and no raw exception payload.

Run the focused tests and confirm they fail before the script exists.

**Step 2: Implement the CLI**

The script loads the normal process environment through `Settings()` and supports only:

```text
python scripts/check_production_config.py
python scripts/check_production_config.py --require-order-chat
```

It must not accept credentials on the command line, enumerate the environment, perform network calls, or display raw Pydantic exceptions. Output issues in deterministic variable-name order.

**Step 3: Verify and commit**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_production_config.py -v
& ".\.venv\Scripts\python.exe" -m ruff check scripts/check_production_config.py tests/test_production_config.py
git add scripts/check_production_config.py tests/test_production_config.py scripts/check.ps1
git commit -m "feat: add production configuration preflight"
```

### Task 3: Add the copy-ready production environment template

**Files:**

- Create: `.env.production.example`
- Modify: `.gitignore`
- Modify: `tests/test_production_config.py`
- Modify: `docs/ENVIRONMENT.md`

**Step 1: Write failing template contract tests**

Parse the example as data without exporting it. Assert that it:

- contains every key in the documented production inventory;
- uses `APP_ENV=production` and `ENABLE_MOYSKLAD_ORDER_CHAT=false`;
- uses `MINIO_ENDPOINT=localhost:9000`, `MINIO_BUCKET=pix-order-chat`, and the approved limits/retry defaults;
- uses `NEXT_PUBLIC_BACKEND_URL=https://pixlogistic.com/api_v1`;
- leaves every credential-bearing value blank;
- does not contain `MOYSKLAD_PASWORD`, local passwords, sample tokens, URL credentials, or an unredacted webhook path;
- is explicitly unignored while other `.env*` files remain ignored.

Run the test and confirm it fails because the template is absent.

**Step 2: Add the template and documentation**

Add `!.env.production.example` to `.gitignore`. Keep comments copy-safe and tell the operator to merge missing keys into the existing server `.env`, never replace it wholesale.

Include all current settings grouped into application/database, Redis/auth/CORS, existing integrations, order chat/MinIO, frontend build, and Compose/pgAdmin. Real secrets remain empty.

**Step 3: Verify and commit**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_production_config.py -v
git diff --check
git add .gitignore .env.production.example docs/ENVIRONMENT.md tests/test_production_config.py
git commit -m "docs: add production environment template"
```

### Task 4: Harden Compose without changing production topology

**Files:**

- Modify: `docker-compose.yml`
- Modify: `tests/test_production_config.py`

**Step 1: Write failing static Compose tests**

Assert that the production Compose contract retains the exact service set and published ports while requiring:

- backend image `backend:latest` plus local build context `.`;
- backend host networking;
- MinIO source build through `infra/minio/Dockerfile`;
- the `pix-minio-data` named volume;
- MinIO healthcheck and restart policy;
- backend dependency on a healthy MinIO service;
- environment-only MinIO credentials with no literal credential values.

Do not assert or introduce a new PostgreSQL, Redis, NGINX, frontend, bot, or pgAdmin topology.

**Step 2: Make the minimal Compose changes**

Add `build: .` to the existing backend service so Compose can build it consistently. Replace list-form MinIO dependency with a health condition while retaining the current database dependency and `network_mode: host`.

Do not add required-value interpolation that would expose or echo secrets. Production preflight owns friendly validation.

**Step 3: Validate with synthetic environment values**

Create a temporary environment file outside the repository from synthetic values, then run:

```powershell
docker compose --env-file <temporary-file> -f docker-compose.yml config --quiet
```

Delete only that temporary file after validation. Never use or display the ignored production `.env`.

**Step 4: Commit**

```powershell
git add docker-compose.yml tests/test_production_config.py
git commit -m "build: health-gate production minio"
```

### Task 5: Protect Docker build contexts and make the frontend API origin explicit

**Backend files:**

- Create: `.dockerignore`
- Modify: `tests/test_production_config.py`

**Frontend files:**

- Create: `../pix_frontend_v2/.dockerignore`
- Modify: `../pix_frontend_v2/Dockerfile`
- Modify: `../pix_frontend_v2/scripts/check-api-url.mjs`

**Step 1: Add failing build-contract checks**

Backend tests must assert that `.dockerignore` excludes `.env`, `.env.*`, Git metadata, virtual environments, local database data, caches, bytecode, logs, coverage, and test/browser artifacts while allowing the two tracked example files.

Extend the frontend source guard to require:

- Dockerfile `ARG NEXT_PUBLIC_BACKEND_URL` before `npm run build`;
- build-time `ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL`;
- `.dockerignore` exclusion of `.env*`, `.git`, `.next`, `node_modules`, Playwright output, logs, and local artifacts;
- no hard-coded secret or credential-bearing API URL.

Run backend focused tests and `npm.cmd run check:api-url`; confirm failure before implementation.

**Step 2: Add both Docker ignore files**

Keep tracked `.env.example` and `.env.production.example` available only where explicitly required for documentation/tests; neither working `.env` nor `.env.local` may enter a build context.

**Step 3: Update the frontend Dockerfile**

Declare the public API build argument immediately before the build stage and export it for `next build`. Do not move any secret into `NEXT_PUBLIC_*` or change runtime routes/cookies.

**Step 4: Verify builds**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_production_config.py -v
Set-Location ..\pix_frontend_v2
npm.cmd run check:api-url
docker build --build-arg NEXT_PUBLIC_BACKEND_URL=https://pixlogistic.com/api_v1 -t pix-frontend:prod-check .
Set-Location ..\pix_backend
docker build -t pix-backend:prod-check .
```

Inspect build output and contexts for secret filenames; do not print file contents.

**Step 5: Commit each repository separately**

```powershell
git add .dockerignore tests/test_production_config.py
git commit -m "build: exclude secrets from backend image"

Set-Location ..\pix_frontend_v2
git add .dockerignore Dockerfile scripts/check-api-url.mjs
git commit -m "build: configure production API at image build"
Set-Location ..\pix_backend
```

### Task 6: Make automatic deployment non-destructive

**Files:**

- Modify: `.github/workflows/pipeline.yml`
- Modify: `tests/test_production_config.py`

**Step 1: Write a failing workflow safety test**

Read the workflow as text and assert that the deployed script:

- contains the base production preflight;
- runs Compose config validation;
- builds backend and MinIO;
- updates through `docker-compose up -d`;
- preserves the currently working `cicd/pix_backend` source path and `../../pix_backend` runtime path;
- contains no `alembic upgrade`, `alembic downgrade`, `docker-compose down`, `docker compose down`, `docker system prune`, or volume-removal command.

Run the focused test and confirm it fails against the current workflow.

**Step 2: Update only the remote command block**

Preserve the current SSH action, server host/user/password/port secret names, and both existing directories. The remote flow becomes:

1. pull source in `cicd/pix_backend`;
2. build `backend:latest` from that source;
3. run base preflight inside a disposable backend container using the existing runtime `.env` via `--env-file`, without printing it;
4. change to the existing `../../pix_backend` runtime directory;
5. run quiet Compose validation;
6. build MinIO;
7. run `docker-compose up -d` without first stopping the project.

Do not introduce migration, webhook, prune, or backup mutations into automatic CI.

**Step 3: Verify and commit**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_production_config.py -v
git diff --check
git add .github/workflows/pipeline.yml tests/test_production_config.py
git commit -m "ci: make production deploy non-destructive"
```

### Task 7: Publish the operator runbook

**Files:**

- Modify: `docs/LOCAL_DEVELOPMENT.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/SECURITY_NOTES.md`
- Modify: `README.md`

**Step 1: Update deployment documentation**

Document exact, separately copyable commands for:

- merging the new template keys while keeping the flag false;
- base preflight and quiet Compose validation;
- PostgreSQL backup/restore ownership and MinIO volume backup as one retention set;
- backend and pinned MinIO builds;
- MinIO health and disposable-object persistence smoke;
- migration history/current inspection and manual revision `c8f2a4e6d901` approval;
- order-chat preflight before enabling the flag;
- backend-only restart and liveness/API checks;
- webhook dry run and the separate approved `--apply` step;
- rollback by disabling the flag without migration downgrade or data deletion.

Explicitly state that even webhook dry run performs a live MoySklad list request and therefore is not run by local checks.

Update the architecture's deployment paragraph so it no longer claims automatic migration, Compose shutdown, or prune.

**Step 2: Review commands for destructive scope**

Every backup/restore/migration/webhook command must name its target and approval boundary. Do not include real hostnames beyond the public site origin, credentials, webhook secret, database password, Telegram IDs, or credential-bearing URLs.

**Step 3: Verify and commit**

```powershell
git diff --check
git add README.md docs/ARCHITECTURE.md docs/LOCAL_DEVELOPMENT.md docs/SECURITY_NOTES.md
git commit -m "docs: add safe production deployment runbook"
```

### Task 8: Final local verification

**Step 1: Run backend verification after the final edit**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
& ".\.venv\Scripts\python.exe" -m alembic history
docker compose --env-file <temporary-synthetic-file> -f docker-compose.yml config --quiet
git diff --check
```

Expected: Ruff and tests pass, Alembic has one head, Compose validates, and no migration is applied.

**Step 2: Run frontend verification after the final edit**

```powershell
Set-Location ..\pix_frontend_v2
npm.cmd run check
git diff --check
Set-Location ..\pix_backend
```

Expected: the API guard, unit tests, production build, and browser tests pass. Existing known lint warnings may remain; add none.

**Step 3: Rebuild production-check images if any Docker file changed after Task 5**

```powershell
docker build -t pix-backend:prod-check .
docker build --build-arg NEXT_PUBLIC_BACKEND_URL=https://pixlogistic.com/api_v1 -t pix-frontend:prod-check ..\pix_frontend_v2
```

Expected: both builds pass and no ignored environment file is copied.

**Step 4: Audit scope**

```powershell
git status --short
git log --oneline -10
```

Confirm that:

- no secret-bearing file is tracked;
- the feature remains disabled in the production template;
- no live integration call, migration, webhook mutation, production connection, Compose shutdown, prune, or volume deletion occurred;
- pre-existing tracked bytecode changes remain uncommitted and otherwise untouched.
