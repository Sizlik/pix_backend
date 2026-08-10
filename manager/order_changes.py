from dataclasses import dataclass

from db.schemas.orders import (
    ExistingOrderPositionChange,
    NewOrderPositionChange,
    OrderPositionChange,
)
from errors import InvalidOrderChanges

EDITABLE_ORDER_STATUSES = frozenset(
    {
        "Подтвержден менеджером",
        "Ожидает подтверждения клиента",
        "Подтвержден клиентом",
        "Изменен клиентом",
    }
)
TARGET_ORDER_STATUS = "Изменен клиентом"


def is_order_editable(status: str) -> bool:
    return status in EDITABLE_ORDER_STATUSES


@dataclass(frozen=True)
class ExistingPositionUpdate:
    server_position: dict
    count: int


@dataclass(frozen=True)
class OrderChangeSummary:
    added: int
    removed: int
    quantity_changed: int

    @property
    def changed(self) -> bool:
        return any((self.added, self.removed, self.quantity_changed))


@dataclass(frozen=True)
class OrderChangePlan:
    existing: tuple[ExistingPositionUpdate, ...]
    new: tuple[NewOrderPositionChange, ...]
    summary: OrderChangeSummary


def build_order_change_plan(
    current_rows: list[dict],
    requested_positions: list[OrderPositionChange],
) -> OrderChangePlan:
    current_by_id = {str(row["id"]): row for row in current_rows}
    requested_existing = [
        item
        for item in requested_positions
        if isinstance(item, ExistingOrderPositionChange)
    ]
    requested_new = tuple(
        item
        for item in requested_positions
        if isinstance(item, NewOrderPositionChange)
    )
    requested_ids = {str(item.id) for item in requested_existing}
    unknown_ids = requested_ids - current_by_id.keys()
    if unknown_ids:
        raise InvalidOrderChanges("unknown position id")

    existing = tuple(
        ExistingPositionUpdate(current_by_id[str(item.id)], item.count)
        for item in requested_existing
    )
    quantity_changed = sum(
        int(float(item.server_position["quantity"]) != item.count)
        for item in existing
    )
    summary = OrderChangeSummary(
        added=len(requested_new),
        removed=len(current_by_id.keys() - requested_ids),
        quantity_changed=quantity_changed,
    )
    return OrderChangePlan(existing=existing, new=requested_new, summary=summary)
