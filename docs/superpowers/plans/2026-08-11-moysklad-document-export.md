# MoySklad Document Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make customer-order, purchase-order, and outgoing-invoice PDFs download reliably through the existing Pix endpoints using the documented MoySklad export contract.

**Architecture:** The backend remains an authenticated proxy: it sends a minimal MoySklad export body, follows the documented redirect with bounded timeouts, verifies final PDF bytes, and maps upstream failures to a safe 502 response. The frontend keeps requesting blobs from Pix but replaces popup navigation with a shared anchor-download helper and deterministic filenames.

**Tech Stack:** Python 3.11, FastAPI, requests, pytest, Next.js 14, React 18, TypeScript, Axios, Vitest, Playwright.

## Global Constraints

- Keep the public API prefix `/api_v1` and the three existing export paths unchanged.
- Never send transport-only URL data inside the MoySklad JSON body.
- Never expose MoySklad credentials, response bodies, or temporary download URLs to clients or logs.
- Do not invent polling for an undocumented HTTP 202 response; reject it safely when it contains no final PDF.
- Do not contact real MoySklad or any other production integration in tests.
- Use connect/read timeouts of 5 and 30 seconds for the export request and its redirect chain.
- Return only verified, non-empty content beginning with `%PDF-` as `application/pdf`.
- Preserve all pre-existing generated-bytecode changes in the backend checkout.
- Run backend checks with `PYTHONDONTWRITEBYTECODE=1` and run the full frontend `check` script after final edits.

---

## File Structure

### Backend repository: `C:\Users\zenja\IdeaProjects\pix_backend`

- Modify `errors.py`: define the safe domain exception used for all MoySklad document-export failures.
- Modify `db/repository.py`: own the exact MoySklad POST contract, redirect behavior, timeouts, status validation, PDF validation, and safe diagnostic logging.
- Modify `manager/moysklad.py`: validate the embedded-template collection once and call the explicit repository interface from all three managers.
- Modify `routes/orders.py`: require authentication and return deterministic PDF attachment headers.
- Modify `main.py`: map the domain export exception to a stable HTTP 502 body.
- Modify `docs/ARCHITECTURE.md`: record the corrected export flow and trust boundary.
- Create `tests/test_moysklad_document_export.py`: repository, manager, route, authentication, and error-contract coverage without external HTTP.

### Frontend repository: `C:\Users\zenja\IdeaProjects\pix_frontend_v2`

- Create `src/features/orders/documentDownload.ts`: document-type names, deterministic filenames, and the browser download boundary.
- Create `src/features/orders/documentDownload.test.ts`: pure node-environment tests using injected browser operations.
- Modify `src/routes/routes.tsx`: type and map all three export paths and return the Axios blob promise directly.
- Modify `src/routes/routes.test.ts`: prove URL, authorization, and `responseType: "blob"` for each document type.
- Modify `src/app/dashboard/orders/[id]/page.tsx`: use the shared download helper, show one failure toast, and remove all popup/dead grid-renderer paths.
- Modify `tests/mock-backend.mjs`: serve a deterministic PDF fixture from the customer-order export path.
- Create `tests/order-document-download.spec.ts`: verify a real browser download and visible error behavior.

---

### Task 1: Contract-Accurate MoySklad PDF Repository

**Files:**

- Modify: `errors.py`
- Modify: `db/repository.py:1-145`
- Create: `tests/test_moysklad_document_export.py`

**Interfaces:**

- Produces: `MoySkladDocumentExportError(reason: str, status_code: int | None = None)`.
- Produces: `AbstractRepository.export_document(document_id: str, *, template: dict, extension: str) -> bytes`.
- Produces: `MoySkladRepository.export_document(document_id: str, *, template: dict, extension: str) -> bytes`.
- Uses: `requests.post(..., allow_redirects=True, timeout=(5, 30))`.

- [ ] **Step 1: Write the failing happy-path repository test**

Create `tests/test_moysklad_document_export.py` with a configured repository and a response fake that behaves like the final response after requests follows MoySklad's 303 redirect:

