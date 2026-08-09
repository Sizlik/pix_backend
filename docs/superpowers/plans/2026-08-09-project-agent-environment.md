# Project Agent Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Pix Logistic backend and frontend reproducibly runnable and verifiable on a local Windows workstation, while giving Codex accurate repository guidance and removing credential-bearing configuration from source and Git remotes.

**Architecture:** Keep FastAPI and Next.js running directly on the host and use Docker Compose only for PostgreSQL and Redis. Add a typed backend settings boundary and lazy external-service initialization so imports are offline-safe, then expose stable PowerShell setup/run/check entry points that both humans and Codex Desktop actions can use.

**Tech Stack:** Python 3.11, FastAPI 0.104.1, Pydantic 2.5.3, pydantic-settings, SQLAlchemy 2, PostgreSQL, Redis, pytest, Ruff, Next.js 14.1, React 18, TypeScript 5, npm, Playwright, PowerShell, Docker Compose.

## Global Constraints

- Create a separate root `AGENTS.md` in `pix_backend` and `pix_frontend_v2`.
- Run FastAPI and Next.js on the Windows host; run only PostgreSQL and Redis through the local Compose file.
- Do not apply Alembic migrations automatically.
- Do not require or contact production integrations during import, setup, tests, or ordinary local startup.
- Do not print, copy, commit, or document any credential value.
- Do not rewrite Git history or revoke credentials automatically.
- Use npm and `package-lock.json` as the supported frontend package manager and lockfile.
- Preserve existing business API contracts except for the new liveness route and sanitized missing-integration `503` responses.
- Keep `MOYSKLAD_PASWORD` only as a temporary input alias; use `MOYSKLAD_PASSWORD` everywhere else.
- Production environment documentation must list names, purpose, requirement level, and format, but no production values.

---

## File Structure

Backend additions and responsibilities:

- `config.py`: typed environment settings and integration-value guards.
- `errors.py`: project exception for an unconfigured external integration.
- `tests/test_config.py`: settings parsing, production safety, and legacy alias tests.
- `tests/test_app.py`: offline import, liveness, and HTTP 503 mapping tests.
- `requirements-dev.txt`: pinned test and lint dependencies.
- `pyproject.toml`: pytest and Ruff configuration.
- `scripts/setup-local.ps1`: create/populate `.venv` and seed `.env` safely.
- `scripts/start-services.ps1`: start local PostgreSQL and Redis.
- `scripts/run-local.ps1`: start Uvicorn from `.venv`.
- `scripts/check.ps1`: run the scoped Ruff baseline and pytest.
- `AGENTS.md`, `README.md`, and `docs/*.md`: durable agent and developer context.

Backend modifications:

- `main.py`: application factory, liveness endpoint, error handler, CORS, guarded scheduler.
- `db/postgres.py`, `db/redis.py`, `db/repository.py`: consume typed settings without network I/O at import.
- `bot/sender.py`: construct the Telegram client lazily.
- `manager/moysklad.py`, `manager/bitrix.py`, `manager/privoz_order.py`, `manager/users.py`: remove embedded/import-time configuration and require integration values at call time.
- `moysklad_webhooks_creator.py`: consume the canonical MoySklad password setting.
- `.env.example`, `.gitignore`, `local-docker-compose.yml`, `requirements.txt`: reproducible local configuration.

Frontend additions and responsibilities:

- `src/config/api.ts`: one normalized backend URL and `backendUrl(path)` helper.
- `scripts/check-api-url.mjs`: prevent reintroduction of the production API literal.
- `tests/public-page.spec.ts`, `playwright.config.ts`: browser smoke baseline.
- `scripts/setup-local.ps1`, `scripts/run-local.ps1`, `scripts/check.ps1`: stable Windows commands.
- `.env.example`, `AGENTS.md`, `README.md`: environment and agent guidance.

Frontend modifications:

- `src/routes/routes.tsx`, `src/components/fileOrderGrid/fileOrder.js`, `src/app/telegram/[telegram_id]/page.jsx`: use `backendUrl`.
- `package.json`, `package-lock.json`, `.gitignore`: Playwright/check scripts and generated-artifact exclusions.

---

### Task 1: Add typed backend settings and the test/lint harness

