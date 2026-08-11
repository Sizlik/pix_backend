# Order Currency Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display every customer-order total, unit price, and line total with the ISO currency code configured on that MoySklad order.

**Architecture:** `CustomerOrderManager` expands `rate.currency` and enriches each raw MoySklad order with the application-owned optional field `currency_code`. A pure frontend formatter renders display-unit amounts with that code, while the personal list, organization list, and order detail keep using their existing data-loading flows.

**Tech Stack:** Python 3.11, FastAPI manager layer, pytest/pytest-asyncio, Next.js 14, TypeScript, React, AG Grid, Vitest.

## Global Constraints

- MoySklad is the source of truth for both the numeric amount and document currency.
- Do not convert between currencies; continue dividing MoySklad monetary values by 100 for display units.
- Display currency as an ISO 4217 code, for example `1 250,00 USD`.
- Never assume a fallback currency when `rate.currency.isoCode` is absent or malformed.
- Preserve every existing raw MoySklad response field and public API path.
- Do not change order creation, order editing payloads, payments, transactions, balances, exchange rates, exports, or MoySklad configuration.
- Run backend and frontend verification after the final edit; earlier runs are not completion evidence.

---

## File Map

- Modify `manager/moysklad.py`: request expanded order currencies and add `currency_code` at the manager boundary.
- Create `tests/test_order_currency.py`: isolate query composition and enrichment behavior with a recording repository.
- Modify `../pix_frontend_v2/src/routes/routes.tsx`: type the optional `currency_code` returned by order endpoints.
- Create `../pix_frontend_v2/src/utils/money.ts`: own locale-aware money presentation and safe currency fallback behavior.
- Create `../pix_frontend_v2/src/utils/money.test.ts`: verify formatting for multiple currencies and malformed metadata.
- Modify `../pix_frontend_v2/src/app/dashboard/orders/page.tsx`: format each personal-order total with its own currency.
- Modify `../pix_frontend_v2/src/app/dashboard/organization/page.tsx`: format each organization-order amount with its own currency.
- Modify `../pix_frontend_v2/src/app/dashboard/orders/[id]/page.tsx`: retain the loaded order currency and apply it to position price columns.
- Modify `../pix_frontend_v2/src/app/dashboard/orders/[id]/orderChanges.test.ts`: prove currency metadata does not alter numeric draft values.

### Task 1: Enrich MoySklad Customer Orders With Currency Codes

**Files:**
- Create: `tests/test_order_currency.py`
- Modify: `manager/moysklad.py:230-318`

**Interfaces:**
- Consumes: MoySklad order dictionaries containing optional `rate.currency.isoCode`.
- Produces: `enrich_order_currency(order: dict) -> dict`, which mutates and returns the same order dictionary with optional `currency_code`; `CustomerOrderManager.get_order_by_id()` and `get_orders_by_user()` return enriched orders.

- [ ] **Step 1: Write failing manager tests**

Create `tests/test_order_currency.py`:

```python
from types import SimpleNamespace

import pytest

from manager.moysklad import CustomerOrderManager, enrich_order_currency


class RecordingCustomerOrderRepository:
    def __init__(self):
        self.read_one_link = None
        self.read_all_filter = None

    async def read_one(self, order_id, **kwargs):
        self.read_one_link = kwargs.get("link")
        return {
            "id": str(order_id),
            "rate": {"currency": {"isoCode": "usd"}},
        }

    async def read_all(self, filter="", **kwargs):
        self.read_all_filter = filter
        return {
            "rows": [
                {"id": "order-usd", "rate": {"currency": {"isoCode": "USD"}}},
                {"id": "order-without-currency", "rate": {"currency": {}}},
            ]
        }


def test_enrich_order_currency_uses_only_non_empty_iso_code():
    order = {"rate": {"currency": {"isoCode": " pln "}}}
    assert enrich_order_currency(order)["currency_code"] == "PLN"

    incomplete = {"rate": {"currency": {}}}
    assert enrich_order_currency(incomplete) is incomplete
    assert "currency_code" not in incomplete


@pytest.mark.asyncio
async def test_single_order_expands_and_returns_currency():
    repository = RecordingCustomerOrderRepository()
    result = await CustomerOrderManager(repository).get_order_by_id("order-usd")

    assert repository.read_one_link == "expand=positions.assortment,state,rate.currency"
    assert result["currency_code"] == "USD"


@pytest.mark.asyncio
async def test_order_list_expands_and_enriches_each_currency_independently():
    repository = RecordingCustomerOrderRepository()
    user = SimpleNamespace(moysklad_counterparty_id="counterparty-1")

    result = await CustomerOrderManager(repository).get_orders_by_user(user)

    assert "expand=state,rate.currency" in repository.read_all_filter
    assert result["rows"][0]["currency_code"] == "USD"
    assert "currency_code" not in result["rows"][1]
```

