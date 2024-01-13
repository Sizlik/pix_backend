import base64
import os

import requests

from db.models.orders import Order, OrderItems
from db.models.users import User
from db.repository import MoySkladRepository, AbstractRepository
from db.schemas import moysklad
from db.schemas.orders import OrderCreate


def set_organization():
    link = "https://api.moysklad.ru/api/remap/1.2/context/usersettings"
    login = os.getenv("MOYSKLAD_LOGIN")
    password = os.getenv("MOYSKLAD_PASWORD")
    headers = {"Authorization": f'Basic {base64.b64encode(f"{login}:{password}".encode("UTF-8")).decode("utf-8")}'}
    return requests.get(link, headers=headers).json()["defaultCompany"]


organization = set_organization()


class CounterpartyRepository(MoySkladRepository):
    model = "entity/counterparty"


class CounterpartyReportRepository(MoySkladRepository):
    model = "report/counterparty"


class ProductRepository(MoySkladRepository):
    model = "entity/product"


class ProductFolderRepository(MoySkladRepository):
    model = "entity/productfolder"


class CustomerOrderRepository(MoySkladRepository):
    model = "entity/customerorder"


class InvoiceOutRepository(MoySkladRepository):
    model = "entity/invoiceout"


class PaymentInRepository(MoySkladRepository):
    model = "entity/paymentin"


class CounterpartyManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_user_counterparty(self, counterparty_data: moysklad.CounterpartyCreate):
        counterparty_dict = counterparty_data.model_dump()
        return await self.__repo.create(**counterparty_dict)


class CounterpartyReportManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def get_user_counterparty_report(self, user):
        return await self.__repo.read_one(user.moysklad_counterparty_id)


class ProductFolderManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_product_folder(self, product_folder_data: moysklad.ProductFolderCreate):
        product_folder_dict = product_folder_data.model_dump()
        return await self.__repo.create(**product_folder_dict)


class ProductManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_products_from_orders(self, order_items: list[OrderItems], product_folder_meta: dict, order_id: int, user: User):
        products = []
        for order_item in order_items:
            product = moysklad.ProductCreate(
                name=f"{order_item.link} - Заказ: #{order_id} - {user.last_name} {user.first_name} - {user.email}",
                description=f"""id на pixlogistic: {order_item.id}
Комментарий: {order_item.comment}
Телефон: {user.phone_number}
""",
                productFolder={"meta": product_folder_meta},
            ).model_dump()
            products.append(product)

        return await self.__repo.create_multiply(products)

    async def create_products(self, order: OrderCreate, user: User):
        products = []
        for item in order.order_items:
            product = moysklad.ProductCreate(
                name=f"{item.link} - {user.last_name} {user.first_name} - {user.email}",
                description=f"Комментарий: {item.comment}\nТелефон: {user.phone_number}",
            ).model_dump()

            products.append(product)

        return await self.__repo.create_multiply(products)


class CustomerOrderManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_order(self, order_items: list[OrderItems], user: User):
        positions = []
        for order_item in order_items:
            position = {
                "quantity": order_item.count,
                "assortment": {
                    "meta": order_item.moysklad_product_meta
                }
            }
            positions.append(position)

        customer_order = {
            "organization": {
                "meta": organization.get("meta")
            },
            "agent": {
                "meta": user.moysklad_counterparty_meta
            },
            "positions": positions
        }
        return await self.__repo.create(**customer_order)

    async def create_order_by_request(self, order_items, user: User):
        positions = []
        for order_item in order_items:
            position = {
                "quantity": order_item["count"],
                "assortment": {
                    "meta": order_item["moysklad_product_meta"]
                }
            }
            positions.append(position)

        customer_order = {
            "organization": {
                "meta": organization.get("meta")
            },
            "agent": {
                "meta": user.moysklad_counterparty_meta
            },
            "positions": positions
        }
        return await self.__repo.create(**customer_order)

    async def get_order_by_id(self, id):
        return await self.__repo.read_one(id, link="expand=positions.assortment")

    async def get_orders_by_user(self, user: User):
        return await self.__repo.read_all(
            f"agent=https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{user.moysklad_counterparty_id}&expand=state&limit=100&order=created,desc"
        )

    async def delete_order_position_by_id(self, order_id, position_id):
        return await self.__repo.delete(order_id, link=f"/positions/{position_id}")


class InvoiceOutManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def get_user_invoices(self, user: User):
        return await self.__repo.read_all(f"agent=https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{user.moysklad_counterparty_id}")

    async def get_invoice_by_id(self, id):
        return await self.__repo.read_one(id)

    async def get_invoice_positions(self, id):
        return await self.__repo.read_one(str(id) + "/positions")


class PaymentInManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_payment_in(self, user: User, sum):
        payment_in_data = {
            "organization": organization,
            "agent": {"meta": user.moysklad_counterparty_meta},
            "sum": sum
        }
        return await self.__repo.create(**payment_in_data)
