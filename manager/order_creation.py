import html
import logging

from db.models.users import User
from db.schemas.orders import CheckoutOrderCreate


def build_new_order_message(order: dict, user: User) -> str:
    order_href = html.escape(order["meta"]["uuidHref"], quote=True)
    user_name = html.escape(user.first_name)
    return (
        f'<a href="{order_href}">Новый заказ</a>\n'
        f"Пользователь: {user_name} Клиент #{user.name_id}"
    )


class OrderCreationManager:
    def __init__(
        self,
        addresses,
        products,
        customer_orders,
        notifier,
        logger=None,
    ):
        self._addresses = addresses
        self._products = products
        self._customer_orders = customer_orders
        self._notifier = notifier
        self._logger = logger or logging.getLogger(__name__)

    async def create(self, request: CheckoutOrderCreate, user: User) -> dict:
        address = await self._addresses.get_for_order(user.id, request.address_id)
        products = await self._products.create_products(request, user)
        positions = [
            {"count": item.count, "moysklad_product_meta": product["meta"]}
            for product, item in zip(products, request.order_items)
        ]
        order = await self._customer_orders.create_order_by_request(
            positions, user, address
        )
        try:
            await self._addresses.mark_used(user.id, request.address_id)
        except Exception:
            self._logger.exception("failed to mark delivery address as used")
        try:
            await self._notifier.send_group_message(
                build_new_order_message(order, user)
            )
        except Exception:
            self._logger.exception("failed to send new order notification")
        return order