- [ ] **Step 2: Run the focused backend test and confirm the red state**

Run from `pix_backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_currency.py -q
```

Expected: collection fails because `enrich_order_currency` does not exist.

- [ ] **Step 3: Implement minimal manager enrichment**

Add near `CustomerOrderManager` in `manager/moysklad.py`:

```python
def enrich_order_currency(order: dict) -> dict:
    rate = order.get("rate")
    currency = rate.get("currency") if isinstance(rate, dict) else None
    iso_code = currency.get("isoCode") if isinstance(currency, dict) else None
    if isinstance(iso_code, str) and iso_code.strip():
        order["currency_code"] = iso_code.strip().upper()
    else:
        order.pop("currency_code", None)
    return order
```

Update the retrieval methods:

```python
    async def get_order_by_id(self, id):
        order = await self.__repo.read_one(
            id,
            link="expand=positions.assortment,state,rate.currency",
        )
        return enrich_order_currency(order)

    async def get_orders_by_user(self, user: User):
        result = await self.__repo.read_all(
            f"agent=https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{user.moysklad_counterparty_id}&expand=state,rate.currency&limit=100&order=created,desc"
        )
        rows = result.get("rows")
        if isinstance(rows, list):
            for order in rows:
                if isinstance(order, dict):
                    enrich_order_currency(order)
        return result
```

Do not alter `replace_positions_and_state`: its existing call to `get_order_by_id` will now return the enriched updated order.

- [ ] **Step 4: Run focused and complete backend checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_currency.py -q
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: the focused tests and the full backend check pass.

- [ ] **Step 5: Commit the backend contract change**

```powershell
git add -- manager/moysklad.py tests/test_order_currency.py
git commit -m "feat: expose MoySklad order currencies"
```

### Task 2: Add a Safe Frontend Money Formatter and API Types

**Files:**
- Create: `../pix_frontend_v2/src/utils/money.ts`
- Create: `../pix_frontend_v2/src/utils/money.test.ts`
- Modify: `../pix_frontend_v2/src/routes/routes.tsx:62-95`

**Interfaces:**
- Consumes: amounts already converted to display units and optional `currency_code` strings from Task 1.
- Produces: `formatMoney(amount: number, currencyCode?: string): string`; `GetOrdersType` and `GetOrderType` expose `currency_code?: string`.

- [ ] **Step 1: Write the failing formatter test**

Create `src/utils/money.test.ts` in `pix_frontend_v2`:

```typescript
import { describe, expect, it } from "vitest";

import { formatMoney } from "./money";

function visibleSpaces(value: string): string {
  return value.replace(/\s/g, " ");
}

describe("formatMoney", () => {
  it.each([
    [1250, "USD", "1 250,00 USD"],
    [12.5, "EUR", "12,50 EUR"],
    [0, "PLN", "0,00 PLN"],
    [99.99, "BYN", "99,99 BYN"],
  ])("formats %s in %s", (amount, code, expected) => {
    expect(visibleSpaces(formatMoney(amount, code))).toBe(expected);
  });

  it("normalizes a well-formed code", () => {
    expect(visibleSpaces(formatMoney(12.5, " usd "))).toBe("12,50 USD");
  });

  it.each([undefined, "", "US", "US1", "not-a-code"])(
    "omits an absent or malformed currency code: %s",
    (code) => {
      expect(visibleSpaces(formatMoney(12.5, code))).toBe("12,50");
    },
  );
});
```

- [ ] **Step 2: Run the formatter test and confirm the red state**

Run from `pix_frontend_v2`:

```powershell
npm.cmd run test:unit -- src/utils/money.test.ts
```

Expected: FAIL because `src/utils/money.ts` does not exist.

- [ ] **Step 3: Implement the formatter**

Create `src/utils/money.ts`:

```typescript
const amountFormatter = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatMoney(
  amount: number,
  currencyCode?: string,
): string {
  const normalizedCode = currencyCode?.trim().toUpperCase();
  const formattedAmount = amountFormatter.format(amount);
  return normalizedCode && /^[A-Z]{3}$/.test(normalizedCode)
    ? `${formattedAmount} ${normalizedCode}`
    : formattedAmount;
}
```

- [ ] **Step 4: Type the enriched order responses**

Add the same optional property to `GetOrdersType` and `GetOrderType` in
`src/routes/routes.tsx`:

```typescript
  currency_code?: string;
```

`GetOrganizationOrdersType` already reuses `GetOrdersType[]`, so it requires no
duplicate currency definition.

