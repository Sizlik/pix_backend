import base64
from dataclasses import dataclass
from uuid import UUID

from config import Settings
from db.moysklad_order_chat_repository import (
    MoySkladOrderChatRepository,
    MoySkladUpload,
)


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200
    content: bytes = b""

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/files") and method == "GET":
            return FakeResponse({"rows": []})
        if url.endswith("/files") and method == "POST":
            return FakeResponse(
                [
                    {
                        "meta": {
                            "href": (url + "/00000000-0000-0000-0000-000000000010"),
                            "downloadHref": ("https://api.moysklad.ru/api/remap/1.2/download/file"),
                        },
                        "filename": "[ЧАТ-КЛИЕНТ][m] a.txt",
                        "size": 5,
                    }
                ]
            )
        if url.endswith("/entity/webhook") and method == "GET":
            return FakeResponse({"rows": []})
        if url.endswith("/entity/webhook") and method == "POST":
            return FakeResponse({"id": "webhook"})
        if "/download/" in url and method == "GET":
            return FakeResponse({}, content=b"downloaded")
        return FakeResponse(
            {
                "id": "order",
                "agent": {"meta": {"href": ("https://api.moysklad.ru/api/remap/1.2/entity/counterparty/client")}},
            }
        )


def settings():
    return Settings(
        _env_file=None,
        moysklad_login="login",
        moysklad_password="password",
    )


async def test_get_order_expands_agent_and_uses_timeout_and_gzip():
    session = FakeSession()
    repository = MoySkladOrderChatRepository(settings(), session=session, timeout_seconds=15)

    await repository.get_order(UUID("00000000-0000-0000-0000-000000000001"))

    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url.endswith("/entity/customerorder/00000000-0000-0000-0000-000000000001")
    assert kwargs["params"] == {"expand": "agent"}
    assert kwargs["timeout"] == 15
    assert kwargs["headers"]["Accept-Encoding"] == "gzip"
    assert kwargs["headers"]["Authorization"] == ("Basic " + base64.b64encode(b"login:password").decode())


async def test_upload_uses_special_resource_base64_array_and_maps_response():
    session = FakeSession()
    repository = MoySkladOrderChatRepository(settings(), session=session)

    result = await repository.upload_files(
        UUID("00000000-0000-0000-0000-000000000001"),
        [MoySkladUpload(filename="[ЧАТ-КЛИЕНТ][m] a.txt", content=b"hello")],
    )

    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/entity/customerorder/00000000-0000-0000-0000-000000000001/files")
    assert kwargs["json"] == [
        {
            "filename": "[ЧАТ-КЛИЕНТ][m] a.txt",
            "content": "aGVsbG8=",
        }
    ]
    assert result[0].filename == "[ЧАТ-КЛИЕНТ][m] a.txt"


async def test_upload_chunks_at_the_moysklad_ten_file_limit():
    session = FakeSession()
    repository = MoySkladOrderChatRepository(settings(), session=session)

    await repository.upload_files(
        UUID("00000000-0000-0000-0000-000000000001"),
        [MoySkladUpload(filename=f"{index}.txt", content=b"a") for index in range(11)],
    )

    payloads = [kwargs["json"] for method, _, kwargs in session.calls if method == "POST"]
    assert [len(payload) for payload in payloads] == [10, 1]


async def test_description_files_delete_download_and_webhook_contracts():
    session = FakeSession()
    repository = MoySkladOrderChatRepository(settings(), session=session)
    order_id = UUID("00000000-0000-0000-0000-000000000001")
    file_id = UUID("00000000-0000-0000-0000-000000000010")

    await repository.update_description(order_id, "chat projection")
    assert (await repository.list_files(order_id)) == []
    await repository.delete_file(order_id, file_id)
    assert await repository.download_file("https://api.moysklad.ru/api/remap/1.2/download/file") == b"downloaded"
    assert await repository.list_webhooks() == []
    await repository.create_webhook("https://pixlogistic.com/webhook")

    calls = {(method, url): kwargs for method, url, kwargs in session.calls}
    order_url = repository.base_url + f"entity/customerorder/{order_id}"
    assert calls[("PUT", order_url)]["json"] == {"description": "chat projection"}
    assert ("GET", order_url + "/files") in calls
    assert ("DELETE", order_url + f"/files/{file_id}") in calls
    webhook_url = repository.base_url + "entity/webhook"
    assert calls[("POST", webhook_url)]["json"] == {
        "url": "https://pixlogistic.com/webhook",
        "action": "UPDATE",
        "entityType": "customerorder",
        "diffType": "FIELDS",
    }
