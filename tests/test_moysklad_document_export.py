from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

from config import Settings
from db.repository import MoySkladRepository
from dependecies import moysklad as dependency_moysklad
from errors import MoySkladDocumentExportError, OrderNotAccessible
from main import create_app
from manager.moysklad import (
    CustomerOrderManager,
    InvoiceOutManager,
    PurchaseOrderManager,
)
from routes.users import current_user_dependency

PDF_BYTES = b"%PDF-1.4\n%%EOF"
EXPORT_ROUTE_CASES = [
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
]


def moysklad_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        moysklad_login="login",
        moysklad_password="password",
    )


def export_user(*, counterparty_id="counterparty", is_superuser=True):
    return SimpleNamespace(
        id="user",
        moysklad_counterparty_id=counterparty_id,
        is_superuser=is_superuser,
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


class FakeJsonResponse(FakeExportResponse):
    def __init__(self, payload=None, *, status_code: int = 200, json_error=None):
        super().__init__(status_code=status_code)
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


class ExportRepositoryStub:
    def __init__(self, template_payload, context_payload=None):
        self.template_payload = template_payload
        self.context_payload = context_payload or {
            "id": "document-id",
            "agent": {
                "meta": {
                    "href": (
                        "https://api.moysklad.ru/api/remap/1.2/"
                        "entity/counterparty/counterparty"
                    )
                }
            },
        }
        self.calls = []
        self.context_calls = []
        self.template_reads = 0

    async def read_export_context(self, document_id):
        self.context_calls.append(document_id)
        return self.context_payload

    async def read_embedded_templates(self):
        self.template_reads += 1
        return self.template_payload

    async def export_document(self, document_id, *, template, extension):
        self.calls.append((document_id, template, extension))
        return PDF_BYTES


class ExportManagerStub:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def export_template(self, document_id, user):
        self.calls.append((document_id, user))
        if self.error:
            raise self.error
        return PDF_BYTES


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


@pytest.mark.asyncio
async def test_embedded_template_request_uses_a_bounded_timeout(monkeypatch):
    calls = []
    payload = {"rows": [{"meta": {"type": "embeddedtemplate"}}]}

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeJsonResponse(payload)

    monkeypatch.setattr(requests, "get", get)
    repository = MoySkladRepository(moysklad_settings())
    repository.model = "entity/customerorder"

    result = await repository.read_embedded_templates()

    assert result == payload
    assert calls[0][0].endswith(
        "/entity/customerorder/metadata/embeddedtemplate"
    )
    assert calls[0][1]["timeout"] == (5, 30)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "failure", "status_code"),
    [
        (None, requests.Timeout("slow"), None),
        (FakeJsonResponse(status_code=503), None, 503),
        (FakeJsonResponse(json_error=ValueError("invalid json")), None, 200),
    ],
)
async def test_embedded_template_request_wraps_upstream_failures(
    monkeypatch,
    response,
    failure,
    status_code,
):
    def get(*args, **kwargs):
        if failure:
            raise failure
        return response

    monkeypatch.setattr(requests, "get", get)
    repository = MoySkladRepository(moysklad_settings())
    repository.model = "entity/customerorder"

    with pytest.raises(MoySkladDocumentExportError) as raised:
        await repository.read_embedded_templates()

    assert raised.value.reason == "template_request_failed"
    assert raised.value.status_code == status_code


