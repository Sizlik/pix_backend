import base64
from dataclasses import dataclass
from uuid import UUID

import pytest
import requests

from config import Settings
from db.moysklad_order_chat_repository import MoySkladOrderChatRepository
from errors import MoySkladOrderLookupUnavailable


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200
    content: bytes = b""

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class FakeSession:
    def __init__(self, response=None, failure=None):
        self.calls = []
        self.response = response
        self.failure = failure

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.failure is not None:
            raise self.failure
        if self.response is not None:
            return self.response
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


async def test_get_order_returns_none_for_upstream_404():
    repository = MoySkladOrderChatRepository(
        settings(),
        session=FakeSession(response=FakeResponse({}, status_code=404)),
    )

    assert await repository.get_order(UUID(int=1)) is None


@pytest.mark.parametrize(
    "failure",
    [
        requests.ConnectionError("https://api.moysklad.ru/private"),
        requests.Timeout("secret response body"),
    ],
)
async def test_get_order_raises_safe_error_for_request_failures(failure):
    repository = MoySkladOrderChatRepository(settings(), session=FakeSession(failure=failure))

    with pytest.raises(MoySkladOrderLookupUnavailable) as raised:
        await repository.get_order(UUID(int=1))

    assert str(raised.value) == "MoySklad order lookup unavailable"
    assert raised.value.__cause__ is None


async def test_get_order_raises_safe_error_for_invalid_json():
    class InvalidJsonResponse(FakeResponse):
        def json(self):
            raise ValueError("secret response body")

    repository = MoySkladOrderChatRepository(
        settings(),
        session=FakeSession(response=InvalidJsonResponse({})),
    )

    with pytest.raises(MoySkladOrderLookupUnavailable) as raised:
        await repository.get_order(UUID(int=1))

    assert str(raised.value) == "MoySklad order lookup unavailable"
    assert raised.value.__cause__ is None
