from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient

from config import Settings
from db.models.users import get_user_db
from db.redis import get_redis_strategy
from db.schemas.chat import (
    OrderChatAttachmentResponse,
    OrderChatMessageResponse,
    OrderChatPageResponse,
    SenderKind,
)
from dependecies.chat import get_chat_manager
from dependecies.notifications import get_notification_manager
from dependecies.order_chat import get_order_chat_access_policy, get_order_chat_service
from main import create_app
from manager.order_chat import DownloadedAttachment, OrderChatNotFound
from manager.users import get_user_manager
from routes.users import current_user_dependency

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")


class StubOrderChatService:
    async def list_messages(self, user, order_id, before, limit):
        return OrderChatPageResponse(items=[], next_before=None)

    async def create_client_message(self, user, order_id, body, uploads):
        return OrderChatMessageResponse(
            id=UUID("00000000-0000-0000-0000-000000000010"),
            order_id=order_id,
            sender_kind=SenderKind.CLIENT,
            sender_label="Клиент",
            message=body.strip(),
            created_at=datetime.now(timezone.utc),
            attachments=[
                OrderChatAttachmentResponse(
                    id=UUID(f"00000000-0000-0000-0000-{index + 20:012d}"),
                    filename=upload.filename,
                    mime_type="application/octet-stream",
                    size_bytes=len(upload.content),
                )
                for index, upload in enumerate(uploads)
            ],
            delivery_state="pending",
        )

    async def get_attachment(self, user, attachment_id):
        if str(attachment_id).endswith("999"):
            raise OrderChatNotFound()
        return DownloadedAttachment(
            filename="фото.jpg",
            mime_type="image/jpeg",
            content=b"image",
        )


def order_chat_client(authenticated=True):
    app = create_app(Settings(_env_file=None, app_env="test"))
    if authenticated:
        app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000002")
        )
    app.dependency_overrides[get_order_chat_service] = StubOrderChatService
    return TestClient(app)


def test_order_message_accepts_text_and_repeated_files():
    with order_chat_client() as client:
        response = client.post(
            f"/api_v1/chat/orders/{ORDER_ID}/messages",
            data={"message": "Где заказ?"},
            files=[
                ("files", ("a.txt", b"a", "text/plain")),
                ("files", ("b.pdf", b"%PDF-1.7", "application/pdf")),
            ],
            headers={"Authorization": "Bearer test"},
        )

    assert response.status_code == 201
    assert response.json()["message"] == "Где заказ?"
    assert len(response.json()["attachments"]) == 2


def test_empty_message_and_files_is_rejected():
    with order_chat_client() as client:
        response = client.post(
            f"/api_v1/chat/orders/{ORDER_ID}/messages",
            data={"message": "   "},
            headers={"Authorization": "Bearer test"},
        )

    assert response.status_code == 422


def test_history_limit_is_bounded():
    with order_chat_client() as client:
        response = client.get(
            f"/api_v1/chat/orders/{ORDER_ID}/messages?limit=101",
            headers={"Authorization": "Bearer test"},
        )

    assert response.status_code == 422


def test_attachment_download_is_authenticated_and_encoded():
    attachment_id = UUID("00000000-0000-0000-0000-000000000201")
    with order_chat_client() as client:
        response = client.get(
            f"/api_v1/chat/attachments/{attachment_id}",
            headers={"Authorization": "Bearer test"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.content == b"image"


def test_attachment_download_requires_authentication():
    attachment_id = UUID("00000000-0000-0000-0000-000000000201")
    with order_chat_client(authenticated=False) as client:
        response = client.get(f"/api_v1/chat/attachments/{attachment_id}")

    assert response.status_code == 401


def test_legacy_order_reply_endpoint_requires_moysklad_comment():
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        email="bot@pixlogistic.com",
    )
    app.dependency_overrides[get_chat_manager] = lambda: SimpleNamespace()
    app.dependency_overrides[get_notification_manager] = lambda: SimpleNamespace()
    app.dependency_overrides[get_user_db] = lambda: SimpleNamespace()

    with TestClient(app) as client:
        response = client.post(
            "/api_v1/chat/send_message",
            json={
                "message": "old reply",
                "to_chat_room": str(ORDER_ID),
                "client_id": "00000000-0000-0000-0000-000000000002",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == ("order_reply_in_moysklad_required")


class SocketTokenStrategy:
    def __init__(self, user):
        self.user = user

    async def read_token(self, token, user_manager):
        return self.user


class SocketChatManager:
    def __init__(self):
        self.persisted = []

    async def connect(self, room_id, websocket):
        await websocket.accept()

    async def disconnect(self, room_id, websocket):
        return None

    async def send_message_from_client(self, *args):
        self.persisted.append(args)


def test_order_websocket_rejects_client_writes_in_favor_of_http():
    app = create_app(Settings(_env_file=None, app_env="test"))
    user = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        moysklad_counterparty_id=UUID("00000000-0000-0000-0000-000000000003"),
    )
    manager = SocketChatManager()
    policy = SimpleNamespace(assert_client_access=AsyncMock(return_value={}))
    app.dependency_overrides[get_redis_strategy] = lambda: SocketTokenStrategy(user)
    app.dependency_overrides[get_user_manager] = lambda: object()
    app.dependency_overrides[get_chat_manager] = lambda: manager
    app.dependency_overrides[get_order_chat_access_policy] = lambda: policy

    with TestClient(app) as client:
        with client.websocket_connect(f"/api_v1/chat/ws?auth=token&room={ORDER_ID}") as socket:
            socket.send_json({"message": "must not persist"})
            assert socket.receive_json() == {
                "type": "error",
                "code": "order_chat_http_required",
            }

    assert manager.persisted == []
