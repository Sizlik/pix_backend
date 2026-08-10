from uuid import UUID

import pytest
from pydantic import ValidationError

from db.schemas.orders import (
    ExistingOrderPositionChange,
    NewOrderPositionChange,
    OrderChangesRequest,
)
from errors import InvalidOrderChanges
from manager.order_changes import (
    build_order_change_plan,
    is_order_editable,
)

POSITION_1 = UUID("00000000-0000-0000-0000-000000000001")
POSITION_2 = UUID("00000000-0000-0000-0000-000000000002")


def current_rows():
    return [
        {
            "id": str(POSITION_1),
            "quantity": 1,
            "price": 12500,
            "discount": 0,
            "vat": 0,
            "vatEnabled": False,
            "reserve": 0,
            "assortment": {"meta": {"href": "https://api.moysklad.ru/product/1"}},
        },
        {
            "id": str(POSITION_2),
            "quantity": 2,
            "price": 5000,
            "discount": 5,
            "vat": 20,
            "vatEnabled": True,
            "reserve": 1,
            "assortment": {"meta": {"href": "https://api.moysklad.ru/product/2"}},
        },
    ]


@pytest.mark.parametrize(
    ("status", "editable"),
    [
        ("Подтвержден менеджером", True),
        ("Ожидает подтверждения клиента", True),
        ("Подтвержден клиентом", True),
        ("Изменен клиентом", True),
        ("Принят к исполнению", False),
        ("Отменен", False),
    ],
)
def test_order_editability_follows_the_business_status_boundary(status, editable):
    assert is_order_editable(status) is editable


def test_request_rejects_empty_positions_duplicate_ids_and_invalid_counts():
    with pytest.raises(ValidationError):
        OrderChangesRequest(expected_updated="2026-08-10 12:00:00.000", positions=[])
    with pytest.raises(ValidationError):
        ExistingOrderPositionChange(id=POSITION_1, count=0)
    with pytest.raises(ValidationError):
        NewOrderPositionChange(link="   ", count=1, comment="")
    with pytest.raises(ValidationError):
        OrderChangesRequest(
            expected_updated="2026-08-10 12:00:00.000",
            positions=[
                ExistingOrderPositionChange(id=POSITION_1, count=1),
                ExistingOrderPositionChange(id=POSITION_1, count=2),
            ],
        )


def test_plan_counts_add_remove_and_quantity_changes():
    request = OrderChangesRequest(
        expected_updated="2026-08-10 12:00:00.000",
        positions=[
            ExistingOrderPositionChange(id=POSITION_1, count=3),
            NewOrderPositionChange(
                link="https://shop.example/item", count=1, comment="black"
            ),
        ],
    )

    plan = build_order_change_plan(current_rows(), request.positions)

    assert plan.summary.added == 1
    assert plan.summary.removed == 1
    assert plan.summary.quantity_changed == 1
    assert [item.server_position["id"] for item in plan.existing] == [str(POSITION_1)]
    assert plan.existing[0].count == 3
    assert plan.new == tuple(request.positions[1:])


def test_plan_recognizes_noop_and_rejects_unknown_position():
    no_op = build_order_change_plan(
        current_rows(),
        [
            ExistingOrderPositionChange(id=POSITION_1, count=1),
            ExistingOrderPositionChange(id=POSITION_2, count=2),
        ],
    )
    assert no_op.summary.changed is False

    with pytest.raises(InvalidOrderChanges, match="unknown position"):
        build_order_change_plan(
            current_rows(),
            [
                ExistingOrderPositionChange(
                    id=UUID("00000000-0000-0000-0000-000000000099"),
                    count=1,
                )
            ],
        )
