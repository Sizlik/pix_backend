from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient

from config import Settings
from db.schemas.chat import MoySkladWebhookPayload
from dependecies.order_chat import get_order_chat_webhook_receiver
from main import create_app
from routes.integration.order_chat_webhook import OrderChatWebhookReceiver
from scripts.register_moysklad_order_chat_webhook import (
    build_webhook_url,
    redact_webhook_url,
)


def payload(action="UPDATE", entity_type="customerorder"):
    return {
        "auditContext": {
            "meta": {
                "type": "audit",
                "href": "https://api.moysklad.ru/api/remap/1.2/audit/audit-id",
            },
            "moment": "2026-08-10 12:00:00",
            "uid": "manager@example.com",
        },
        "events": [
            {
                "meta": {
                    "type": entity_type,
                    "href": (
                        "https://api.moysklad.ru/api/remap/1.2/"
                        "entity/customerorder/"
                        "00000000-0000-0000-0000-000000000001"
                    ),
                },
                "updatedFields": ["description", "files"],
                "action": action,
                "accountId": "00000000-0000-0000-0000-000000000099",
            }
        ],
    }


def webhook_client(receiver):
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_order_chat_webhook_receiver] = lambda: receiver
    return TestClient(app)


def test_webhook_accepts_valid_secret_and_only_enqueues():
    receiver = SimpleNamespace(secret="webhook-secret", enqueue=AsyncMock(return_value=1))
    with webhook_client(receiver) as client:
        response = client.post(
            "/api_v1/integration/webhooks/order-chat/webhook-secret?requestId=request-1",
            json=payload(),
        )

    assert response.status_code == 204
    receiver.enqueue.assert_awaited_once()


def test_webhook_hides_secret_failure_as_not_found():
    receiver = SimpleNamespace(secret="webhook-secret", enqueue=AsyncMock(return_value=0))
    with webhook_client(receiver) as client:
        response = client.post(
            "/api_v1/integration/webhooks/order-chat/wrong?requestId=request-1",
            json=payload(),
        )

    assert response.status_code == 404
    receiver.enqueue.assert_not_awaited()


async def test_receiver_ignores_non_update_and_non_customer_order():
    repository = SimpleNamespace(enqueue_events=AsyncMock())
    receiver = OrderChatWebhookReceiver(repository=repository, secret="secret")

    accepted = await receiver.enqueue(
        "request-1",
        MoySkladWebhookPayload.model_validate(
            {
                "events": [
                    payload(action="DELETE")["events"][0],
                    payload(entity_type="product")["events"][0],
                ]
            }
        ),
    )

    assert accepted == 0
    repository.enqueue_events.assert_not_awaited()


async def test_receiver_uses_request_and_order_as_dedup_identity():
    repository = SimpleNamespace(enqueue_events=AsyncMock())
    receiver = OrderChatWebhookReceiver(repository=repository, secret="secret")

    await receiver.enqueue("request-1", MoySkladWebhookPayload.model_validate(payload()))

    event = repository.enqueue_events.await_args.args[0][0]
    assert event.order_id == UUID("00000000-0000-0000-0000-000000000001")
    assert event.dedup_key == ("moysklad:request-1:00000000-0000-0000-0000-000000000001")


def test_registration_url_uses_configured_secret_but_redaction_never_returns_it():
    url = build_webhook_url("https://pixlogistic.com/", "super-secret")

    assert url == (
        "https://pixlogistic.com/api_v1/integration/webhooks/"
        "order-chat/super-secret"
    )
    assert redact_webhook_url(url) == (
        "https://pixlogistic.com/api_v1/integration/webhooks/order-chat/***"
    )
    assert "super-secret" not in redact_webhook_url(url)