```python
import pytest
import requests

from config import Settings
from db.repository import MoySkladRepository


PDF_BYTES = b"%PDF-1.4\n%%EOF"


def moysklad_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        moysklad_login="login",
        moysklad_password="password",
    )


class FakeExportResponse:
    def __init__(self, *, status_code: int = 200, content: bytes = PDF_BYTES):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"status {self.status_code}",
                response=self,
            )


@pytest.mark.asyncio
async def test_export_document_sends_only_the_moysklad_contract(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeExportResponse()

    monkeypatch.setattr(requests, "post", post)
    repository = MoySkladRepository(moysklad_settings())
    repository.model = "entity/customerorder"
    template = {"meta": {"type": "embeddedtemplate"}}

    result = await repository.export_document(
        "order-id",
        template=template,
        extension="pdf",
    )

    assert result == PDF_BYTES
    assert calls[0][0].endswith("/entity/customerorder/order-id/export")
    assert calls[0][1]["json"] == {
        "template": template,
        "extension": "pdf",
    }
    assert calls[0][1]["allow_redirects"] is True
    assert calls[0][1]["timeout"] == (5, 30)
```

- [ ] **Step 2: Run the happy-path test and confirm the interface is missing**

Run from the backend repository:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m pytest tests\test_moysklad_document_export.py::test_export_document_sends_only_the_moysklad_contract -v
```

Expected: FAIL because `MoySkladRepository` has no `export_document` method.

- [ ] **Step 3: Add the explicit repository interface and minimum happy-path implementation**

Replace the keyword-bag export methods in `db/repository.py` with explicit signatures:

```python
class AbstractRepository(ABC):
    @abstractmethod
    async def export_document(
        self,
        document_id: str,
        *,
        template: dict,
        extension: str,
    ) -> bytes:
        raise NotImplementedError


class MoySkladRepository(AbstractRepository):
    async def export_document(
        self,
        document_id: str,
        *,
        template: dict,
        extension: str,
    ) -> bytes:
        response = requests.post(
            f"{self.base_url}{self.model}/{document_id}/export",
            headers=self._headers(),
            json={"template": template, "extension": extension},
            allow_redirects=True,
            timeout=(5, 30),
        )
        response.raise_for_status()
        return response.content


class SQLAlchemyRepository(AbstractRepository):
    async def export_document(
        self,
        document_id: str,
        *,
        template: dict,
        extension: str,
    ) -> bytes:
        raise NotImplementedError
```

- [ ] **Step 4: Run the happy-path test and confirm it passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_moysklad_document_export.py::test_export_document_sends_only_the_moysklad_contract -v
```

Expected: PASS.

- [ ] **Step 5: Add failing tests for every rejected upstream result**

Append focused tests using the same fake:

```python
from errors import MoySkladDocumentExportError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "content", "reason"),
    [
        (202, b"", "unexpected_status"),
        (200, b"", "invalid_pdf"),
        (200, b'{"errors":[{"error":"bad request"}]}', "invalid_pdf"),
    ],
)
async def test_export_document_rejects_non_final_pdf_responses(
    monkeypatch,
    status_code,
    content,
    reason,
):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: FakeExportResponse(
            status_code=status_code,
            content=content,
        ),
    )
    repository = MoySkladRepository(moysklad_settings())
    repository.model = "entity/customerorder"

    with pytest.raises(MoySkladDocumentExportError) as raised:
        await repository.export_document(
            "order-id",
            template={"meta": {}},
            extension="pdf",
        )

    assert raised.value.reason == reason
    assert raised.value.status_code == status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [requests.Timeout("slow"), requests.HTTPError("503")])
async def test_export_document_wraps_request_failures(monkeypatch, failure):
    def post(*args, **kwargs):
        raise failure

    monkeypatch.setattr(requests, "post", post)
    repository = MoySkladRepository(moysklad_settings())
    repository.model = "entity/customerorder"

    with pytest.raises(MoySkladDocumentExportError) as raised:
        await repository.export_document(
            "order-id",
            template={"meta": {}},
            extension="pdf",
        )

    assert raised.value.reason == "request_failed"


@pytest.mark.asyncio
async def test_export_document_wraps_an_http_error_response(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: FakeExportResponse(status_code=503),
    )
    repository = MoySkladRepository(moysklad_settings())
    repository.model = "entity/customerorder"

    with pytest.raises(MoySkladDocumentExportError) as raised:
        await repository.export_document(
            "order-id",
            template={"meta": {}},
            extension="pdf",
        )

    assert raised.value.reason == "request_failed"
    assert raised.value.status_code == 503
```

