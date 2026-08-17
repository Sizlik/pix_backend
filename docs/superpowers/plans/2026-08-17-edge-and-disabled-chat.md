# Edge And Disabled Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore realtime notification WebSocket upgrades and prevent the frontend from starting order-chat traffic while the backend integration is disabled.

**Architecture:** NGINX receives one explicit notification WebSocket location alongside the existing chat socket. The Next.js bundle receives a separate public build flag and conditionally omits the order-chat component, while test builds deliberately enable it to preserve coverage of the enabled feature.

**Tech Stack:** NGINX, Next.js 14, TypeScript, Vitest, Playwright, Docker.

## Global Constraints

- Keep the ordinary `/api_v1/` HTTP proxy and existing chat WebSocket behavior unchanged.
- Do not place credentials in any `NEXT_PUBLIC_*` variable.
- Production order chat remains disabled; this plan does not enable its backend, scheduler, webhook, or MinIO flow.
- Preserve user changes in both repositories and commit backend and frontend files separately.
- Back up host-managed NGINX before production replacement and require `nginx -t` before reload.

---

### Task 1: Notification WebSocket proxy configuration

**Files:**
- Modify: `conf.d/default.conf`
- Create: `tests/test_nginx_config.py`

**Interfaces:**
- Consumes: backend WebSocket endpoint `/api_v1/notifications/ws`.
- Produces: NGINX HTTP/1.1 upgrade forwarding with the query string preserved by `proxy_pass`.

- [ ] **Step 1: Write a failing static proxy-contract test**

Create `tests/test_nginx_config.py`:

```python
from pathlib import Path


CONFIG = Path(__file__).parents[1] / "conf.d" / "default.conf"


def location_block(text: str, path: str) -> str:
    start = text.index(f"location {path} {{")
    end = text.index("\n    }", start)
    return text[start:end]


def test_notification_websocket_has_upgrade_proxy_before_generic_api_location():
    text = CONFIG.read_text(encoding="utf-8")
    block = location_block(text, "/api_v1/notifications/ws")

    assert text.index("location /api_v1/notifications/ws {") < text.index(
        "location /api_v1/ {"
    )
    assert "proxy_pass http://backend;" in block
    assert "proxy_http_version 1.1;" in block
    assert "proxy_set_header Upgrade $http_upgrade;" in block
    assert "proxy_set_header Connection $connection_upgrade;" in block
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in block
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_nginx_config.py -q
```

Expected: `ValueError` because the notification WebSocket location is absent.

- [ ] **Step 3: Add the explicit location before the generic API location**

Insert in `conf.d/default.conf`:

```nginx
    location /api_v1/notifications/ws {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
```

Do not redirect, rewrite, or remove the `auth` query parameter required by the endpoint.

- [ ] **Step 4: Run the static test and backend suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_nginx_config.py tests/test_notification_realtime.py tests/test_notifications_api.py -q
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: selected tests and the complete backend check pass.

- [ ] **Step 5: Commit the proxy contract**

```powershell
git add conf.d/default.conf tests/test_nginx_config.py
git commit -m "fix: proxy notification WebSocket upgrades"
```

### Task 2: Public order-chat build flag

**Files:**
- Create in frontend: `src/config/features.ts`
- Create in frontend: `src/config/features.test.ts`
- Modify in frontend: `src/app/dashboard/orders/[id]/page.tsx`
- Modify in frontend: `tests/global-setup.mjs`
- Modify in frontend: `Dockerfile`
- Modify in backend: `.env.production.example`
- Modify in backend: `tests/test_production_config.py`

**Interfaces:**
- Consumes: build-time `NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT`.
- Produces: `moyskladOrderChatEnabled: boolean` and no rendered `OrderChat` component when false.

- [ ] **Step 1: Write a failing flag parser test**

Create `src/config/features.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { publicFeatureEnabled } from "./features";

describe("publicFeatureEnabled", () => {
  it.each([
    [undefined, false],
    ["", false],
    ["false", false],
    ["TRUE", false],
    ["true", true],
  ])("maps %s to %s", (value, expected) => {
    expect(publicFeatureEnabled(value)).toBe(expected);
  });
});
```

- [ ] **Step 2: Run the unit test and verify RED**

```powershell
npm.cmd run test:unit -- src/config/features.test.ts
```

Expected: module resolution fails because `features.ts` is absent.

- [ ] **Step 3: Implement a strict public flag**

Create `src/config/features.ts`:

```typescript
export function publicFeatureEnabled(value: string | undefined): boolean {
  return value === "true";
}

export const moyskladOrderChatEnabled = publicFeatureEnabled(
  process.env.NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT,
);
```

In the order-detail page, import `moyskladOrderChatEnabled` and replace the unconditional component with:

```tsx
{moyskladOrderChatEnabled && <OrderChat orderId={params.id} />}
```

Because the component is not mounted when false, its history effect and WebSocket effect cannot start.

- [ ] **Step 4: Preserve enabled-feature E2E coverage**

In `tests/global-setup.mjs`, set the flag before importing Next:

```javascript
process.env.NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT = "true";
```

The existing `tests/order-chat.spec.ts` remains unchanged and must still prove the enabled path.

- [ ] **Step 5: Add the Docker build input with a safe default**

In the frontend `Dockerfile`, beside the backend URL build argument, add:

```dockerfile
ARG NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT=false
ENV NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT=${NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT}
```

In backend `.env.production.example`, add:

```dotenv
NEXT_PUBLIC_ENABLE_MOYSKLAD_ORDER_CHAT=false
```

Update `tests/test_production_config.py` so its exact environment inventory expects this key and value.

- [ ] **Step 6: Run focused frontend tests**

```powershell
npm.cmd run test:unit -- src/config/features.test.ts
npx.cmd playwright test tests/order-chat.spec.ts tests/order-changes.spec.ts
```

Expected: the strict parser passes and the deliberately enabled test build still exercises order chat.

- [ ] **Step 7: Commit each repository intentionally**

From the frontend repository:

```powershell
git add Dockerfile src/config/features.ts src/config/features.test.ts src/app/dashboard/orders/[id]/page.tsx tests/global-setup.mjs
git commit -m "fix: hide disabled MoySklad order chat"
```

From the backend repository:

```powershell
git add .env.production.example tests/test_production_config.py
git commit -m "docs: declare frontend order chat build flag"
```

### Task 3: Cross-repository verification

**Files:**
- No new files

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: verified backend proxy configuration and frontend image inputs.

- [ ] **Step 1: Run backend verification after the final backend edit**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
git diff --check
```

Expected: full backend verification passes with no whitespace errors.

- [ ] **Step 2: Run frontend verification after the final frontend edit**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
git diff --check
```

Expected: lint completes with no new errors, API URL check passes, unit tests pass, production build passes with the safe default, and all Playwright tests pass with chat enabled by test setup.

- [ ] **Step 3: Review repository boundaries**

In each repository run:

```powershell
git status --short
git log -3 --oneline
```

Confirm the frontend commit contains no backend file, the backend commits contain no frontend artifact, and no `.env`, `.next`, `node_modules`, token, or production data was added.
