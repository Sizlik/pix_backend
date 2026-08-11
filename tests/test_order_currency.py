from types import SimpleNamespace

import pytest

from manager import moysklad


class RecordingCustomerOrderRepository:
    def __init__(self):
        self.read_one_link = None
        self.read_all_filter = None

    async def read_one(self, order_id, **kwargs):
        self.read_one_link = kwargs.get("link")
        return {
            "id": str(order_id),
            "rate": {"currency": {"isoCode": "usd"}},
        }

    async def read_all(self, filter="", **kwargs):
        self.read_all_filter = filter
        return {
            "rows": [
                {
                    "id": "order-usd",
                    "rate": {"currency": {"isoCode": "USD"}},
                },
                {
                    "id": "order-without-currency",
                    "rate": {"currency": {}},
                },
            ]
        }


def test_enrich_order_currency_uses_only_non_empty_iso_code():
    enrich = getattr(moysklad, "enrich_order_currency", None)
    assert enrich is not None

    order = {"rate": {"currency": {"isoCode": " pln "}}}
    assert enrich(order)["currency_code"] == "PLN"

    incomplete = {"rate": {"currency": {}}}
    assert enrich(incomplete) is incomplete
    assert "currency_code" not in incomplete


@pytest.mark.asyncio
async def test_single_order_expands_and_returns_currency():
    repository = RecordingCustomerOrderRepository()
    result = await moysklad.CustomerOrderManager(repository).get_order_by_id(
        "order-usd"
    )

    assert repository.read_one_link == (
        "expand=positions.assortment,state,rate.currency"
    )
    assert result["currency_code"] == "USD"


@pytest.mark.asyncio
async def test_order_list_expands_and_enriches_each_currency_independently():
    repository = RecordingCustomerOrderRepository()
    user = SimpleNamespace(moysklad_counterparty_id="counterparty-1")

    result = await moysklad.CustomerOrderManager(repository).get_orders_by_user(
        user
    )

    assert "expand=state,rate.currency" in repository.read_all_filter
    assert result["rows"][0]["currency_code"] == "USD"
    assert "currency_code" not in result["rows"][1]