- [ ] **Step 6: Run the rejection tests and confirm raw responses still escape**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_moysklad_document_export.py -v
```

Expected: FAIL because 202, empty bodies, and JSON bodies are returned and `requests` exceptions are not translated.

- [ ] **Step 7: Implement the safe domain error, validation, and logging**

Add to `errors.py`:

```python
class MoySkladDocumentExportError(RuntimeError):
    def __init__(self, reason: str, status_code: int | None = None) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__("MoySklad document export failed")
```

In `db/repository.py`, add `import logging`, import the exception, define `logger = logging.getLogger(__name__)`, and finish `export_document` with this behavior:

```python
try:
    response = requests.post(
        f"{self.base_url}{self.model}/{document_id}/export",
        headers=self._headers(),
        json={"template": template, "extension": extension},
        allow_redirects=True,
        timeout=(5, 30),
    )
    response.raise_for_status()
except requests.RequestException as exc:
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    logger.warning(
        "MoySklad document export request failed model=%s document_id=%s status=%s",
        self.model,
        document_id,
        status_code,
    )
    raise MoySkladDocumentExportError("request_failed", status_code) from exc

if response.status_code != 200:
    logger.warning(
        "MoySklad document export returned a non-final status model=%s document_id=%s status=%s",
        self.model,
        document_id,
        response.status_code,
    )
    raise MoySkladDocumentExportError("unexpected_status", response.status_code)

if not response.content.startswith(b"%PDF-"):
    logger.warning(
        "MoySklad document export returned invalid PDF content model=%s document_id=%s status=%s",
        self.model,
        document_id,
        response.status_code,
    )
    raise MoySkladDocumentExportError("invalid_pdf", response.status_code)

return response.content
```

Do not log `response.content`, response headers, the redirect URL, or authorization headers.

- [ ] **Step 8: Run focused and existing integration tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_moysklad_document_export.py tests\test_integrations.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit the repository contract**

```powershell
git add errors.py db/repository.py tests/test_moysklad_document_export.py
git commit -m "fix: validate MoySklad PDF exports"
```

---

### Task 2: Manager, Authentication, Attachment, and Safe HTTP Error Contract

**Files:**

- Modify: `manager/moysklad.py:251-407`
- Modify: `routes/orders.py:1-136`
- Modify: `main.py:1-120`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `tests/test_moysklad_document_export.py`

**Interfaces:**

- Consumes: `AbstractRepository.export_document(document_id, *, template, extension) -> bytes` from Task 1.
- Consumes: `MoySkladDocumentExportError` from Task 1.
- Produces: authenticated responses with filenames `customer-order-{id}.pdf`, `purchase-order-{id}.pdf`, and `invoice-out-{id}.pdf`.
- Produces: HTTP 502 JSON `{"detail":{"code":"document_export_failed","message":"Document generation failed"}}` for the domain exception.

- [ ] **Step 1: Add failing manager delegation and template-validation tests**

Append to `tests/test_moysklad_document_export.py`:

```python
from manager.moysklad import (
    CustomerOrderManager,
    InvoiceOutManager,
    PurchaseOrderManager,
)


class ExportRepositoryStub:
    def __init__(self, template_payload):
        self.template_payload = template_payload
        self.calls = []

    async def read_all(self, **kwargs):
        assert kwargs == {"metadata": "/metadata/embeddedtemplate"}
        return self.template_payload

    async def export_document(self, document_id, *, template, extension):
        self.calls.append((document_id, template, extension))
        return PDF_BYTES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manager_type",
    [CustomerOrderManager, PurchaseOrderManager, InvoiceOutManager],
)
async def test_export_managers_use_the_first_embedded_template(manager_type):
    template = {"meta": {"type": "embeddedtemplate"}}
    repository = ExportRepositoryStub({"rows": [template]})

    result = await manager_type(repository).export_template("document-id")

    assert result == PDF_BYTES
    assert repository.calls == [("document-id", template, "pdf")]