**Files:**
- Create: `config.py`
- Create: `errors.py`
- Create: `tests/test_config.py`
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `Settings`, `get_settings() -> Settings`, `require_value(value, integration) -> str`, `require_secret(value, integration) -> str`, and `IntegrationNotConfigured(integration)`.
- Consumes: existing environment variable names plus the new names defined in the design spec.

- [ ] **Step 1: Add the failing settings tests**

Create `tests/test_config.py` with concrete expectations:

```python
import pytest
from pydantic import ValidationError

from config import Settings, require_value
from errors import IntegrationNotConfigured


def test_local_settings_have_offline_safe_defaults():
    settings = Settings(_env_file=None)
    assert settings.app_env == "local"
    assert settings.enable_scheduler is False
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.redis_url == "redis://localhost:6379/0"


def test_legacy_moysklad_password_alias(monkeypatch):
    monkeypatch.delenv("MOYSKLAD_PASSWORD", raising=False)
    monkeypatch.setenv("MOYSKLAD_PASWORD", "legacy-value")
    settings = Settings(_env_file=None)
    assert settings.moysklad_password is not None
    assert settings.moysklad_password.get_secret_value() == "legacy-value"


def test_production_rejects_local_auth_secrets(monkeypatch):
    monkeypatch.delenv("VERIFICATION_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("RESET_PASSWORD_TOKEN_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production")


def test_missing_integration_value_is_sanitized():
    with pytest.raises(IntegrationNotConfigured, match="moysklad is not configured"):
        require_value(None, "moysklad")
```

- [ ] **Step 2: Run the focused test and verify the missing-module failure**

Run:

```powershell
python -m pytest tests/test_config.py -q
```

Expected: collection fails because `config.py` and `errors.py` do not exist.

- [ ] **Step 3: Add pinned settings/test dependencies and tool configuration**

Append `pydantic-settings==2.1.0` to `requirements.txt`. Create `requirements-dev.txt`:

```text
-r requirements.txt
httpx==0.27.2
pytest==8.3.5
pytest-asyncio==0.25.3
ruff==0.9.10
```

Create `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I"]
```

- [ ] **Step 4: Implement the settings and configuration error**

Create `errors.py`:

```python
class IntegrationNotConfigured(RuntimeError):
    def __init__(self, integration: str) -> None:
        self.integration = integration
        super().__init__(f"{integration} is not configured")
```

Create `config.py` around this exact public shape:

```python
from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from errors import IntegrationNotConfigured

LOCAL_VERIFICATION_SECRET = "local-verification-secret"
LOCAL_RESET_SECRET = "local-reset-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: Literal["local", "test", "production"] = "local"
    postgres_driver: str = "postgresql+asyncpg"
    postgres_user: str = "pix"
    postgres_password: SecretStr = SecretStr("pix_local")
    postgres_db: str = "pix"
    postgres_host: str = "localhost"
    db_port: int = 5431
    redis_url: str = "redis://localhost:6379/0"
    token_lifetime: int = 3600
    verification_token_secret: SecretStr = SecretStr(LOCAL_VERIFICATION_SECRET)
    reset_password_token_secret: SecretStr = SecretStr(LOCAL_RESET_SECRET)
    cors_origins: list[str] = ["http://localhost:3000"]
    enable_scheduler: bool = False

    bot_token: SecretStr | None = None
    chat_id: int | None = None
    help_chat_id: int | None = None
    bitrix_link: SecretStr | None = None
    moysklad_login: str | None = None
    moysklad_password: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("MOYSKLAD_PASSWORD", "MOYSKLAD_PASWORD"),
    )
    privoz_username: str | None = None
    privoz_password: SecretStr | None = None
    mailersend_token: SecretStr | None = None

    @property
    def database_url(self) -> str:
        password = quote_plus(self.postgres_password.get_secret_value())
        return (
            f"{self.postgres_driver}://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.db_port}/{self.postgres_db}"
        )

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env == "production":
            if self.postgres_password.get_secret_value() == "pix_local":
                raise ValueError("POSTGRES_PASSWORD must be set in production")
            if self.verification_token_secret.get_secret_value() == LOCAL_VERIFICATION_SECRET:
                raise ValueError("VERIFICATION_TOKEN_SECRET must be set in production")
            if self.reset_password_token_secret.get_secret_value() == LOCAL_RESET_SECRET:
                raise ValueError("RESET_PASSWORD_TOKEN_SECRET must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def require_value(value: str | None, integration: str) -> str:
    if value is None or not value.strip():
        raise IntegrationNotConfigured(integration)
    return value


def require_secret(value: SecretStr | None, integration: str) -> str:
    if value is None or not value.get_secret_value():
        raise IntegrationNotConfigured(integration)
    return value.get_secret_value()
```

