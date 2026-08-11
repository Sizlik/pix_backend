from types import SimpleNamespace
from uuid import UUID

import pytest

from manager.addresses import DeliveryAddressSnapshot
from manager.moysklad import CustomerOrderManager, moysklad_delivery_payload

SNAPSHOT = DeliveryAddressSnapshot(
    name="Дом",
    city="Калининград",
    street="Ленинский проспект",
    house="10",
    postal_code="236000",
    building="корп. 2",
    apartment="15",
    delivery_comment="Позвонить за 10 минут",
)
ORDER_SYNC_ID = UUID("00000000-0000-0000-0000-000000000030")


def test_moysklad_payload_is_structured_and_preserves_privoz_comment():
    payload = moysklad_delivery_payload(SNAPSHOT)
    assert payload["shipmentAddress"] == (
        "236000, Россия, Калининград, Ленинский проспект, дом 10, "
        "корп. 2, кв./офис 15"
    )
    assert payload["shipmentAddressFull"] == {
        "postalCode": "236000",
        "city": "Калининград",
        "street": "Ленинский проспект",
        "house": "10, корп. 2",
        "apartment": "15",
        "addInfo": "Позвонить за 10 минут",
    }
    assert "comment" not in payload["shipmentAddressFull"]


class RecordingCustomerOrderRepository:
    def __init__(self):
        self.created = None

    async def get_default_company(self):
        return {"meta": {"href": "organization"}}

    async def create(self, **payload):
        self.created = payload
        return {"id": "order"}


@pytest.mark.asyncio
async def test_customer_order_creation_copies_delivery_snapshot_into_order():
    repository = RecordingCustomerOrderRepository()
    manager = CustomerOrderManager(repository)
    user = SimpleNamespace(moysklad_counterparty_meta={"href": "counterparty"})

    await manager.create_order_by_request(
        [{"count": 2, "moysklad_product_meta": {"href": "product"}}],
        user,
        SNAPSHOT,
        sync_id=ORDER_SYNC_ID,
    )

    assert repository.created["shipmentAddressFull"]["addInfo"] == (
        "Позвонить за 10 минут"
    )
    assert "comment" not in repository.created["shipmentAddressFull"]
    assert repository.created["agent"] == {
        "meta": {"href": "counterparty"}
    }
    assert repository.created["syncId"] == str(ORDER_SYNC_ID)
