import pytest
import requests

from config import Settings
from db.repository import MoySkladRepository
from errors import MoySkladDocumentExportError


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