@pytest.mark.asyncio
async def test_export_context_request_is_bounded_and_expands_agent(monkeypatch):
    calls = []
    payload = {
        "id": "order-id",
        "agent": {"meta": {"href": "https://example/counterparty"}},
    }

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeJsonResponse(payload)

    monkeypatch.setattr(requests, "get", get)
    repository = MoySkladRepository(moysklad_settings())
    repository.model = "entity/customerorder"

    result = await repository.read_export_context("order-id")

    assert result == payload
    assert calls[0][0].endswith("/entity/customerorder/order-id")
    assert calls[0][1]["params"] == {"expand": "agent"}
    assert calls[0][1]["timeout"] == (5, 30)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "failure", "expected", "status_code"),
    [
        (FakeJsonResponse(status_code=404), None, {}, None),
        (None, requests.Timeout("slow"), None, None),
        (FakeJsonResponse(status_code=503), None, None, 503),
        (FakeJsonResponse(payload=[]), None, None, 200),
    ],
)
async def test_export_context_normalizes_not_found_and_upstream_failures(
    monkeypatch,
    response,
    failure,
    expected,
    status_code,
):
    def get(*args, **kwargs):
        if failure:
            raise failure
        return response

    monkeypatch.setattr(requests, "get", get)
    repository = MoySkladRepository(moysklad_settings())
    repository.model = "entity/customerorder"

    if expected is not None:
        assert await repository.read_export_context("order-id") == expected
        return

    with pytest.raises(MoySkladDocumentExportError) as raised:
        await repository.read_export_context("order-id")

    assert raised.value.reason == "context_request_failed"
    assert raised.value.status_code == status_code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manager_type",
    [CustomerOrderManager, PurchaseOrderManager, InvoiceOutManager],
)
async def test_export_managers_use_the_first_embedded_template(manager_type):
    template = {"meta": {"type": "embeddedtemplate"}}
    repository = ExportRepositoryStub({"rows": [template]})

    result = await manager_type(repository).export_template(
        "document-id",
        export_user(),
    )

    assert result == PDF_BYTES
    assert repository.calls == [("document-id", template, "pdf")]


@pytest.mark.asyncio
async def test_export_manager_rejects_a_missing_embedded_template():
    repository = ExportRepositoryStub({"rows": []})

    with pytest.raises(MoySkladDocumentExportError) as raised:
        await CustomerOrderManager(repository).export_template(
            "document-id",
            export_user(),
        )

    assert raised.value.reason == "template_missing"
    assert repository.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_type", [CustomerOrderManager, InvoiceOutManager])
async def test_export_manager_rejects_a_document_owned_by_another_user(
    manager_type,
):
    repository = ExportRepositoryStub(
        {"rows": [{"meta": {}}]},
        context_payload={
            "id": "document-id",
            "agent": {
                "meta": {
                    "href": (
                        "https://api.moysklad.ru/api/remap/1.2/"
                        "entity/counterparty/another-counterparty"
                    )
                }
            },
        },
    )

    with pytest.raises(OrderNotAccessible):
        await manager_type(repository).export_template(
            "document-id",
            export_user(is_superuser=False),
        )

    assert repository.template_reads == 0
    assert repository.calls == []


@pytest.mark.asyncio
async def test_purchase_order_export_requires_a_superuser():
    repository = ExportRepositoryStub({"rows": [{"meta": {}}]})

    with pytest.raises(OrderNotAccessible):
        await PurchaseOrderManager(repository).export_template(
            "document-id",
            export_user(is_superuser=False),
        )

    assert repository.template_reads == 0
    assert repository.calls == []


@pytest.mark.parametrize(
    ("path", "dependency", "filename"),
    EXPORT_ROUTE_CASES,
)
def test_export_routes_return_authenticated_pdf_attachments(
    path,
    dependency,
    filename,
):
    app = create_app(Settings(_env_file=None, app_env="test"))
    manager = ExportManagerStub()
    user = export_user()
    app.dependency_overrides[current_user_dependency] = lambda: user
    app.dependency_overrides[dependency] = lambda: manager

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{filename}"'
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert manager.calls == [(path.rsplit("/", 1)[-1], user)]


@pytest.mark.parametrize(("path", "dependency", "_filename"), EXPORT_ROUTE_CASES)
def test_export_routes_require_authentication(path, dependency, _filename):
    app = create_app(Settings(_env_file=None, app_env="test"))
    manager = ExportManagerStub()
    app.dependency_overrides[dependency] = lambda: manager

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 401
    assert manager.calls == []


@pytest.mark.parametrize(("path", "dependency", "_filename"), EXPORT_ROUTE_CASES)
def test_export_routes_hide_inaccessible_documents(path, dependency, _filename):
    app = create_app(Settings(_env_file=None, app_env="test"))
    manager = ExportManagerStub(OrderNotAccessible())
    app.dependency_overrides[current_user_dependency] = lambda: export_user()
    app.dependency_overrides[dependency] = lambda: manager

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "order_not_found", "message": "Order not found"}
    }


def test_export_failure_maps_to_safe_502():
    app = create_app(Settings(_env_file=None, app_env="test"))
    manager = ExportManagerStub(MoySkladDocumentExportError("invalid_pdf", 200))
    app.dependency_overrides[current_user_dependency] = lambda: export_user()
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
