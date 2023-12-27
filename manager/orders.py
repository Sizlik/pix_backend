import json
import uuid

from db.models.orders import Order, OrderItems
from db.models.users import User
from db.repository import SQLAlchemyRepository, AbstractRepository
from db.schemas.orders import OrderCreate, OrderItemCreate, MoySkladIntegrationOrder, MoySkladIntegrationCustomerOrder


class OrderRepository(SQLAlchemyRepository):
    model = Order


class OrderItemsRepository(SQLAlchemyRepository):
    model = OrderItems


class OrderManager:
    def __init__(self, order_repo: AbstractRepository):
        self.order_repo = order_repo

    async def create_order(self, user: User, is_bitrix_deal: bool = False):
        order_id = await self.order_repo.create(user_id=user.id, is_bitrix_deal=is_bitrix_deal)
        return order_id

    async def moysklad_product_folder_insert(self, order_id: int, moysklad_data: MoySkladIntegrationOrder | MoySkladIntegrationCustomerOrder):
        moysklad_dict = moysklad_data.model_dump()
        return await self.order_repo.update(order_id, **moysklad_dict)

    async def get_user_orders(self, user: User):
        return await self.order_repo.read_all(Order.user_id == user.id)

    async def get_order_by_moysklad_customer_order_id(self, id):
        return await self.order_repo.search_one(Order.moysklad_customer_order_id == id)

    async def update_order(self, id, update_dict):
        return await self.order_repo.update(id, **update_dict)


class OrderItemsManager:
    def __init__(self, order_repo: AbstractRepository):
        self.order_repo = order_repo

    async def create_order(self, fields: OrderItemCreate):
        order_item_dict = fields.model_dump()
        order_item_id = await self.order_repo.create(**order_item_dict)
        return order_item_id

    async def create_orders(self, rows: OrderCreate, order_id):
        order_items_list = []
        for x in rows.model_dump().get("order_items"):
            x.update({"order_id": order_id})
            order_items_list.append(x)
        order_items = await self.order_repo.create_multiply(order_items_list)
        return order_items

    async def get_order_items(self, order_id: int):
        return await self.order_repo.read_all(OrderItems.order_id == order_id)

    async def moysklad_products_insert(self, moysklad_products: dict, order_items: list[OrderItems]):
        new_order_items = []
        for product, order_item in zip(moysklad_products, order_items):
            update_fields = {
                "moysklad_product_id": product.get("id"),
                "moysklad_product_meta": product.get("meta")
            }
            new_order_items.append(await self.order_repo.update(order_item.id, **update_fields))

        return new_order_items

    async def get_order_items_by_moysklad_product_ids(self, ids):
        return await self.order_repo.read_all(OrderItems.moysklad_product_id.in_(ids))

    async def update_order_item(self, id, update_data):
        return await self.order_repo.update(id, **update_data)


