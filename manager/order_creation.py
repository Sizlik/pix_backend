import hashlib
import html
import json
import logging
from uuid import UUID

from db.models.users import User
from db.schemas.orders import CheckoutOrderCreate
from manager.order_identity import build_order_create_identity


def checkout_fingerprint(request: CheckoutOrderCreate) -> str:
    canonical = {
        "address_id": str(request.address_id),
        "order_items": [
            {
                "link": item.link,
                "count": item.count,
                "comment": item.comment,
            }
            for item in request.order_items
        ],
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        idempotency,
        notifier,
        logger=None,
    ):
        self._addresses = addresses
        self._products = products
        self._customer_orders = customer_orders
        self._idempotency = idempotency
        self._notifier = notifier
        self._logger = logger or logging.getLogger(__name__)

    async def create(
        self,
        request: CheckoutOrderCreate,
        user: User,
        idempotency_key: UUID,
    ) -> dict:
        identity = build_order_create_identity(
            user.id,
            idempotency_key,
            len(request.order_items),
        )

        async def create_external_order():
            address = await self._addresses.get_for_order(
                user.id,
                request.address_id,
            )
            products = await self._products.create_products(
                request,
                user,
                sync_ids=identity.product_sync_ids,
            )
            positions = [
                {
                    "count": item.count,
                    "moysklad_product_meta": product["meta"],
                }
                for product, item in zip(products, request.order_items)
            ]
            return await self._customer_orders.create_order_by_request(
                positions,
                user,
                address,
                sync_id=identity.order_sync_id,
            )

        order, executed = await self._idempotency.run(
            user.id,
            idempotency_key,
            checkout_fingerprint(request),
            create_external_order,
        )
        if not executed:
            return order

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
