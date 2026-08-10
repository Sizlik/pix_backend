from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from config import Settings
from db.schemas.addresses import AddressListResponse, AddressRead
from dependecies.addresses import get_address_manager
from errors import AddressNameConflict, AddressNotFound
from main import create_app
from routes.users import current_user_dependency

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
ADDRESS_ID = UUID("00000000-0000-0000-0000-000000000010")
NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def address_read():
    return AddressRead(
        id=ADDRESS_ID,
        name="Дом",
        city="Калининград",
        street="Ленинский проспект",
        house="10",
        postal_code="236000",
        building=None,
        apartment="15",
        delivery_comment=None,
        is_default=True,
        created_at=NOW,
        updated_at=NOW,
        last_used_at=NOW,
    )


class StubAddressManager:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def maybe_raise(self):
        if self.error:
            raise self.error

    async def list(self, user_id, search, limit, offset):
        self.calls.append(("list", user_id, search, limit, offset))
        self.maybe_raise()
        return AddressListResponse(
            items=[address_read()], total=1, limit=limit, offset=offset
        )

    async def create(self, user_id, request):
        self.calls.append(("create", user_id, request))
        self.maybe_raise()
        return address_read()

    async def update(self, user_id, address_id, request):
        self.calls.append(("update", user_id, address_id, request))
        self.maybe_raise()
        return address_read()

    async def delete(self, user_id, address_id):
        self.calls.append(("delete", user_id, address_id))
        self.maybe_raise()


def client_for(manager):
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
        id=USER_ID
    )
    app.dependency_overrides[get_address_manager] = lambda: manager
    return TestClient(app)


def test_list_is_authenticated_paginated_and_user_scoped():
    manager = StubAddressManager()
    with client_for(manager) as client:
        response = client.get("/api_v1/addresses?search=дом&limit=20&offset=0")
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Дом"
    assert manager.calls == [("list", USER_ID, "дом", 20, 0)]


def valid_payload():
    return {
        "name": "Дом",
        "city": "Калининград",
        "street": "Ленинский проспект",
        "house": "10",
    }


def test_create_update_and_delete_status_contracts():
    manager = StubAddressManager()
    with client_for(manager) as client:
        created = client.post("/api_v1/addresses", json=valid_payload())
        updated = client.patch(
            f"/api_v1/addresses/{ADDRESS_ID}", json={"house": "12"}
        )
        deleted = client.delete(f"/api_v1/addresses/{ADDRESS_ID}")
    assert created.status_code == 201
    assert updated.status_code == 200
    assert deleted.status_code == 204
    assert [call[0] for call in manager.calls] == ["create", "update", "delete"]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AddressNotFound(), 404, "address_not_found"),
        (AddressNameConflict(), 409, "address_name_conflict"),
    ],
)
def test_domain_errors_have_stable_http_shape(error, status, code):
    with client_for(StubAddressManager(error)) as client:
        response = client.post("/api_v1/addresses", json=valid_payload())
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


def test_invalid_limit_is_rejected_before_manager_call():
    manager = StubAddressManager()
    with client_for(manager) as client:
        response = client.get("/api_v1/addresses?limit=101")
    assert response.status_code == 422
    assert manager.calls == []


def test_address_api_requires_authentication():
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_address_manager] = lambda: StubAddressManager()
    with TestClient(app) as client:
        response = client.get("/api_v1/addresses")
    assert response.status_code == 401
