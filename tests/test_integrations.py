import pytest
import requests

from bot.sender import Sender
from config import Settings
from db.repository import MoySkladRepository
from errors import IntegrationNotConfigured
from manager.bitrix import BitrixCrmContact
from manager.privoz_order import PrivozManager
from manager.users import send_verification_code


def missing_integration_settings() -> Settings:
    return Settings(_env_file=None, app_env="test")


@pytest.mark.asyncio
async def test_moysklad_requires_credentials_before_http(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("external HTTP was called")

    monkeypatch.setattr(requests, "get", fail)
    repository = MoySkladRepository(missing_integration_settings())

    with pytest.raises(IntegrationNotConfigured, match="moysklad"):
        await repository.get_default_company()


@pytest.mark.asyncio
async def test_telegram_requires_token_before_sending():
    sender = Sender(settings_provider=missing_integration_settings)

    with pytest.raises(IntegrationNotConfigured, match="telegram"):
        await sender.send_group_message("test")


def test_bitrix_requires_webhook_url_before_http(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("external HTTP was called")

    monkeypatch.setattr(requests, "post", fail)

    with pytest.raises(IntegrationNotConfigured, match="bitrix"):
        BitrixCrmContact(missing_integration_settings()).get("1")


@pytest.mark.asyncio
async def test_privoz_requires_credentials_before_http(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("external HTTP was called")

    monkeypatch.setattr(requests.Session, "post", fail)
    manager = PrivozManager(object(), missing_integration_settings())

    with pytest.raises(IntegrationNotConfigured, match="privoz"):
        await manager.parse_privoz()


def test_email_requires_token_before_http(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("external HTTP was called")

    monkeypatch.setattr(requests, "post", fail)

    with pytest.raises(IntegrationNotConfigured, match="email"):
        send_verification_code(
            "developer@example.com",
            "123456",
            missing_integration_settings(),
        )


class FakeMoySkladResponse:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


@pytest.mark.asyncio
async def test_moysklad_update_omits_transport_link_and_raises_http_errors(
    monkeypatch,
):
    calls = []

    def put(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return FakeMoySkladResponse({"id": "order"})

    settings = Settings(
        _env_file=None,
        app_env="test",
        moysklad_login="login",
        moysklad_password="password",
    )
    monkeypatch.setattr(requests, "put", put)
    repository = MoySkladRepository(settings)
    repository.model = "entity/customerorder"

    await repository.update("order", link="/positions/position", quantity=2)

    assert calls[0][0].endswith(
        "/entity/customerorder/order/positions/position"
    )
    assert calls[0][1] == {"quantity": 2}

    monkeypatch.setattr(
        requests,
        "put",
        lambda *args, **kwargs: FakeMoySkladResponse(status_code=503),
    )
    with pytest.raises(requests.HTTPError):
        await repository.update("order", positions=[], state={"meta": {}})


@pytest.mark.asyncio
async def test_moysklad_create_omits_transport_link_and_raises_http_errors(
    monkeypatch,
):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return FakeMoySkladResponse({"id": "position"})

    settings = Settings(
        _env_file=None,
        app_env="test",
        moysklad_login="login",
        moysklad_password="password",
    )
    monkeypatch.setattr(requests, "post", post)
    repository = MoySkladRepository(settings)
    repository.model = "entity/customerorder"

    await repository.create(link="order/positions", quantity=2)
    assert calls[0][0].endswith("/entity/customerorder/order/positions")
    assert calls[0][1] == {"quantity": 2}

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: FakeMoySkladResponse(status_code=503),
    )
    with pytest.raises(requests.HTTPError):
        await repository.create(positions=[])


@pytest.mark.asyncio
async def test_moysklad_read_one_maps_only_not_found_to_an_empty_result(
    monkeypatch,
):
    settings = Settings(
        _env_file=None,
        app_env="test",
        moysklad_login="login",
        moysklad_password="password",
    )
    repository = MoySkladRepository(settings)
    repository.model = "entity/customerorder"

    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: FakeMoySkladResponse(status_code=404),
    )
    assert await repository.read_one("missing") == {}

    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: FakeMoySkladResponse(status_code=503),
    )
    with pytest.raises(requests.HTTPError):
        await repository.read_one("unavailable")
