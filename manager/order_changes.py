import logging
from dataclasses import dataclass
from html import escape
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

logger = logging.getLogger(__name__)

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


class GroupNotifier(Protocol):
    async def send_group_message(self, text: str) -> None: ...


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


def format_order_change_message(
    order: dict, user: User, summary: OrderChangeSummary
) -> str:
    href = escape(order["meta"]["uuidHref"], quote=True)
    order_name = escape(str(order.get("name", order["id"])))
    first_name = escape(str(user.first_name))
    return (
        f'<a href="{href}">Заказ #{order_name}</a> изменён клиентом\n'
        f"Пользователь: {first_name} Клиент #{user.name_id}\n"
        f"Добавлено: {summary.added}\n"
        f"Удалено: {summary.removed}\n"
        f"Количество изменено: {summary.quantity_changed}\n"
        f"Статус: <b>{TARGET_ORDER_STATUS}</b>"
    )


class OrderChangesManager:
    def __init__(
        self,
        customer_orders: CustomerOrderGateway,
        products: ProductGateway,
        notifier: GroupNotifier,
    ) -> None:
        self._customer_orders = customer_orders
        self._products = products
        self._notifier = notifier

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
        self._validate_context(order, user, request.expected_updated)
        plan = build_order_change_plan(order["positions"]["rows"], request.positions)
        if not plan.summary.changed:
            return OrderChangesResponse(
                order=order, changed=False, notification_sent=None
            )

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
        state_meta = await self._customer_orders.get_state_meta(TARGET_ORDER_STATUS)
        updated_order = await self._customer_orders.replace_positions_and_state(
            order_id, positions, state_meta
        )

        notification_sent = True
        try:
            await self._notifier.send_group_message(
                format_order_change_message(updated_order, user, plan.summary)
            )
        except Exception:
            logger.warning("Telegram order-change notification failed")
            notification_sent = False
        return OrderChangesResponse(
            order=updated_order,
            changed=True,
            notification_sent=notification_sent,
        )
