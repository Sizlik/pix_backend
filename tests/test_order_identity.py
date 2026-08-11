from types import SimpleNamespace
from uuid import UUID

import pytest

from db.schemas.orders import CheckoutOrderCreate
from manager.moysklad import ProductManager
from manager.order_identity import build_order_create_identity

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
KEY = UUID("00000000-0000-0000-0000-000000000020")
OTHER_KEY = UUID("00000000-0000-0000-0000-000000000021")


def test_order_create_identity_is_stable_and_distinct_per_entity():
    first = build_order_create_identity(USER_ID, KEY, 2)
    retry = build_order_create_identity(USER_ID, KEY, 2)

    assert first == retry
    assert len(first.product_sync_ids) == 2
    assert len({first.order_sync_id, *first.product_sync_ids}) == 3


def test_order_create_identity_is_scoped_by_user_and_attempt():
    original = build_order_create_identity(USER_ID, KEY, 1)
    other_user = build_order_create_identity(OTHER_USER_ID, KEY, 1)
    other_attempt = build_order_create_identity(USER_ID, OTHER_KEY, 1)

    assert original.order_sync_id != other_user.order_sync_id
    assert original.order_sync_id != other_attempt.order_sync_id
    assert original.product_sync_ids != other_user.product_sync_ids
    assert original.product_sync_ids != other_attempt.product_sync_ids


class RecordingProductRepository:
    def __init__(self):
        self.rows = None

    async def create_multiply(self, rows):
        self.rows = rows
        return [
            {"meta": {"href": f"product-{index}"}}
            for index, _ in enumerate(rows)
        ]


@pytest.mark.asyncio
async def test_checkout_products_send_supplied_sync_ids():
    request = CheckoutOrderCreate(
        address_id=UUID("00000000-0000-0000-0000-000000000010"),
        order_items=[
            {"link": "first", "count": 1, "comment": ""},
            {"link": "second", "count": 2, "comment": "note"},
        ],
    )
    identity = build_order_create_identity(USER_ID, KEY, 2)
    repository = RecordingProductRepository()

    await ProductManager(repository).create_products(
        request,
        SimpleNamespace(),
        sync_ids=identity.product_sync_ids,
    )

    assert [row["syncId"] for row in repository.rows] == [
        str(value) for value in identity.product_sync_ids
    ]