@pytest.mark.asyncio
async def test_export_manager_rejects_a_missing_embedded_template():
    repository = ExportRepositoryStub({"rows": []})

    with pytest.raises(MoySkladDocumentExportError) as raised:
        await CustomerOrderManager(repository).export_template("document-id")

    assert raised.value.reason == "template_missing"
    assert repository.calls == []
```

- [ ] **Step 2: Run manager tests and confirm the old keyword-bag call fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_moysklad_document_export.py -k "export_manager" -v
```

Expected: FAIL because managers still call `export(link=...)` and do not validate the template collection.

- [ ] **Step 3: Add one template helper and update all three managers**

In `manager/moysklad.py`, import `MoySkladDocumentExportError` and add:

```python
def first_embedded_template(payload: object) -> dict:
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise MoySkladDocumentExportError("template_missing")
    return rows[0]
```

Use the same explicit call in `CustomerOrderManager`, `PurchaseOrderManager`, and `InvoiceOutManager`:

```python
async def export_template(self, id):
    payload = await self.__repo.read_all(metadata="/metadata/embeddedtemplate")
    return await self.__repo.export_document(
        str(id),
        template=first_embedded_template(payload),
        extension="pdf",
    )
```

- [ ] **Step 4: Run manager tests and confirm they pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_moysklad_document_export.py -k "export_manager" -v
```

Expected: PASS.

- [ ] **Step 5: Add failing route, authentication, and safe-error tests**

Append route coverage using `create_app`, `TestClient`, dependency overrides, and a stub manager:

```python
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dependecies import moysklad as dependency_moysklad
from main import create_app
from routes.users import current_user_dependency


class ExportManagerStub:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def export_template(self, document_id):
        self.calls.append(document_id)
        if self.error:
            raise self.error
        return PDF_BYTES


@pytest.mark.parametrize(
    ("path", "dependency", "filename"),
    [
        (
            "/api_v1/orders/export/customer-id",
            dependency_moysklad.get_customer_order_manager,
            "customer-order-customer-id.pdf",
        ),
        (
            "/api_v1/orders/purchaseorder/export/purchase-id",
            dependency_moysklad.get_purchase_order_manager,
            "purchase-order-purchase-id.pdf",
        ),
        (
            "/api_v1/orders/invoiceout/export/invoice-id",
            dependency_moysklad.get_invoice_out_manager,
            "invoice-out-invoice-id.pdf",
        ),
    ],
)
def test_export_routes_return_authenticated_pdf_attachments(path, dependency, filename):
    app = create_app(Settings(_env_file=None, app_env="test"))
    manager = ExportManagerStub()
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[dependency] = lambda: manager

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'


def test_export_route_requires_authentication():
    app = create_app(Settings(_env_file=None, app_env="test"))
    manager = ExportManagerStub()
    app.dependency_overrides[
        dependency_moysklad.get_customer_order_manager
    ] = lambda: manager

    with TestClient(app) as client:
        response = client.get("/api_v1/orders/export/customer-id")

    assert response.status_code == 401
    assert manager.calls == []


def test_export_failure_maps_to_safe_502():
    app = create_app(Settings(_env_file=None, app_env="test"))
    manager = ExportManagerStub(MoySkladDocumentExportError("invalid_pdf", 200))
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[
        dependency_moysklad.get_customer_order_manager
    ] = lambda: manager

    with TestClient(app) as client:
        response = client.get("/api_v1/orders/export/customer-id")

    assert response.status_code == 502
    assert response.json() == {
        "detail": {
            "code": "document_export_failed",
            "message": "Document generation failed",
        }
    }
    assert "invalid_pdf" not in response.text
```

- [ ] **Step 6: Run route tests and confirm authentication, headers, and mapping fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_moysklad_document_export.py -k "export_route or export_failure" -v
```

Expected: FAIL because routes are public, use `inline; filename=sample.pdf`, and the domain exception has no handler.

- [ ] **Step 7: Implement one response helper and authenticate all export routes**