- [ ] **Step 5: Install the development dependencies and run the tests**

Run:

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pytest tests/test_config.py -q
& .\.venv\Scripts\python.exe -m ruff check config.py errors.py tests/test_config.py
```

Expected: all four tests pass and Ruff exits 0.

- [ ] **Step 6: Commit the settings boundary**

```powershell
git add config.py errors.py tests/test_config.py requirements.txt requirements-dev.txt pyproject.toml
git commit -m "feat: centralize backend settings"
```

---

### Task 2: Make backend imports offline-safe and add liveness/error handling

**Files:**
- Create: `tests/test_app.py`
- Modify: `main.py`
- Modify: `db/postgres.py`
- Modify: `db/redis.py`
- Modify: `db/repository.py`
- Modify: `bot/sender.py`
- Modify: `manager/moysklad.py`
- Modify: `manager/bitrix.py`
- Modify: `manager/privoz_order.py`
- Modify: `manager/users.py`
- Modify: `moysklad_webhooks_creator.py`

**Interfaces:**
- Consumes: `get_settings`, `require_value`, `require_secret`, `IntegrationNotConfigured` from Task 1.
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`, `GET /api_v1/health`, lazy `Sender._bot()`, and `MoySkladRepository.get_default_company()`.

- [ ] **Step 1: Add failing application tests before refactoring imports**

Create `tests/test_app.py`:

```python
import importlib

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import Settings
from errors import IntegrationNotConfigured


def test_import_does_not_call_external_http(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("external HTTP was called during import")

    monkeypatch.setattr(requests, "get", fail)
    monkeypatch.setattr(requests, "post", fail)
    module = importlib.import_module("main")
    assert isinstance(module.app, FastAPI)


def test_health_is_offline_and_stable():
    from main import create_app

    app = create_app(Settings(_env_file=None, app_env="test"))
    with TestClient(app) as client:
        response = client.get("/api_v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_integration_configuration_error_maps_to_503():
    from main import create_app

    app = create_app(Settings(_env_file=None, app_env="test"))

    @app.get("/_integration-test")
    async def integration_test():
        raise IntegrationNotConfigured("moysklad")

    with TestClient(app) as client:
        response = client.get("/_integration-test")
    assert response.status_code == 503
    assert response.json() == {"detail": "moysklad is not configured"}
```

- [ ] **Step 2: Run the application tests and capture the import-time failure**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_app.py -q
```

Expected: failure caused by import-time MoySklad or Telegram initialization and missing `create_app`/health behavior.

- [ ] **Step 3: Route database and Redis configuration through `Settings`**

In `db/postgres.py`, replace individual `os.getenv` reads with:

```python
from config import get_settings

settings = get_settings()
DATABASE_URL = settings.database_url
engine = create_async_engine(DATABASE_URL)
```

In `db/redis.py`, create the client from `settings.redis_url` and pass the integer `settings.token_lifetime` to `RedisStrategy`.

- [ ] **Step 4: Make MoySklad configuration instance-based and lazy**

Change `MoySkladRepository` so credentials are resolved only when a method is called:

```python
class MoySkladRepository(AbstractRepository):
    model = None
    base_url = "https://api.moysklad.ru/api/remap/1.2/"

    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def _headers(self) -> dict[str, str]:
        login = require_value(self.settings.moysklad_login, "moysklad")
        password = require_secret(self.settings.moysklad_password, "moysklad")
        encoded = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("utf-8")
        return {"Authorization": f"Basic {encoded}"}

    async def get_default_company(self) -> dict:
        response = requests.get(
            f"{self.base_url}context/usersettings",
            headers=self._headers(),
        ).json()
        return response["defaultCompany"]
