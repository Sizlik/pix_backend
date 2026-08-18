from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from config import Settings
from db.schemas.orders import OrderChangesResponse
from dependecies.orders import get_order_changes_manager
from errors import (
    MoySkladOrderStateMissing,
    OrderNotAccessible,
    OrderNotEditable,
    OrderVersionConflict,
)
from main import create_app
from routes.users import current_user_dependency

ORDER_ID = "00000000-0000-0000-0000-000000000010"
POSITION_ID = "00000000-0000-0000-0000-000000000001"


class StubOrderChangesManager:
    def __init__(self, result=None, error=None):
        self.result = result or OrderChangesResponse(
            order={"id": ORDER_ID, "state": {"name": "Изменен клиентом"}},
            changed=True,
            notification_sent=True,
        )
        self.error = error
        self.calls = []

    async def save_changes(self, user, order_id, request):
        self.calls.append((user, str(order_id), request))
        if self.error:
            raise self.error
        return self.result

    async def change_quantity(self, user, order_id, position_id, count):
        self.calls.append(
            ("quantity", user, str(order_id), str(position_id), count)
        )
        if self.error:
            raise self.error
        return self.result

    async def remove_position(self, user, order_id, position_id):
        self.calls.append(("remove", user, str(order_id), str(position_id)))
        if self.error:
            raise self.error
        return self.result

    async def add_positions(self, user, order_id, order):
        self.calls.append(("add", user, str(order_id), order))
        if self.error:
            raise self.error
        return self.result


def order_changes_client(manager):
    app = create_app(Settings(_env_file=None, app_env="test"))
    user = SimpleNamespace(id="user", moysklad_counterparty_id="counterparty")
    app.dependency_overrides[current_user_dependency] = lambda: user
    app.dependency_overrides[get_order_changes_manager] = lambda: manager
    return TestClient(app), user


def valid_payload():
    return {
        "expected_updated": "2026-08-10 12:00:00.000",
        "positions": [{"id": POSITION_ID, "count": 2}],
    }


def test_batch_endpoint_returns_typed_result_without_live_integrations():
    manager = StubOrderChangesManager()
    client, user = order_changes_client(manager)

    with client:
        response = client.put(
            f"/api_v1/orders/{ORDER_ID}/changes", json=valid_payload()
        )

    assert response.status_code == 200
    assert response.json()["notification_sent"] is True
    assert manager.calls[0][0] is user
    assert manager.calls[0][1] == ORDER_ID


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (OrderNotAccessible(), 404, "order_not_found"),
        (OrderNotEditable("Принят к исполнению"), 409, "order_not_editable"),
        (OrderVersionConflict(), 409, "order_version_conflict"),
        (
            MoySkladOrderStateMissing("Изменен клиентом"),
            503,
            "moysklad_order_state_missing",
        ),
    ],
)
def test_batch_endpoint_maps_domain_errors(error, status_code, code):
    client, _ = order_changes_client(StubOrderChangesManager(error=error))
    with client:
        response = client.put(
            f"/api_v1/orders/{ORDER_ID}/changes", json=valid_payload()
        )
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code


def test_batch_endpoint_rejects_empty_order_before_manager_call():
    manager = StubOrderChangesManager()
    client, _ = order_changes_client(manager)
    payload = {**valid_payload(), "positions": []}
    with client:
        response = client.put(f"/api_v1/orders/{ORDER_ID}/changes", json=payload)
    assert response.status_code == 422
    assert manager.calls == []


def test_batch_endpoint_requires_authentication():
    app = create_app(Settings(_env_file=None, app_env="test"))
    with TestClient(app) as client:
        response = client.put(
            f"/api_v1/orders/{ORDER_ID}/changes", json=valid_payload()
        )
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "json_body", "operation"),
    [
        (
            "put",
            f"/api_v1/orders/{ORDER_ID}/positions/{POSITION_ID}",
            3,
            "quantity",
        ),
        (
            "delete",
            f"/api_v1/orders/{ORDER_ID}/positions/{POSITION_ID}",
            None,
            "remove",
        ),
        (
            "put",
            f"/api_v1/orders/{ORDER_ID}/positions",
            {
                "order_items": [
                    {
                        "link": "https://shop.example/new",
                        "count": 1,
                        "comment": "",
                    }
                ]
            },
            "add",
        ),
    ],
)
def test_legacy_mutation_routes_use_order_changes_manager(
    method, path, json_body, operation
):
    manager = StubOrderChangesManager()
    client, _ = order_changes_client(manager)
    with client:
        response = client.request(method.upper(), path, json=json_body)
    assert response.status_code == 200
    assert response.json()["state"]["name"] == "Изменен клиентом"
    assert manager.calls[0][0] == operation


def test_legacy_mutation_route_maps_locked_status_to_conflict():
    manager = StubOrderChangesManager(
        error=OrderNotEditable("Принят к исполнению")
    )
    client, _ = order_changes_client(manager)
    with client:
        response = client.put(
            f"/api_v1/orders/{ORDER_ID}/positions/{POSITION_ID}",
            json=2,
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "order_not_editable"
