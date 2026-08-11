from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import errors
from config import Settings
from dependecies.orders import get_order_creation_manager
from main import create_app
from routes.users import current_user_dependency


class StubOrderCreationManager:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def create(self, request, user, idempotency_key=None):
        self.calls.append((request, user, idempotency_key))
        if self.error:
            raise self.error
        return {"id": "moysklad-order"}


def valid_payload():
    return {
        "address_id": "00000000-0000-0000-0000-000000000010",
        "order_items": [
            {"link": "https://shop.example/item", "count": 1, "comment": ""}
        ],
    }


IDEMPOTENCY_KEY = "00000000-0000-0000-0000-000000000020"


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
        response = client.post(
            "/api_v1/orders",
            json=valid_payload(),
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
    assert response.status_code == 200
    assert manager.calls[0][0].address_id is not None


def test_create_order_rejects_missing_address_before_use_case():
    manager = StubOrderCreationManager()
    payload = valid_payload()
    payload.pop("address_id")
    with order_client(manager) as client:
        response = client.post(
            "/api_v1/orders",
            json=payload,
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
    assert response.status_code == 422
    assert manager.calls == []


def test_create_order_requires_authentication():
    manager = StubOrderCreationManager()
    with order_client(manager, authenticated=False) as client:
        response = client.post(
            "/api_v1/orders",
            json=valid_payload(),
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
    assert response.status_code == 401
    assert manager.calls == []


@pytest.mark.parametrize(
    "order_items",
    [
        [],
        [{"link": "   ", "count": 1, "comment": ""}],
        [{"link": "https://shop.example/item", "count": 0, "comment": ""}],
        [{"link": "https://shop.example/item", "count": -1, "comment": ""}],
    ],
)
def test_create_order_rejects_empty_or_invalid_checkout_items(order_items):
    manager = StubOrderCreationManager()
    payload = valid_payload()
    payload["order_items"] = order_items
    with order_client(manager) as client:
        response = client.post(
            "/api_v1/orders",
            json=payload,
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
    assert response.status_code == 422
    assert manager.calls == []


def test_create_order_requires_uuid_idempotency_key():
    manager = StubOrderCreationManager()
    with order_client(manager) as client:
        missing = client.post("/api_v1/orders", json=valid_payload())
        malformed = client.post(
            "/api_v1/orders",
            json=valid_payload(),
            headers={"Idempotency-Key": "not-a-uuid"},
        )
    assert missing.status_code == 422
    assert malformed.status_code == 422
    assert manager.calls == []


def test_create_order_passes_valid_idempotency_key_to_use_case():
    manager = StubOrderCreationManager()
    with order_client(manager) as client:
        response = client.post(
            "/api_v1/orders",
            json=valid_payload(),
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
    assert response.status_code == 200
    assert str(manager.calls[0][2]) == IDEMPOTENCY_KEY


def test_order_idempotency_errors_are_defined():
    assert issubclass(errors.IdempotencyKeyReused, RuntimeError)
    assert issubclass(errors.OrderCreationInProgress, RuntimeError)
    assert issubclass(errors.OrderCreationIdempotencyUnavailable, RuntimeError)


@pytest.mark.parametrize(
    ("error_name", "status", "code"),
    [
        ("IdempotencyKeyReused", 409, "idempotency_key_reused"),
        ("OrderCreationInProgress", 409, "order_creation_in_progress"),
        (
            "OrderCreationIdempotencyUnavailable",
            503,
            "order_idempotency_unavailable",
        ),
    ],
)
def test_create_order_maps_idempotency_failures(error_name, status, code):
    manager = StubOrderCreationManager(getattr(errors, error_name)())
    with order_client(manager) as client:
        response = client.post(
            "/api_v1/orders",
            json=valid_payload(),
            headers={"Idempotency-Key": IDEMPOTENCY_KEY},
        )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