```

Use `self._headers()` in every existing request method. Remove `set_organization()` and the module-global `organization` from `manager/moysklad.py`. In `CustomerOrderManager.create_order`, `CustomerOrderManager.create_order_by_request`, and `PaymentInManager.create_payment_in`, call `await self.__repo.get_default_company()` immediately before constructing the outgoing payload.

- [ ] **Step 5: Make Telegram, Bitrix, Privoz, and email clients lazy**

Refactor `Sender` to keep no class-level bot:

```python
class Sender:
    def __init__(self, settings_provider=get_settings):
        self._settings_provider = settings_provider
        self._bot_client = None

    def _bot(self) -> Bot:
        if self._bot_client is None:
            token = require_secret(self._settings_provider().bot_token, "telegram")
            self._bot_client = Bot(token, parse_mode=ParseMode.HTML)
        return self._bot_client
```

Each send method calls `bot = self._bot()` and then `await bot.send_message(...)`; group/help IDs come from settings and are validated with `require_value(str(value) if value is not None else None, "telegram")`. Replace the hard-coded recipient in `accept_transaction_message` with configured `CHAT_ID`.

In `manager/bitrix.py`, remove the credential-bearing fallback URL and resolve `BITRIX_LINK` inside `BitrixABC.__init__`. In `manager/privoz_order.py`, resolve `PRIVOZ_USERNAME` and `PRIVOZ_PASSWORD` at the beginning of `parse_privoz`. In `manager/users.py`, read auth secrets from `get_settings()` when constructing `UserManager`, and read `MAILERSEND_TOKEN` immediately before sending mail. Update `moysklad_webhooks_creator.py` to use `get_settings().moysklad_password`.

- [ ] **Step 6: Introduce an application factory, liveness route, and guarded startup**

Refactor `main.py` to this structure:

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    application = FastAPI()
    api_router = APIRouter(prefix="/api_v1")

    api_router.include_router(router_users)
    api_router.include_router(router_bot)
    api_router.include_router(router_payment)
    api_router.include_router(router_bitrix)
    api_router.include_router(router_orders)
    api_router.include_router(router_chat)
    api_router.include_router(router_notifications)
    api_router.include_router(router_organizations)

    @api_router.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    @application.exception_handler(IntegrationNotConfigured)
    async def integration_not_configured_handler(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    application.include_router(api_router)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.on_event("startup")
    async def startup():
        FastAPICache.init(get_redis_backend(), prefix="fastapi-cache")
        if settings.enable_scheduler:
            scheduler = AsyncIOScheduler()
            scheduler.add_job(change_states_on_moysklad, "interval", hours=1)
            scheduler.start()
            application.state.scheduler = scheduler

    return application


app = create_app()
```

Remove the root router self-include and unused `os.environ` import. Retain existing `/api_v1/` and `/api_v1/hello/{name}` routes inside the factory only if they are documented as compatibility endpoints.

- [ ] **Step 7: Run offline import, app tests, and the scoped lint baseline**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_app.py -q
& .\.venv\Scripts\python.exe -m ruff check config.py errors.py main.py db/postgres.py db/redis.py db/repository.py bot/sender.py tests
```

Expected: all tests pass, no request is made during import, and Ruff exits 0 for the configuration boundary and touched infrastructure files.

- [ ] **Step 8: Commit the offline-safe application boundary**

```powershell
git add main.py db/postgres.py db/redis.py db/repository.py bot/sender.py manager/moysklad.py manager/bitrix.py manager/privoz_order.py manager/users.py moysklad_webhooks_creator.py tests/test_app.py
git commit -m "refactor: make integrations lazy for local startup"
```

---

### Task 3: Add the backend local environment entry points

**Files:**
- Create: `scripts/setup-local.ps1`
- Create: `scripts/start-services.ps1`
- Create: `scripts/run-local.ps1`
- Create: `scripts/check.ps1`
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `local-docker-compose.yml`

**Interfaces:**
- Consumes: Task 1 requirements/tool configuration and Task 2 `main:app`.
- Produces: four stable Windows commands referenced by README, `AGENTS.md`, and Codex Desktop actions.

- [ ] **Step 1: Add complete, secret-free local environment defaults**

Replace `.env.example` with grouped values using this shape:

```dotenv
APP_ENV=local
POSTGRES_DRIVER=postgresql+asyncpg
POSTGRES_USER=pix
POSTGRES_PASSWORD=pix_local
POSTGRES_DB=pix
POSTGRES_HOST=localhost
DB_PORT=5431
REDIS_URL=redis://localhost:6379/0
TOKEN_LIFETIME=3600
VERIFICATION_TOKEN_SECRET=local-verification-secret
RESET_PASSWORD_TOKEN_SECRET=local-reset-secret
CORS_ORIGINS=["http://localhost:3000"]
ENABLE_SCHEDULER=false

