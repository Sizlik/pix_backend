from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from config import Settings
from db.schemas.chat import (
    ConversationLastMessage,
    ConversationPage,
    ConversationSummary,
    OperatorReadResponse,
)
from dependecies.order_chat import (
    get_operator_chat_authenticator,
    get_order_chat_service,
)
from main import create_app
from manager.order_chat import OrderChatNotFound
from manager.order_chat_auth import OperatorChatAuthenticator

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000002")


def conversation_page():
    return ConversationPage(
        items=[
            ConversationSummary(
                order_id=ORDER_ID,
                order_name="12345",
                last_message=ConversationLastMessage(
                    id=MESSAGE_ID,
                    sender_kind="client",
                    sender_label="Клиент",
                    message="Проверка",
                    created_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
                    attachment_count=1,
                ),
                unread_count=2,
            )
        ],
        next_before=None,
        total_unread=2,
    )


def service_stub():
    return SimpleNamespace(
        list_operator_conversations=AsyncMock(return_value=conversation_page()),
        mark_operator_read=AsyncMock(
            return_value=OperatorReadResponse(
                order_id=ORDER_ID,
                total_unread=0,
            )
        ),
    )


@contextmanager
def operator_client(*, enabled=True, service=None):
    service = service or service_stub()
    settings = Settings(
        _env_file=None,
        app_env="test",
        enable_moysklad_order_chat=enabled,
        minio_endpoint="localhost:9000",
        minio_access_key="test",
        minio_secret_key="test-secret",
    )
    storage = SimpleNamespace(ensure_bucket=AsyncMock())
    with patch("main.build_order_chat_storage", return_value=storage):
        app = create_app(settings)
        app.dependency_overrides[get_order_chat_service] = lambda: service
        app.dependency_overrides[get_operator_chat_authenticator] = lambda: (
            OperatorChatAuthenticator("expected")
        )
        with TestClient(app) as client:
            yield client, service


def test_conversation_list_requires_secret_and_passes_default_page_size():
    with operator_client() as (client, service):
        unauthorized = client.get("/api_v1/chat/operator/conversations")
        response = client.get(
            "/api_v1/chat/operator/conversations",
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["items"][0]["order_name"] == "12345"
    assert response.json()["total_unread"] == 2
    service.list_operator_conversations.assert_awaited_once_with(None, 50)


def test_conversation_list_passes_cursor_and_rejects_limit_above_fifty():
    with operator_client() as (client, service):
        response = client.get(
            "/api_v1/chat/operator/conversations",
            params={"before": str(MESSAGE_ID), "limit": 25},
            headers={"X-Pix-Chat-Secret": "expected"},
        )
        excessive = client.get(
            "/api_v1/chat/operator/conversations",
            params={"limit": 51},
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert response.status_code == 200
    assert excessive.status_code == 422
    service.list_operator_conversations.assert_awaited_once_with(MESSAGE_ID, 25)


def test_mark_read_is_idempotent_and_validates_order_id():
    with operator_client() as (client, service):
        response = client.post(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/read",
            headers={"X-Pix-Chat-Secret": "expected"},
        )
        malformed = client.post(
            "/api_v1/chat/operator/orders/not-a-uuid/read",
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "order_id": str(ORDER_ID),
        "unread_count": 0,
        "total_unread": 0,
    }
    assert malformed.status_code == 404
    assert malformed.json() == {"detail": "Order not found"}
    service.mark_operator_read.assert_awaited_once_with(ORDER_ID)


def test_missing_conversation_is_generic_404_and_disabled_chat_is_503():
    missing_service = service_stub()
    missing_service.mark_operator_read.side_effect = OrderChatNotFound()
    with operator_client(service=missing_service) as (client, _):
        missing = client.post(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/read",
            headers={"X-Pix-Chat-Secret": "expected"},
        )
    with operator_client(enabled=False) as (client, disabled_service):
        disabled = client.get(
            "/api_v1/chat/operator/conversations",
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Order not found"}
    assert disabled.status_code == 503
    disabled_service.list_operator_conversations.assert_not_awaited()
