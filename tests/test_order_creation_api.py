from types import SimpleNamespace

from fastapi.testclient import TestClient

from config import Settings
from dependecies.orders import get_order_creation_manager
from main import create_app
from routes.users import current_user_dependency


class StubOrderCreationManager:
    def __init__(self):
        self.calls = []

    async def create(self, request, user):
        self.calls.append((request, user))
        return {"id": "moysklad-order"}


def valid_payload():
    return {
        "address_id": "00000000-0000-0000-0000-000000000010",
        "order_items": [
            {"link": "https://shop.example/item", "count": 1, "comment": ""}
        ],
    }


def order_client(manager, authenticated=True):
    app = create_app(Settings(_env_file=None, app_env="test"))
    user = SimpleNamespace(id="user")
    if authenticated:
        app.dependency_overrides[current_user_dependency] = lambda: user
    app.dependency_overrides[get_order_creation_manager] = lambda: manager
    return TestClient(app)


def test_create_order_delegates_complete_request_to_use_case():
    manager = StubOrderCreationManager()
    with order_client(manager) as client:
        response = client.post("/api_v1/orders", json=valid_payload())
    assert response.status_code == 200
    assert manager.calls[0][0].address_id is not None


def test_create_order_rejects_missing_address_before_use_case():
    manager = StubOrderCreationManager()
    payload = valid_payload()
    payload.pop("address_id")
    with order_client(manager) as client:
        response = client.post("/api_v1/orders", json=payload)
    assert response.status_code == 422
    assert manager.calls == []


def test_create_order_requires_authentication():
    manager = StubOrderCreationManager()
    with order_client(manager, authenticated=False) as client:
        response = client.post("/api_v1/orders", json=valid_payload())
    assert response.status_code == 401
    assert manager.calls == []
