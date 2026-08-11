from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

from config import Settings
from db.repository import MoySkladRepository
from dependecies import moysklad as dependency_moysklad
from errors import MoySkladDocumentExportError
from main import create_app
from manager.moysklad import (
    CustomerOrderManager,
    InvoiceOutManager,
    PurchaseOrderManager,
)
from routes.users import current_user_dependency


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


class ExportManagerStub:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def export_template(self, document_id):
        self.calls.append(document_id)
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
def test_export_routes_return_authenticated_pdf_attachments(
    path,
    dependency,
    filename,
):
    app = create_app(Settings(_env_file=None, app_env="test"))
    manager = ExportManagerStub()
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
        id="user"
    )
    app.dependency_overrides[dependency] = lambda: manager

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{filename}"'
    )


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
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
        id="user"
    )
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
