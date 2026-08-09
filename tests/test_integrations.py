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
