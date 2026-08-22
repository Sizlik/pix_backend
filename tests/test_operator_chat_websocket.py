import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from config import Settings
from dependecies.chat import get_chat_realtime
from dependecies.order_chat import get_operator_chat_authenticator, get_order_chat_service
from errors import MoySkladOrderLookupUnavailable
from main import create_app
from manager.order_chat import OrderChatNotFound
from manager.order_chat_auth import OperatorChatAuthenticator
from routes.operator_chat import (
    receive_operator_authentication,
    register_authenticated_socket,
)

ORDER_ID = "00000000-0000-0000-0000-000000000001"


class SocketStub:
    def __init__(self, frames):
        self.frames = list(frames)

    async def receive_json(self):
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame


class BlockingSocketStub:
    async def receive_json(self):
        await asyncio.Event().wait()


async def test_first_frame_authentication_accepts_only_exact_shape():
    accepted = SocketStub(frames=[{"type": "authenticate", "secret": "expected"}])
    wrong = SocketStub(frames=[{"type": "authenticate", "secret": "no"}])

    assert await receive_operator_authentication(
        accepted,
        OperatorChatAuthenticator("expected"),
        timeout_seconds=0.1,
    ) is True
    assert await receive_operator_authentication(
        wrong,
        OperatorChatAuthenticator("expected"),
        timeout_seconds=0.1,
    ) is False


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "authenticate"},
        {"type": "authenticate", "secret": "expected", "extra": True},
        ["authenticate", "expected"],
        ValueError("invalid JSON"),
    ],
)
async def test_first_frame_authentication_rejects_every_non_exact_shape(frame):
    assert await receive_operator_authentication(
        SocketStub(frames=[frame]),
        OperatorChatAuthenticator("expected"),
        timeout_seconds=0.1,
    ) is False


async def test_first_frame_timeout_fails_closed():
    assert await receive_operator_authentication(
        BlockingSocketStub(),
        OperatorChatAuthenticator("expected"),
        timeout_seconds=0,
    ) is False


class RecordingRealtime:
    def __init__(self, sequence):
        self.sequence = sequence
        self.registered = []
        self.disconnected = []

    async def register(self, room_id, websocket):
        self.sequence.append("register")
        self.registered.append((room_id, websocket))

    async def disconnect(self, room_id, websocket):
        self.disconnected.append((room_id, websocket))


async def test_room_registration_precedes_authenticated_acknowledgement():
    sequence = []
    realtime = RecordingRealtime(sequence)

    class RecordingSocket:
        async def send_json(self, value):
            sequence.append(("send", value))

    await register_authenticated_socket(
        RecordingSocket(),
        realtime,
        ORDER_ID,
    )

    assert sequence == [
        "register",
        ("send", {"type": "authenticated"}),
    ]


def storage_stub():
    return SimpleNamespace(ensure_bucket=AsyncMock())


@contextmanager
def socket_client(*, enabled=True, prepare_failure=None):
    sequence = []

    async def prepare(order_id):
        sequence.append("prepare")
        if prepare_failure is not None:
            raise prepare_failure

    service = SimpleNamespace(prepare_operator_order=AsyncMock(side_effect=prepare))
    realtime = RecordingRealtime(sequence)
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
            OperatorChatAuthenticator("expected")
        )
        app.dependency_overrides[get_chat_realtime] = lambda: realtime
        with TestClient(app) as client:
            yield client, service, realtime, sequence


def assert_socket_close(client, path, code, frame=None, *, raw_text=None):
    with client.websocket_connect(path) as websocket:
        if raw_text is not None:
            websocket.send_text(raw_text)
        elif frame is not None:
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
        ["authenticate", "expected"],
    ],
)
def test_operator_socket_invalid_auth_closes_without_registration(frame):
    with socket_client() as (client, service, realtime, sequence):
        assert_socket_close(
            client,
            f"/api_v1/chat/operator/ws?room={ORDER_ID}",
            4401,
            frame,
        )

    service.prepare_operator_order.assert_not_awaited()
    assert realtime.registered == []
    assert sequence == []


def test_operator_socket_invalid_json_closes_without_registration():
    with socket_client() as (client, service, realtime, _):
        assert_socket_close(
            client,
            f"/api_v1/chat/operator/ws?room={ORDER_ID}",
            4401,
            raw_text="{",
        )

    service.prepare_operator_order.assert_not_awaited()
    assert realtime.registered == []


@pytest.mark.parametrize("path", ["/api_v1/chat/operator/ws", "/api_v1/chat/operator/ws?room=bad"])
def test_operator_socket_missing_or_malformed_room_closes_before_authentication(path):
    with socket_client() as (client, service, realtime, _):
        assert_socket_close(client, path, 4404)

    service.prepare_operator_order.assert_not_awaited()
    assert realtime.registered == []


@pytest.mark.parametrize(
    "failure",
    [OrderChatNotFound(), MoySkladOrderLookupUnavailable()],
)
def test_operator_socket_inaccessible_or_unavailable_order_never_registers(failure):
    with socket_client(prepare_failure=failure) as (client, service, realtime, sequence):
        assert_socket_close(
            client,
            f"/api_v1/chat/operator/ws?room={ORDER_ID}",
            4404,
            {"type": "authenticate", "secret": "expected"},
        )

    service.prepare_operator_order.assert_awaited_once()
    assert realtime.registered == []
    assert sequence == ["prepare"]


def test_disabled_operator_socket_closes_before_authentication_or_registration():
    with socket_client(enabled=False) as (client, service, realtime, sequence):
        assert_socket_close(
            client,
            f"/api_v1/chat/operator/ws?room={ORDER_ID}",
            4404,
        )

    service.prepare_operator_order.assert_not_awaited()
    assert realtime.registered == []
    assert sequence == []


def test_operator_socket_registers_only_after_order_access_and_rejects_writes():
    with socket_client() as (client, service, realtime, sequence):
        with client.websocket_connect(
            f"/api_v1/chat/operator/ws?room={ORDER_ID}"
        ) as websocket:
            websocket.send_json({"type": "authenticate", "secret": "expected"})
            assert websocket.receive_json() == {"type": "authenticated"}
            assert sequence == ["prepare", "register"]
            websocket.send_json({"message": "must use REST"})
            assert websocket.receive_json() == {
                "type": "error",
                "code": "order_chat_http_required",
            }

    service.prepare_operator_order.assert_awaited_once()
    assert len(realtime.registered) == 1
    assert len(realtime.disconnected) == 1