BOT_TOKEN=
CHAT_ID=
HELP_CHAT_ID=
BITRIX_LINK=
MOYSKLAD_LOGIN=
MOYSKLAD_PASSWORD=
PRIVOZ_USERNAME=
PRIVOZ_PASSWORD=
MAILERSEND_TOKEN=

PGADMIN_DEFAULT_EMAIL=admin@example.test
PGADMIN_DEFAULT_PASSWORD=pgadmin_local
```

Do not add `MOYSKLAD_PASWORD` to the new template; it remains an input compatibility alias only.

- [ ] **Step 2: Harden ignored local/generated paths**

Ensure backend `.gitignore` includes:

```gitignore
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
htmlcov/
.coverage
db_data/
downloaded/
test.json
playwright-report/
test-results/
.codex-log/
.idea/
```

- [ ] **Step 3: Make the local Compose file explicit and health-checkable**

Keep only PostgreSQL and Redis in `local-docker-compose.yml`, pin the major images, add named volumes, and add health checks:

```yaml
services:
  database:
    image: postgres:16
    ports:
      - "5431:5432"
    env_file:
      - .env
    volumes:
      - pix-postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7
    ports:
      - "6379:6379"
    volumes:
      - pix-redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pix-postgres-data:
  pix-redis-data:
```

- [ ] **Step 4: Add idempotent PowerShell entry points**

Create `scripts/setup-local.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}
```

Create `scripts/start-services.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
docker compose -f local-docker-compose.yml up -d
```

Create `scripts/run-local.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
& ".\.venv\Scripts\python.exe" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Create `scripts/check.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
& ".\.venv\Scripts\python.exe" -m ruff check config.py errors.py main.py db/postgres.py db/redis.py db/repository.py bot/sender.py tests
& ".\.venv\Scripts\python.exe" -m pytest tests -q
```

- [ ] **Step 5: Execute the scripts and verify local infrastructure**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-services.ps1
docker compose -f local-docker-compose.yml ps
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: `.env` exists but is ignored, PostgreSQL and Redis become healthy, and checks exit 0. Do not run `alembic upgrade head` in this task.

- [ ] **Step 6: Commit backend local tooling**

```powershell
git add .env.example .gitignore local-docker-compose.yml scripts
git commit -m "chore: add backend local workflow"
```

---

### Task 4: Move frontend API configuration to the environment and add Playwright

**Files:**
- Create: `src/config/api.ts`
- Create: `scripts/check-api-url.mjs`
- Create: `tests/public-page.spec.ts`
- Create: `playwright.config.ts`
- Create: `.env.example`
- Create: `scripts/setup-local.ps1`
- Create: `scripts/run-local.ps1`
- Create: `scripts/check.ps1`
- Modify: `src/routes/routes.tsx`
- Modify: `src/components/fileOrderGrid/fileOrder.js`
- Modify: `src/app/telegram/[telegram_id]/page.jsx`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `BACKEND_URL: string`, `backendUrl(path: string) -> string`, `npm run check`, and a public-page Playwright smoke test.
- Consumes: `NEXT_PUBLIC_BACKEND_URL`, defaulting locally to `http://localhost:8000/api_v1`.

- [ ] **Step 1: Add a failing source guard and Playwright smoke test**

Create `scripts/check-api-url.mjs`:

```javascript
import { readFile } from "node:fs/promises";

const files = [
  "src/routes/routes.tsx",
  "src/components/fileOrderGrid/fileOrder.js",
  "src/app/telegram/[telegram_id]/page.jsx",
];
const forbidden = "https://pixlogistic.com/api_v1";

for (const file of files) {
  const source = await readFile(file, "utf8");
  if (source.includes(forbidden)) {
    throw new Error(`${file} contains the production API URL`);
  }
}
```

Create `tests/public-page.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";

test("public authentication page renders", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/PIX Logistic/i);
  await expect(page.getByRole("heading", { name: "PIX Logistic" })).toBeVisible();
});
```

- [ ] **Step 2: Run the source guard and verify it fails on current literals**