- [ ] **Step 5: Run formatter tests and frontend type/build verification**

Run:

```powershell
npm.cmd run test:unit -- src/utils/money.test.ts
npm.cmd run lint
npm.cmd run build
```

Expected: formatter tests, lint, and the production build pass without new warnings.

- [ ] **Step 6: Commit the formatting contract**

```powershell
git add -- src/utils/money.ts src/utils/money.test.ts src/routes/routes.tsx
git commit -m "feat: format order money with currency codes"
```

### Task 3: Apply Per-Order Currency to Every Order Price Display

**Files:**
- Modify: `../pix_frontend_v2/src/app/dashboard/orders/page.tsx:15-122`
- Modify: `../pix_frontend_v2/src/app/dashboard/organization/page.tsx:26-185`
- Modify: `../pix_frontend_v2/src/app/dashboard/orders/[id]/page.tsx:68-360`
- Modify: `../pix_frontend_v2/src/app/dashboard/orders/[id]/orderChanges.test.ts`

**Interfaces:**
- Consumes: `formatMoney(amount, currencyCode)` and `currency_code?: string` from Task 2.
- Produces: personal and organization order rows with `currencyCode?: string`; order-detail column formatters bound to the loaded document currency.

- [ ] **Step 1: Strengthen the order-draft regression test**

In `src/app/dashboard/orders/[id]/orderChanges.test.ts`, add
`currency_code: "USD"` to the shared `order` fixture and add this test:

```typescript
  it("keeps document currency separate from numeric draft values", () => {
    const rows = createOrderDraftRows(order);
    expect(order.currency_code).toBe("USD");
    expect(rows.map(({ price, sum }) => ({ price, sum }))).toEqual([
      { price: 100, sum: 100 },
      { price: 200, sum: 400 },
    ]);
  });
```

Run:

```powershell
npm.cmd run test:unit -- "src/app/dashboard/orders/[id]/orderChanges.test.ts"
```

Expected: PASS, establishing that presentation changes must not change numeric draft calculations.

- [ ] **Step 2: Format the personal order-list total**

In `src/app/dashboard/orders/page.tsx`:

```typescript
import { formatMoney } from "@/utils/money";
```

Add `currencyCode?: string` to `OrdersGrid`, add this formatter to the `sum`
column, and retain the code when mapping API rows:

```typescript
      valueFormatter: (params) =>
        formatMoney(params.value ?? 0, params.data?.currencyCode),
```

```typescript
            currencyCode: item.currency_code,
```

- [ ] **Step 3: Format all organization order amounts**

In `src/app/dashboard/organization/page.tsx`, import `formatMoney`, add
`currencyCode?: string` to `OrdersGrid`, and add this formatter to the `sum`,
`payed_sum`, and `delivered_sum` column definitions:

```typescript
      valueFormatter: (params) =>
        formatMoney(params.value ?? 0, params.data?.currencyCode),
```

Retain the code in the API-to-row mapping:

```typescript
            currencyCode: item.currency_code,
```

- [ ] **Step 4: Format unit prices and line totals on order detail**

In `src/app/dashboard/orders/[id]/page.tsx`, import `formatMoney` and add order
currency state beside the existing order state:

```typescript
  const [currencyCode, setCurrencyCode] = useState<string>();
```

Update `applyOrder`:

```typescript
    setCurrencyCode(order.currency_code);
```

Add the same value formatter to the `price` and `sum` column definitions:

```typescript
        valueFormatter: (params) =>
          formatMoney(params.value ?? 0, currencyCode),
```

Add `currencyCode` to the `useMemo` dependency array that produces `colDefs`.
This also formats newly staged zero-price positions with the document currency.

- [ ] **Step 5: Run focused frontend tests**

Run from `pix_frontend_v2`:

```powershell
npm.cmd run test:unit -- src/utils/money.test.ts "src/app/dashboard/orders/[id]/orderChanges.test.ts"
```

Expected: both test files pass.

- [ ] **Step 6: Run final backend and frontend verification after all edits**

Run from `pix_backend`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Run from `pix_frontend_v2`:

```powershell
npm.cmd run check
```

Expected: both repository check commands pass. If signed-in local test data contains
orders in at least two currencies, also smoke `/dashboard/orders` and both order
detail pages and confirm each row/detail uses its own code. If that data is not
available, record the browser smoke as not run rather than claiming it passed.

- [ ] **Step 7: Commit the UI integration**

```powershell
git add -- src/app/dashboard/orders/page.tsx src/app/dashboard/organization/page.tsx "src/app/dashboard/orders/[id]/page.tsx" "src/app/dashboard/orders/[id]/orderChanges.test.ts"
git commit -m "feat: show currencies on customer orders"
```
