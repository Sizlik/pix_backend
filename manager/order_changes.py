from dataclasses import dataclass
from typing import Protocol

from db.models.users import User
from db.schemas.orders import (
    ExistingOrderPositionChange,
    NewOrderPositionChange,
    OrderChangesRequest,
    OrderChangesResponse,
    OrderCreate,
    OrderItemCreate,
    OrderPositionChange,
)
from errors import (
    InvalidOrderChanges,
    OrderNotAccessible,
    OrderNotEditable,
    OrderVersionConflict,
)

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


class CustomerOrderGateway(Protocol):
    async def get_order_by_id(self, order_id) -> dict: ...

    async def get_state_meta(self, state_name: str) -> dict: ...

    async def replace_positions_and_state(
        self, order_id, positions: list[dict], state_meta: dict
    ) -> dict: ...


class ProductGateway(Protocol):
    async def create_products(self, order: OrderCreate, user: User) -> list[dict]: ...


def serialize_existing_position(item: ExistingPositionUpdate) -> dict:
    row = item.server_position
    result = {
        "id": str(row["id"]),
        "quantity": item.count,
        "price": row["price"],
        "discount": row["discount"],
        "vat": row["vat"],
        "vatEnabled": row.get("vatEnabled", False),
        "reserve": min(float(row.get("reserve", 0)), item.count),
        "assortment": {"meta": row["assortment"]["meta"]},
    }
    for optional_field in ("pack", "taxSystem"):
        if optional_field in row:
            result[optional_field] = row[optional_field]
    return result


def serialize_new_position(item: NewOrderPositionChange, product: dict) -> dict:
    return {
        "quantity": item.count,
        "price": 0,
        "discount": 0,
        "vat": 0,
        "vatEnabled": False,
        "reserve": 0,
        "assortment": {"meta": product["meta"]},
    }


def _existing_request_rows(order: dict) -> list[ExistingOrderPositionChange]:
    return [
        ExistingOrderPositionChange(id=row["id"], count=int(row["quantity"]))
        for row in order["positions"]["rows"]
    ]


class OrderChangesManager:
    def __init__(
        self,
        customer_orders: CustomerOrderGateway,
        products: ProductGateway,
    ) -> None:
        self._customer_orders = customer_orders
        self._products = products

    @staticmethod
    def _validate_context(order: dict, user: User, expected_updated: str) -> None:
        agent_href = order.get("agent", {}).get("meta", {}).get("href", "")
        if agent_href.rsplit("/", 1)[-1] != str(user.moysklad_counterparty_id):
            raise OrderNotAccessible()
        status = order.get("state", {}).get("name", "")
        if not is_order_editable(status):
            raise OrderNotEditable(status)
        if order.get("updated") != expected_updated:
            raise OrderVersionConflict()

    async def save_changes(
        self,
        user: User,
        order_id,
        request: OrderChangesRequest,
    ) -> OrderChangesResponse:
        order = await self._customer_orders.get_order_by_id(order_id)
        if not order or not order.get("id"):
            raise OrderNotAccessible()
        return await self._save_loaded_order(user, order_id, order, request)

    async def _save_loaded_order(
        self,
        user: User,
        order_id,
        order: dict,
        request: OrderChangesRequest,
    ) -> OrderChangesResponse:
        self._validate_context(order, user, request.expected_updated)
        plan = build_order_change_plan(order["positions"]["rows"], request.positions)
        if not plan.summary.changed:
            return OrderChangesResponse(order=order, changed=False)

        state_meta = await self._customer_orders.get_state_meta(TARGET_ORDER_STATUS)
        product_rows = OrderCreate(
            order_items=[
                OrderItemCreate(link=item.link, count=item.count, comment=item.comment)
                for item in plan.new
            ]
        )
        products = (
            await self._products.create_products(product_rows, user)
            if plan.new
            else []
        )
        positions = [serialize_existing_position(item) for item in plan.existing]
        positions.extend(
            serialize_new_position(item, product)
            for item, product in zip(plan.new, products, strict=True)
        )
        updated_order = await self._customer_orders.replace_positions_and_state(
            order_id, positions, state_meta
        )

        return OrderChangesResponse(
            order=updated_order,
            changed=True,
        )

    async def _load_for_legacy_change(self, user: User, order_id) -> dict:
        order = await self._customer_orders.get_order_by_id(order_id)
        if not order or not order.get("id"):
            raise OrderNotAccessible()
        self._validate_context(order, user, order["updated"])
        return order

    async def change_quantity(
        self,
        user: User,
        order_id,
        position_id,
        count: int,
    ) -> OrderChangesResponse:
        order = await self._load_for_legacy_change(user, order_id)
        requested = []
        found = False
        for item in _existing_request_rows(order):
            if str(item.id) == str(position_id):
                requested.append(
                    ExistingOrderPositionChange(id=item.id, count=count)
                )
                found = True
            else:
                requested.append(item)
        if not found:
            raise InvalidOrderChanges("unknown position id")
        request = OrderChangesRequest(
            expected_updated=order["updated"], positions=requested
        )
        return await self._save_loaded_order(user, order_id, order, request)

    async def remove_position(
        self,
        user: User,
        order_id,
        position_id,
    ) -> OrderChangesResponse:
        order = await self._load_for_legacy_change(user, order_id)
        requested = [
            item
            for item in _existing_request_rows(order)
            if str(item.id) != str(position_id)
        ]
        if len(requested) == len(order["positions"]["rows"]):
            raise InvalidOrderChanges("unknown position id")
        if not requested:
            raise InvalidOrderChanges("order must contain at least one position")
        request = OrderChangesRequest(
            expected_updated=order["updated"], positions=requested
        )
        return await self._save_loaded_order(user, order_id, order, request)

    async def add_positions(
        self,
        user: User,
        order_id,
        additions: OrderCreate,
    ) -> OrderChangesResponse:
        order = await self._load_for_legacy_change(user, order_id)
        requested: list[OrderPositionChange] = _existing_request_rows(order)
        requested.extend(
            NewOrderPositionChange(
                link=item.link,
                count=item.count,
                comment=item.comment,
            )
            for item in additions.order_items
        )
        request = OrderChangesRequest(
            expected_updated=order["updated"], positions=requested
        )
        return await self._save_loaded_order(user, order_id, order, request)
