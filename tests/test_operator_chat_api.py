from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from config import Settings
from db.schemas.chat import OrderChatMessageResponse, OrderChatPageResponse, SenderKind
from dependecies.order_chat import get_operator_chat_authenticator, get_order_chat_service
from errors import MoySkladOrderLookupUnavailable
from main import create_app
from manager.order_chat import DownloadedAttachment
from manager.order_chat_auth import OperatorChatAuthenticator

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
ATTACHMENT_ID = UUID("00000000-0000-0000-0000-000000000002")


def manager_message(order_id=ORDER_ID):
    return OrderChatMessageResponse(
        id=UUID("00000000-0000-0000-0000-000000000010"),
        order_id=order_id,
        sender_kind=SenderKind.MANAGER,
        sender_label="Менеджер Pix Logistic",
        message="Готово",
        created_at=datetime.now(timezone.utc),
        attachments=[],
    )


def service_stub():
    return SimpleNamespace(
        list_operator_messages=AsyncMock(
            return_value=OrderChatPageResponse(items=[], next_before=None)
        ),
        create_manager_message=AsyncMock(return_value=manager_message()),
        get_operator_attachment=AsyncMock(
            return_value=DownloadedAttachment(
                filename="счёт.pdf",
                mime_type="application/pdf",
                content=b"%PDF-1.7",
            )
        ),
    )


def storage_stub():
    return SimpleNamespace(ensure_bucket=AsyncMock())


@contextmanager
def operator_client(*, enabled=True, expected_secret="expected", service=None):
    service = service or service_stub()
    settings = Settings(
        _env_file=None,
        app_env="test",
        enable_moysklad_order_chat=enabled,
        minio_endpoint="localhost:9000",
        minio_access_key="test",
        minio_secret_key="test-secret",
    )
    with patch("main.build_order_chat_storage", return_value=storage_stub()):
        app = create_app(settings)
        app.dependency_overrides[get_order_chat_service] = lambda: service
        app.dependency_overrides[get_operator_chat_authenticator] = lambda: (
            OperatorChatAuthenticator(expected_secret)
        )
        with TestClient(app) as client:
            yield client, service


def test_operator_history_requires_the_shared_secret():
    with operator_client() as (client, service):
        missing = client.get(f"/api_v1/chat/operator/orders/{ORDER_ID}/messages")
        wrong = client.get(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/messages",
            headers={"X-Pix-Chat-Secret": "wrong"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json() == wrong.json() == {"detail": "Unauthorized"}
    service.list_operator_messages.assert_not_awaited()


def test_operator_history_passes_bounded_pagination_to_service():
    before = UUID("00000000-0000-0000-0000-000000000020")
    with operator_client() as (client, service):
        response = client.get(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/messages",
            params={"before": str(before), "limit": 25},
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_before": None}
    service.list_operator_messages.assert_awaited_once_with(ORDER_ID, before, 25)


def test_operator_message_accepts_text_and_repeated_files():
    with operator_client() as (client, service):
        response = client.post(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/messages",
            headers={"X-Pix-Chat-Secret": "expected"},
            data={"message": "Готово"},
            files=[
                ("files", ("a.txt", b"a", "text/plain")),
                ("files", ("b.pdf", b"%PDF-1.7", "application/pdf")),
            ],
        )

    assert response.status_code == 201
    assert response.json()["sender_kind"] == "manager"
    args = service.create_manager_message.await_args.args
    assert args[:2] == (ORDER_ID, "Готово")
    assert [(item.filename, item.content) for item in args[2]] == [
        ("a.txt", b"a"),
        ("b.pdf", b"%PDF-1.7"),
    ]


def test_operator_empty_message_and_files_is_rejected_before_service():
    with operator_client() as (client, service):
        response = client.post(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/messages",
            headers={"X-Pix-Chat-Secret": "expected"},
            data={"message": "   "},
        )

    assert response.status_code == 422
    service.create_manager_message.assert_not_awaited()


def test_operator_attachment_is_scoped_to_url_order():
    with operator_client() as (client, service):
        response = client.get(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/attachments/{ATTACHMENT_ID}",
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    service.get_operator_attachment.assert_awaited_once_with(ORDER_ID, ATTACHMENT_ID)


def test_operator_malformed_order_is_the_same_generic_404():
    with operator_client() as (client, service):
        response = client.get(
            "/api_v1/chat/operator/orders/not-a-uuid/messages",
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Order not found"}
    service.list_operator_messages.assert_not_awaited()


def test_operator_malformed_attachment_is_generic_404():
    with operator_client() as (client, service):
        response = client.get(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/attachments/not-a-uuid",
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "File not found"}
    service.get_operator_attachment.assert_not_awaited()


def test_operator_lookup_outage_is_503_without_external_details():
    service = service_stub()
    service.list_operator_messages.side_effect = MoySkladOrderLookupUnavailable()
    with operator_client(service=service) as (client, _):
        response = client.get(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/messages",
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Chat temporarily unavailable"}


def test_disabled_operator_chat_fails_closed_before_service_lookup():
    with operator_client(enabled=False) as (client, service):
        response = client.get(
            f"/api_v1/chat/operator/orders/{ORDER_ID}/messages",
            headers={"X-Pix-Chat-Secret": "expected"},
        )

    assert response.status_code == 503
    service.list_operator_messages.assert_not_awaited()
