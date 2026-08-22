from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from config import Settings
from dependecies.operator_inbox import get_operator_inbox_realtime
from dependecies.order_chat import get_operator_chat_authenticator
from main import create_app
from manager.order_chat_auth import OperatorChatAuthenticator


class RecordingRealtime:
    def __init__(self):
        self.registered = []
        self.disconnected = []

    async def register(self, room_id, websocket):
        self.registered.append((room_id, websocket))

    async def disconnect(self, room_id, websocket):
        self.disconnected.append((room_id, websocket))


@contextmanager
def socket_client(*, enabled=True):
    realtime = RecordingRealtime()
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
        app.dependency_overrides[get_operator_chat_authenticator] = lambda: (
            OperatorChatAuthenticator("expected")
        )
        app.dependency_overrides[get_operator_inbox_realtime] = lambda: realtime
        with TestClient(app) as client:
            yield client, realtime


def assert_closed(client, code, frame=None, path="/api_v1/chat/operator/inbox/ws"):
    with client.websocket_connect(path) as websocket:
        if frame is not None:
            websocket.send_json(frame)
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
    assert closed.value.code == code


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "authenticate", "secret": "wrong"},
        {"type": "authenticate"},
        {"type": "authenticate", "secret": "expected", "extra": True},
    ],
)
def test_inbox_socket_rejects_non_exact_first_frame_without_registration(frame):
    with socket_client() as (client, realtime):
        assert_closed(client, 4401, frame)

    assert realtime.registered == []


def test_inbox_socket_never_accepts_secret_from_query_string():
    with socket_client() as (client, realtime):
        assert_closed(
            client,
            4401,
            {"type": "authenticate", "secret": "wrong"},
            path="/api_v1/chat/operator/inbox/ws?secret=expected",
        )

    assert realtime.registered == []


def test_disabled_inbox_socket_closes_before_authentication():
    with socket_client(enabled=False) as (client, realtime):
        assert_closed(client, 4404)

    assert realtime.registered == []


def test_inbox_socket_registers_global_room_and_is_read_only():
    with socket_client() as (client, realtime):
        with client.websocket_connect(
            "/api_v1/chat/operator/inbox/ws"
        ) as websocket:
            websocket.send_json({"type": "authenticate", "secret": "expected"})
            assert websocket.receive_json() == {"type": "authenticated"}
            websocket.send_json({"message": "not allowed"})
            assert websocket.receive_json() == {
                "type": "error",
                "code": "operator_inbox_read_only",
            }

    assert [room for room, _ in realtime.registered] == ["global"]
    assert [room for room, _ in realtime.disconnected] == ["global"]