In `routes/orders.py`, add:

```python
def pdf_attachment(content: bytes, filename: str) -> Response:
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

Give every export endpoint an unused authenticated dependency named `_user`, then call the helper. The customer-order route should have this exact shape; apply the matching manager and filename prefix to the other two:

```python
@router.get("/export/{id}")
async def export_pdf(
    id: str,
    _user: User = Depends(current_user_dependency),
    customer_order_manager: CustomerOrderManager = Depends(
        dependency_moysklad.get_customer_order_manager
    ),
):
    content = await customer_order_manager.export_template(id)
    return pdf_attachment(content, f"customer-order-{id}.pdf")
```

- [ ] **Step 8: Add the global safe 502 exception handler**

Import `MoySkladDocumentExportError` in `main.py` and register:

```python
@application.exception_handler(MoySkladDocumentExportError)
async def moysklad_document_export_error_handler(
    request: Request,
    exc: MoySkladDocumentExportError,
):
    return JSONResponse(
        status_code=502,
        content={
            "detail": {
                "code": "document_export_failed",
                "message": "Document generation failed",
            }
        },
    )
```

The handler intentionally does not serialize `reason`, `status_code`, or an exception chain.

- [ ] **Step 9: Document the corrected flow in architecture docs**

Add a short paragraph near the order flow in `docs/ARCHITECTURE.md` stating that authenticated export endpoints proxy only verified PDFs, MoySklad temporary URLs remain server-side, and upstream failures become safe 502 responses.

- [ ] **Step 10: Run the complete focused backend test file**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_moysklad_document_export.py -v
```

Expected: PASS.

- [ ] **Step 11: Commit the backend HTTP contract**

```powershell
git add manager/moysklad.py routes/orders.py main.py docs/ARCHITECTURE.md tests/test_moysklad_document_export.py
git commit -m "fix: proxy document exports safely"
```

---

### Task 3: Typed Frontend Export API and Browser Download Boundary

**Files:**

- Create: `src/features/orders/documentDownload.ts`
- Create: `src/features/orders/documentDownload.test.ts`
- Modify: `src/routes/routes.tsx:466-487`
- Modify: `src/routes/routes.test.ts`

**Interfaces:**

- Produces: `OrderDocumentType = "order" | "purchaseorder" | "invoiceout"`.
- Produces: `documentFilename(type: OrderDocumentType, documentId: string) -> string`.
- Produces: `downloadOrderDocument(blob: Blob, type: OrderDocumentType, documentId: string, environment?: DownloadEnvironment) -> void`.
- Produces: `ExportEndpoint(documentId: string, orderType: OrderDocumentType) -> Promise<AxiosResponse<Blob>>`.

- [ ] **Step 1: Write failing pure tests for filenames and browser operations**

Create `src/features/orders/documentDownload.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";

import {
  documentFilename,
  downloadOrderDocument,
  type DownloadEnvironment,
} from "./documentDownload";


describe("document download", () => {
  it.each([
    ["order", "customer-order-id.pdf"],
    ["purchaseorder", "purchase-order-id.pdf"],
    ["invoiceout", "invoice-out-id.pdf"],
  ] as const)("builds a deterministic %s filename", (type, expected) => {
    expect(documentFilename(type, "id")).toBe(expected);
  });

  it("clicks, removes, and later revokes one object URL", () => {
    const anchor = {
      href: "",
      download: "",
      click: vi.fn(),
      remove: vi.fn(),
    };
    let deferred: (() => void) | undefined;
    const environment: DownloadEnvironment = {
      createObjectUrl: vi.fn(() => "blob:pdf"),
      createAnchor: vi.fn(() => anchor),
      appendAnchor: vi.fn(),
      revokeObjectUrl: vi.fn(),
      defer: vi.fn((callback) => {
        deferred = callback;
      }),
    };
    const blob = new Blob(["%PDF-1.4"], { type: "application/pdf" });

    downloadOrderDocument(blob, "order", "id", environment);

    expect(anchor.href).toBe("blob:pdf");
    expect(anchor.download).toBe("customer-order-id.pdf");
    expect(environment.appendAnchor).toHaveBeenCalledWith(anchor);
    expect(anchor.click).toHaveBeenCalledOnce();
    expect(anchor.remove).toHaveBeenCalledOnce();
    expect(environment.revokeObjectUrl).not.toHaveBeenCalled();
    deferred?.();
    expect(environment.revokeObjectUrl).toHaveBeenCalledWith("blob:pdf");
  });
});
```

