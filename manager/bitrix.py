import json
import os
from abc import ABC, abstractmethod
import smtplib
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from db.models.users import User
from db.schemas.bitrix_contact import AddContactFields, AddProductFields
from db.schemas.orders import OrderCreate


class BitrixABC(ABC):
    _link = os.getenv("BITRIX_LINK", "https://b24-678fl3.bitrix24.ru/rest/1/mojcqqoj4s90eyb0/")

    @abstractmethod
    def get(self, id_: str) -> dict:
        pass

    @abstractmethod
    def list(self, filter_: dict = None, order: dict = None, select: list = None) -> dict:
        pass

    @abstractmethod
    def add(self, fields: dict) -> dict:
        pass


class BitrixManager:

    def __init__(self, bitrix: BitrixABC):
        self.bitrix = bitrix

    def get(self, id_: str):
        return self.bitrix.get(id_)

    def list(self, filter_: dict = None, order: dict = None, select: list = None):
        select = select if select else ["*"]
        return self.bitrix.list(filter_, order, select)

    def add(self, fields):
        return self.bitrix.add(fields)


class BitrixManagerFull:
    _link = os.getenv("BITRIX_LINK", "https://b24-678fl3.bitrix24.ru/rest/1/mojcqqoj4s90eyb0/")

    def __init__(self):
        self.deal_manager = BitrixManager(BitrixCrmDeal())
        self.product_manager = BitrixManager(BitrixCrmProduct())
        self.contact_manager = BitrixManager(BitrixCrmContact())

    def get_or_create_contact_by_user(self, user: User):
        result = self.contact_manager.list(filter_={"EMAIL": user.email}).get("result")
        if result:
            return result[0]["ID"]
        else:
            contact_data = AddContactFields(
                EMAIL=[{"VALUE": user.email}],
                LAST_NAME=user.last_name,
                NAME=user.first_name,
                PHONE=[{"VALUE": user.phone_number}]
            )
            return self.contact_manager.add(contact_data.model_dump()).get("result")

    def insert_products(self, orders: OrderCreate, bitrix_deal_id):
        products = []
        for i in orders.model_dump().get("order_items"):
            product = AddProductFields(
                NAME=f"{i['link']}",
                DESCRIPTION=f"{i['link']}\n{i['comment']}"
            ).model_dump()
            product_response = self.product_manager.add(product)
            product_id = product_response.get("result")
            row_product = {"PRODUCT_ID": product_id, "QUANTITY": i['count']}
            print("1", row_product)
            products.append(row_product)

        fields = {"id": bitrix_deal_id, "rows": products}
        response = requests.post(self._link + "crm.deal.productrows.set.json", json=fields).json()
        return response


class BitrixCrmContact(BitrixABC):
    def get(self, id_: str) -> dict:
        return requests.post(self._link + "crm.contact.get.json", json={"id": id_}).json()

    def list(self, filter_: dict = None, order: dict = None, select: list = None) -> dict:
        return requests.post(self._link + "crm.contact.list.json", json={"filter": filter_, "order": order, "select": select}).json()

    def add(self, fields: dict) -> dict:
        return requests.post(self._link + "crm.contact.add.json", json={"fields": fields}).json()


class BitrixCrmDeal(BitrixABC):
    def get(self, id_: str) -> dict:
        return requests.post(self._link + "crm.deal.get.json", json={"id": id_}).json()

    def list(self, filter_: dict = None, order: dict = None, select: list = None) -> dict:
        return requests.post(self._link + "crm.deal.list.json", json={"filter": filter_, "order": order, "select": select}).json()

    def add(self, fields: dict) -> dict:
        return requests.post(self._link + "crm.deal.add.json", json={"fields": fields}).json()


class BitrixCrmProduct(BitrixABC):
    def get(self, id_: str) -> dict:
        return requests.post(self._link + "crm.product.get.json", json={"id": id_}).json()

    def list(self, filter_: dict = None, order: dict = None, select: list = None) -> dict:
        return requests.post(self._link + "crm.product.list.json", json={"filter": filter_, "order": order, "select": select}).json()

    def add(self, fields: dict) -> dict:
        return requests.post(self._link + "crm.product.add.json", json={"fields": fields}).json()


# if __name__ == '__main__':
    # smtp = smtplib.SMTP_SSL("mail.pixlogistic.com", 465)
    # smtp.login("info@pixlogistic.com", "qwerty")
    #
    # msg = MIMEMultipart()
    # msg.attach(MIMEText("Test SMTP message"))
    #
    # msg['Subject'] = f'The Test SMTP server'
    # msg['From'] = "info@pixlogistic.com"
    # msg['To'] = "eugene.stlab@gmail.com"
    #
    # smtp.sendmail("info@pixlogistic.com", ["eugene.stlab@gmail.com"], msg.as_string())