Run:

```powershell
node .\scripts\check-api-url.mjs
```

Expected: non-zero exit naming `src/routes/routes.tsx` as the first offending file.

- [ ] **Step 3: Add the centralized frontend URL helper**

Create `src/config/api.ts`:

```typescript
const LOCAL_BACKEND_URL = "http://localhost:8000/api_v1";

export const BACKEND_URL = (
  process.env.NEXT_PUBLIC_BACKEND_URL ?? LOCAL_BACKEND_URL
).replace(/\/+$/, "");

export function backendUrl(path: string): string {
  return `${BACKEND_URL}/${path.replace(/^\/+/, "")}`;
}
```

Replace all three active `BACKEND_URL` declarations with imports from `@/config/api`. Convert every template expression from ```${BACKEND_URL}/path``` to `backendUrl("path")`; preserve dynamic segments with expressions such as `backendUrl(`orders/${order_id}`)`.

- [ ] **Step 4: Add Playwright and the unified npm check command**

Run:

```powershell
npm.cmd install --save-dev @playwright/test
```

Add scripts to `package.json`:

```json
"check:api-url": "node scripts/check-api-url.mjs",
"test:e2e": "playwright test",
"check": "npm run lint && npm run check:api-url && npm run build && npm run test:e2e"
```

Create `playwright.config.ts`:

```typescript
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm.cmd run dev",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
```

- [ ] **Step 5: Add frontend environment and PowerShell entry points**

Create `.env.example`:

```dotenv
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000/api_v1
```

Create `scripts/setup-local.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
npm.cmd ci
if (-not (Test-Path ".env.local")) {
    Copy-Item ".env.example" ".env.local"
}
npx.cmd playwright install chromium
```

Create `scripts/run-local.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
npm.cmd run dev
```

Create `scripts/check.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
npm.cmd run check
```

Add these ignore entries:

```gitignore
/playwright-report/
/test-results/
/.codex-log/
```

- [ ] **Step 6: Run frontend checks**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
node .\scripts\check-api-url.mjs
npm.cmd run lint
npm.cmd run build
npm.cmd run test:e2e
```

Expected: the source guard, lint, build, and Chromium smoke test pass. If the existing codebase has pre-existing lint/build errors, record exact failures, fix only errors caused by the touched files or required for the agreed baseline, and document remaining unrelated debt.

- [ ] **Step 7: Commit frontend environment and checks**

```powershell
git add .env.example .gitignore package.json package-lock.json playwright.config.ts scripts tests src/config/api.ts src/routes/routes.tsx src/components/fileOrderGrid/fileOrder.js "src/app/telegram/[telegram_id]/page.jsx"
git commit -m "chore: add frontend local workflow"
```

---

### Task 5: Write backend project guidance and shared architecture documentation

**Files:**
- Create: `AGENTS.md`
- Create: `README.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/LOCAL_DEVELOPMENT.md`
- Create: `docs/ENVIRONMENT.md`
- Create: `docs/SECURITY_NOTES.md`

**Interfaces:**
- Consumes: the final commands and configuration names from Tasks 1–4.
- Produces: the backend repository instruction source and the shared documentation source of truth.

- [ ] **Step 1: Write a concise backend `AGENTS.md`**

Use these exact top-level sections and keep the file under 120 lines:

```markdown
# Pix Backend Agent Guide

## Purpose and Scope
## Architecture Boundaries
## Local Setup and Commands
## Verification Matrix
## Database and Migration Safety
## External Integrations and Secrets
## Cross-Repository Contract
## Source-of-Truth Documentation
```

Include the four PowerShell entry points, the manual Alembic rule, the no-production-network rule, the `MOYSKLAD_PASSWORD` canonical name, and a requirement to run backend checks after Python/config changes.

- [ ] **Step 2: Replace the missing backend README with a verified quick start**

Document this command order:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-services.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
```

Link architecture, environment, security, and local-development docs. State that Swagger is at `http://127.0.0.1:8000/docs` and liveness is at `http://127.0.0.1:8000/api_v1/health`.

- [ ] **Step 3: Document architecture from inspected code**

`docs/ARCHITECTURE.md` must contain:

- a two-repository system context;
- route → dependency → manager → repository flow;
- PostgreSQL model inventory and Redis responsibilities;
- MoySklad, Bitrix, Privoz, Telegram, email, and currency-rate integrations;
- REST and WebSocket flows;
- scheduler flow and its `ENABLE_SCHEDULER` gate;
- production Docker/NGINX/GitHub Actions topology;
- a route-group table and the current technical-debt inventory from the design spec.

- [ ] **Step 4: Document local development and production environment inventory**

`docs/LOCAL_DEVELOPMENT.md` must include prerequisites, first setup, startup/shutdown, checks, liveness, troubleshooting for `npm.ps1`, Docker health, missing integrations, and deliberate Alembic commands. `docs/ENVIRONMENT.md` must include a table with columns `Variable`, `Scope`, `Required in production`, `Secret`, `Format`, and `Purpose` for every setting in `Settings`, `NEXT_PUBLIC_BACKEND_URL`, `PGADMIN_DEFAULT_EMAIL`, and `PGADMIN_DEFAULT_PASSWORD`.

Explicitly state that `NEXT_PUBLIC_BACKEND_URL` is embedded during the frontend build and that production must use `https://pixlogistic.com/api_v1`. Do not include any other production value.

- [ ] **Step 5: Record credential rotation and security boundaries without values**

`docs/SECURITY_NOTES.md` must name the affected categories and locations, require rotation for Bitrix, Privoz, and both Git credentials, explain that working-tree removal does not invalidate prior exposure, and forbid storing secrets in `AGENTS.md`, README, committed env files, logs, or frontend `NEXT_PUBLIC_*` variables.

- [ ] **Step 6: Validate commands, links, placeholders, and secret absence**

Run:

```powershell
rg -n -i "TBD|TODO|fill in|implement later" AGENTS.md README.md docs
rg -n "MOYSKLAD_PASWORD" AGENTS.md README.md docs
git diff --check
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: placeholder scan is empty; the legacy name appears only in an explicit deprecation note; diff check and backend checks pass.

- [ ] **Step 7: Commit backend guidance and shared docs**

```powershell
git add AGENTS.md README.md docs/ARCHITECTURE.md docs/LOCAL_DEVELOPMENT.md docs/ENVIRONMENT.md docs/SECURITY_NOTES.md
git commit -m "docs: add backend agent and architecture guide"
```

---

### Task 6: Write frontend repository guidance

**Files:**
- Create: `AGENTS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `backendUrl`, npm scripts, Playwright configuration, and backend docs from Tasks 4–5.
- Produces: the frontend repository instruction source and developer entry point.

- [ ] **Step 1: Write the frontend `AGENTS.md`**

Use these exact sections and keep the file under 100 lines:

```markdown
# Pix Frontend Agent Guide

## Purpose and Scope
## App Router Structure
## API and Authentication Boundary
## Local Setup and Commands
## Verification Matrix
## Environment and Secret Rules
## Backend Contract
```

Require npm, `package-lock.json`, `backendUrl`, `NEXT_PUBLIC_BACKEND_URL`, and `npm.cmd run check`. Warn that token/user cookies and WebSocket behavior cross the backend contract.

- [ ] **Step 2: Replace the generated Next.js README**

Document Python-independent prerequisites with Node.js 20 LTS recommended, setup/run/check scripts, `.env.local`, page structure, API-client location, Playwright behavior, and links to the shared backend architecture/environment docs using the adjacent checkout path `../pix_backend/docs/...`.

- [ ] **Step 3: Validate frontend guidance and full checks**

Run:

```powershell
rg -n -i "TBD|TODO|fill in|implement later" AGENTS.md README.md
git diff --check
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: placeholder scan is empty, diff check is clean, and frontend checks pass.

- [ ] **Step 4: Commit frontend guidance**

```powershell
git add AGENTS.md README.md
git commit -m "docs: add frontend agent guide"
```

---

### Task 7: Install Codex skills, register actions, and remove credential-bearing remotes

**Files/State:**
- Install outside repositories: `~/.codex/skills/security-best-practices`, `~/.codex/skills/security-threat-model`, `~/.codex/skills/playwright`
- Update backend Git remote: `https://github.com/Sizlik/pix_backend`
- Update frontend Git remote: `https://github.com/Sizlik/pix_frontend_v2`
- Update Codex Desktop local environment actions for both saved projects