- [ ] **Step 2: Run the utility test and confirm the module is missing**

Run from the frontend repository:

```powershell
npm.cmd run test:unit -- src/features/orders/documentDownload.test.ts
```

Expected: FAIL because `documentDownload.ts` does not exist.

- [ ] **Step 3: Implement the small injected browser boundary**

Create `src/features/orders/documentDownload.ts`:

```typescript
export type OrderDocumentType = "order" | "purchaseorder" | "invoiceout";

type DownloadAnchor = {
  href: string;
  download: string;
  click: () => void;
  remove: () => void;
};

export type DownloadEnvironment = {
  createObjectUrl: (blob: Blob) => string;
  createAnchor: () => DownloadAnchor;
  appendAnchor: (anchor: DownloadAnchor) => void;
  revokeObjectUrl: (url: string) => void;
  defer: (callback: () => void) => void;
};

const filenamePrefixes: Record<OrderDocumentType, string> = {
  order: "customer-order",
  purchaseorder: "purchase-order",
  invoiceout: "invoice-out",
};

export function documentFilename(
  type: OrderDocumentType,
  documentId: string,
): string {
  return `${filenamePrefixes[type]}-${documentId}.pdf`;
}

function browserDownloadEnvironment(): DownloadEnvironment {
  return {
    createObjectUrl: (blob) => URL.createObjectURL(blob),
    createAnchor: () => document.createElement("a"),
    appendAnchor: (anchor) => document.body.appendChild(anchor as HTMLAnchorElement),
    revokeObjectUrl: (url) => URL.revokeObjectURL(url),
    defer: (callback) => window.setTimeout(callback, 0),
  };
}

export function downloadOrderDocument(
  blob: Blob,
  type: OrderDocumentType,
  documentId: string,
  environment: DownloadEnvironment = browserDownloadEnvironment(),
): void {
  const url = environment.createObjectUrl(blob);
  const anchor = environment.createAnchor();
  anchor.href = url;
  anchor.download = documentFilename(type, documentId);
  environment.appendAnchor(anchor);
  anchor.click();
  anchor.remove();
  environment.defer(() => environment.revokeObjectUrl(url));
}
```

- [ ] **Step 4: Run the utility test and confirm it passes**

Run:

```powershell
npm.cmd run test:unit -- src/features/orders/documentDownload.test.ts
```

Expected: PASS.

- [ ] **Step 5: Add failing route tests for all three typed API paths**

In `src/routes/routes.test.ts`, include `get: vi.fn()` in the Axios mock, import `ExportEndpoint`, and add:

```typescript
it.each([
  ["order", "http://backend/orders/export/document-id"],
  [
    "purchaseorder",
    "http://backend/orders/purchaseorder/export/document-id",
  ],
  ["invoiceout", "http://backend/orders/invoiceout/export/document-id"],
] as const)("requests the %s export as an authenticated blob", async (type, url) => {
  vi.mocked(axios.get).mockResolvedValue({ data: new Blob() });

  await ExportEndpoint("document-id", type);

  expect(axios.get).toHaveBeenCalledWith(url, {
    headers: { Authorization: "Bearer token" },
    responseType: "blob",
  });
});
```

- [ ] **Step 6: Run the route test and confirm the current conditional implementation fails the new contract**

Run:

```powershell
npm.cmd run test:unit -- src/routes/routes.test.ts
```

Expected: FAIL until Axios `get` is mocked and `ExportEndpoint` uses the typed path map.

- [ ] **Step 7: Replace the open-ended string branch with an exhaustive map**

Import `OrderDocumentType` in `src/routes/routes.tsx` and replace `ExportEndpoint` with:

