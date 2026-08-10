from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from config import Settings
from db.redis import get_redis_strategy
from dependecies.notifications import (
    get_notification_manager,
    get_notification_realtime,
)
from main import create_app
from manager.users import get_user_manager
from routes.users import current_user_dependency

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
NOTIFICATION_ID = UUID("00000000-0000-0000-0000-000000000010")


class StubNotificationManager:
    def __init__(self, count=4):
        self.count = count
        self.calls = []

    async def unread_count(self, user_id):
        self.calls.append(("count", user_id))
        return self.count

    async def read_notification(self, user_id, notification_id):
        self.calls.append(("read-one", user_id, notification_id))
        return 3

    async def read_all_notifications(self, user_id):
        self.calls.append(("read-all", user_id))
        return 0


class StubRealtime:
    def __init__(self):
        self.connected_user_ids = []
        self.disconnected_user_ids = []

    async def connect(self, user_id, websocket):
        self.connected_user_ids.append(str(user_id))
        await websocket.accept()

    async def disconnect(self, user_id, websocket):
        self.disconnected_user_ids.append(str(user_id))


class StubStrategy:
    def __init__(self, valid_user):
        self.valid_user = valid_user

    async def read_token(self, token, user_manager):
        if token == "valid-token":
            return self.valid_user
        return None


def notification_app(manager, *, authenticated=True):
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_notification_manager] = lambda: manager
    if authenticated:
        app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
            id=USER_ID
        )
    return app


def websocket_app(*, valid_user, count):
    manager = StubNotificationManager(count=count)
    realtime = StubRealtime()
    app = notification_app(manager)
    app.dependency_overrides[get_notification_realtime] = lambda: realtime
    app.dependency_overrides[get_redis_strategy] = lambda: StubStrategy(valid_user)
    app.dependency_overrides[get_user_manager] = lambda: object()
    return app, realtime


def test_count_and_read_routes_pass_only_current_user_id():
    manager = StubNotificationManager()
    with TestClient(notification_app(manager)) as client:
        count = client.get("/api_v1/notifications/unread-count")
        one = client.post(f"/api_v1/notifications/read/{NOTIFICATION_ID}")
        all_items = client.post("/api_v1/notifications/read")

    assert count.status_code == 200
    assert count.json() == {"unread_count": 4}
    assert one.json() == {"unread_count": 3}
    assert all_items.json() == {"unread_count": 0}
    assert manager.calls == [
        ("count", USER_ID),
        ("read-one", USER_ID, NOTIFICATION_ID),
        ("read-all", USER_ID),
    ]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api_v1/notifications/unread-count"),
        ("post", f"/api_v1/notifications/read/{NOTIFICATION_ID}"),
        ("post", "/api_v1/notifications/read"),
    ],
)
def test_count_and_read_routes_require_authentication(method, path):
    with TestClient(
        notification_app(StubNotificationManager(), authenticated=False)
    ) as client:
        response = client.request(method, path)
    assert response.status_code == 401


def test_notification_websocket_sends_initial_authoritative_count():
    user = SimpleNamespace(id=USER_ID)
    app, realtime = websocket_app(valid_user=user, count=7)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api_v1/notifications/ws?auth=valid-token"
        ) as websocket:
            assert websocket.receive_json() == {
                "type": "notification_count",
                "unread_count": 7,
            }

    assert realtime.connected_user_ids == [str(USER_ID)]
    assert realtime.disconnected_user_ids == [str(USER_ID)]


@pytest.mark.parametrize(
    "path",
    [
        "/api_v1/notifications/ws",
        "/api_v1/notifications/ws?auth=invalid-token",
    ],
)
def test_notification_websocket_rejects_missing_and_invalid_tokens(path):
    app, realtime = websocket_app(valid_user=None, count=0)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(path):
                pass

    assert closed.value.code == 4401
    assert realtime.connected_user_ids == []