**Interfaces:**
- Consumes: stable setup/run/check scripts from Tasks 3–4.
- Produces: three user-level skills, sanitized remotes, and clickable Codex actions.

- [ ] **Step 1: Install the three curated skills with the official installer**

Run:

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" --repo openai/skills --path skills/.curated/security-best-practices skills/.curated/security-threat-model skills/.curated/playwright
```

Expected: all three destination directories are created. Report that newly installed skills become available on the next turn.

- [ ] **Step 2: Verify installation without reading unrelated personal data**

Run the official curated listing script with `--format json` and confirm the three names report `installed: true`.

- [ ] **Step 3: Sanitize both local Git remotes**

Run in backend:

```powershell
git remote set-url origin https://github.com/Sizlik/pix_backend
```

Run in frontend:

```powershell
git remote set-url origin https://github.com/Sizlik/pix_frontend_v2
```

Verify in each repository without printing a URL:

```powershell
$remote = git remote get-url origin
if ($remote -match '^https://[^/]+@') { throw "origin still contains embedded credentials" }
```

- [ ] **Step 4: Register Codex Desktop setup/run/check actions**

Use Codex Desktop Settings → Local environments for each saved repository. Bind these commands:

Backend:

```text
Setup: powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
Run: powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
Check: powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
Services: powershell -ExecutionPolicy Bypass -File .\scripts\start-services.ps1
```

Frontend:

```text
Setup: powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
Run: powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1
Check: powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Save the generated project configuration through the app's supported local-environment flow. If the app writes shareable files into a repository `.codex` directory, inspect them for absolute paths or secrets before staging them.

- [ ] **Step 5: Confirm the security handoff**

Report, without values, that Git, Bitrix, and Privoz credentials observed in source/configuration must be rotated manually. Do not test old credentials and do not perform revocation.

---

### Task 8: Run the complete local verification and audit repository state

**Files:**
- Modify only files required to correct failures introduced by Tasks 1–7.

**Interfaces:**
- Consumes: both repositories' setup/check scripts and all acceptance criteria.
- Produces: evidence-backed completion report with production env inventory link and any remaining external blocker.

- [ ] **Step 1: Run backend verification from a fresh process**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-services.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
& .\.venv\Scripts\python.exe -c "import main; print(main.app.title)"
```

Expected: dependencies are idempotently installed, PostgreSQL/Redis are healthy, checks pass, and importing `main` makes no external integration request.

- [ ] **Step 2: Run frontend verification from the supported lockfile**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: npm lockfile installation, source guard, lint, build, and Playwright smoke test pass.

- [ ] **Step 3: Audit ignored/generated/secret files**

In both repositories run:

```powershell
git status --short
git diff --check
```

In backend, run structural scans that do not reproduce secret values:

```powershell
rg -n 'os\.getenv\("BITRIX_LINK",\s*"https://' manager\bitrix.py
rg -n 'data=\{"username":\s*"[^"]+",\s*"password":' manager\privoz_order.py
git status --short --ignored | rg '(^|/)(\.env|\.venv|node_modules|\.next|playwright-report|test-results|db_data)(/|$)'
```

In frontend, run:

```powershell
rg -n 'https://pixlogistic\.com/api_v1' src
git status --short --ignored | rg '(^|/)(\.env|\.venv|node_modules|\.next|playwright-report|test-results|db_data)(/|$)'
```

Expected: credential-structure and production-API scans return no active source matches; ignored generated paths may be listed only with `!!` status and never staged.

- [ ] **Step 4: Verify production environment documentation against code**

Compare all fields in `Settings`, frontend `NEXT_PUBLIC_BACKEND_URL`, and production Compose variables against `docs/ENVIRONMENT.md`. Expected: every consumed variable appears exactly once in the inventory, and the inventory contains no secret value.

- [ ] **Step 5: Commit any verification-only correction separately**

If verification required a correction, stage only that correction and commit with:

```powershell
git commit -m "fix: complete local environment verification"
```

If no correction was required, do not create an empty commit.

- [ ] **Step 6: Produce the final handoff**

Report:

- backend and frontend commands executed and their exit results;
- installed skill names and next-turn availability;
- links to both `AGENTS.md`, architecture, local development, environment, and security notes;
- the production environment inventory location;
- the manual credential-rotation requirement;
- any test that could not run and its exact external blocker.