```typescript
export async function ExportEndpoint(
  documentId: string,
  orderType: OrderDocumentType,
) {
  const paths: Record<OrderDocumentType, string> = {
    order: `orders/export/${documentId}`,
    purchaseorder: `orders/purchaseorder/export/${documentId}`,
    invoiceout: `orders/invoiceout/export/${documentId}`,
  };

  return axios.get<Blob>(backendUrl(paths[orderType]), {
    headers: { Authorization: getCookie("token") },
    responseType: "blob",
  });
}
```

Do not wrap this call in `toast.promise`; the page will show one specific error and successful downloads need no success toast.

- [ ] **Step 8: Run both focused frontend unit tests**

Run:

```powershell
npm.cmd run test:unit -- src/features/orders/documentDownload.test.ts src/routes/routes.test.ts
```

Expected: PASS.

- [ ] **Step 9: Commit the frontend download boundary**

```powershell
git add src/features/orders/documentDownload.ts src/features/orders/documentDownload.test.ts src/routes/routes.tsx src/routes/routes.test.ts
git commit -m "feat: add typed document download helper"
```

---

### Task 4: Order-Page Download UX and Browser Verification

**Files:**

- Modify: `src/app/dashboard/orders/[id]/page.tsx`
- Modify: `tests/mock-backend.mjs`
- Create: `tests/order-document-download.spec.ts`

**Interfaces:**

- Consumes: `ExportEndpoint(documentId, orderType) -> Promise<AxiosResponse<Blob>>` from Task 3.
- Consumes: `downloadOrderDocument(blob, orderType, documentId) -> void` from Task 3.
- Produces: one visible `Скачать` button per document, one real browser download, and one `Не удалось скачать документ` error toast on failure.

- [ ] **Step 1: Add a mock PDF response and a failing Playwright download test**

Extend `sendBytes` in `tests/mock-backend.mjs` with an optional filename argument while keeping `photo.jpg` as its default for existing chat tests:

```javascript
function sendBytes(
  response,
  content,
  contentType,
  filename = "photo.jpg",
) {
  response.writeHead(200, {
    "Access-Control-Allow-Headers":
      "Authorization, Content-Type, Idempotency-Key",
    "Access-Control-Allow-Origin": "*",
    "Content-Disposition": `attachment; filename="${filename}"`,
    "Content-Type": contentType,
  });
  response.end(content);
}
```

Before the existing order-detail cases, add:

```javascript
if (
  request.method === "GET" &&
  pathname === "/api_v1/orders/export/existing-order"
) {
  return sendBytes(
    response,
    Buffer.from("%PDF-1.4\n%%EOF"),
    "application/pdf",
    "customer-order-existing-order.pdf",
  );
}
```

Create `tests/order-document-download.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";


test.beforeEach(async ({ context, page }) => {
  await context.addCookies([
    {
      name: "token",
      value: "Bearer test-token",
      url: "http://127.0.0.1:3100",
    },
  ]);
  await page.routeWebSocket("wss://pixlogistic.com/**", (socket) =>
    socket.close(),
  );
});


test("downloads the customer order PDF without opening a popup", async ({
  page,
}) => {
  await page.goto("/dashboard/orders/existing-order");

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: 'Скачать Документ "Заказ"' }).click();
  const download = await downloadPromise;

  expect(download.suggestedFilename()).toBe(
    "customer-order-existing-order.pdf",
  );
});


test("shows an error and does not download when export fails", async ({ page }) => {
  await page.route("**/api_v1/orders/export/existing-order", (route) =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "document_export_failed",
          message: "Document generation failed",
        },
      }),
    }),
  );
  await page.goto("/dashboard/orders/existing-order");

  await page.getByRole("button", { name: 'Скачать Документ "Заказ"' }).click();

  await expect(page.getByText("Не удалось скачать документ")).toBeVisible();
});
```

- [ ] **Step 2: Run the Playwright test and confirm the old popup path fails**

Run:

```powershell
npx.cmd playwright test tests/order-document-download.spec.ts
```

Expected: FAIL because the page exposes a link, opens a popup after the request, and never triggers a named browser download.

- [ ] **Step 3: Replace the popup flow and remove the dead renderer**

In `src/app/dashboard/orders/[id]/page.tsx`:

1. Remove imports for `CustomCellRendererProps` and `next/link` if no longer used.
2. Import `downloadOrderDocument` and `OrderDocumentType` from `@/features/orders/documentDownload`.
3. Replace the optional `Document`/`DocumtnsGrid` types with a required local type:

```typescript
type OrderDocument = {
  document_id: string;
  document_name: string;
  document_type: OrderDocumentType;
};
```

4. Type `documentRowData` as `OrderDocument[]`, only push an invoice when `invoiceId` is defined, and remove unused `documentColDefs` plus `DownloadDocumentCellRenderer`.
5. Add this handler inside the page component:

```typescript
const handleDocumentDownload = async (document: OrderDocument) => {
  try {
    const response = await ExportEndpoint(
      document.document_id,
      document.document_type,
    );
    downloadOrderDocument(
      response.data,
      document.document_type,
      document.document_id,
    );
  } catch {
    toast.error("Не удалось скачать документ");
  }
};
```

6. Render a real button instead of `Link href="#"`:

```tsx
<button
  type="button"
  className="ml-4 text-[#2E90FA] transition-all hover:underline"
  aria-label={`Скачать ${doc.document_name}`}
  onClick={() => void handleDocumentDownload(doc)}
>
  Скачать
</button>
```

There must be no `window.open`, non-null assertion on a popup, or duplicate blob wrapping left in the file.

- [ ] **Step 4: Run the focused unit and browser tests**

Run:

```powershell
npm.cmd run test:unit -- src/features/orders/documentDownload.test.ts src/routes/routes.test.ts
npx.cmd playwright test tests/order-document-download.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Run static checks for the touched frontend files**

Run:

```powershell
npm.cmd run lint
npm.cmd run build
```

Expected: PASS with no unused legacy document-grid imports or type errors.

- [ ] **Step 6: Commit the order-page behavior**

```powershell
git add src/app/dashboard/orders/[id]/page.tsx tests/mock-backend.mjs tests/order-document-download.spec.ts
git commit -m "fix: download order documents without popups"
```

---

### Task 5: Full Verification and Clean Handoff

**Files:**

- Verify only; no new production files.

**Interfaces:**

- Consumes: completed backend and frontend commits from Tasks 1-4.
- Produces: fresh verification evidence and clean, reviewable worktrees.

- [ ] **Step 1: Run the complete backend check after the final backend edit**

Run from the backend implementation worktree:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: ruff and the complete pytest suite PASS.

- [ ] **Step 2: Verify backend startup and liveness without integrations**

Run:

```powershell
$env:APP_ENV = "test"
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -c "import main; print(main.app.title)"
.\.venv\Scripts\python.exe -m pytest tests\test_app.py::test_health_is_offline_and_stable -v
```

Expected: the fresh import prints `Pix Logistic API`; the liveness test passes; no production HTTP occurs.

- [ ] **Step 3: Run the complete frontend contract check after the final frontend edit**

Run from the frontend implementation worktree:

```powershell
npm.cmd run check
```

Expected: lint, API URL check, Vitest, build, and Playwright all PASS.

- [ ] **Step 4: Inspect final diffs and worktree status in both repositories**

Run in each implementation worktree:

```powershell
git diff --check
git status --short
git log --oneline -5
```

Expected: `git diff --check` is silent; no uncommitted source or test files remain; only intentional task commits appear. The original backend checkout's pre-existing `.pyc` changes remain untouched.

- [ ] **Step 5: Review the final implementation against the spec**

Confirm all of these directly in code and tests:

- Request JSON has exactly `template` and `extension`.
- Export URL owns `document_id`; it never appears in the JSON body.
- Redirects and `(5, 30)` timeouts are enabled.
- Only status 200 with `%PDF-` bytes reaches a PDF response.
- 4xx, 5xx, timeout, 202, empty, and JSON bodies become safe 502 responses.
- All three backend routes require authentication and use deterministic attachment filenames.
- Frontend downloads through an anchor, revokes the object URL, and contains no popup code.
- The browser test observes a download and the failure test observes the Russian error toast.

Expected: every item has a corresponding passing automated test or static assertion from Tasks 1-4.
