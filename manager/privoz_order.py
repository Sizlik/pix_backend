import requests
from bs4 import BeautifulSoup
from fastapi_utils.tasks import repeat_every

from db.models.privoz_order import PrivozOrder
from db.repository import SQLAlchemyRepository, AbstractRepository


class PrivozRepository(SQLAlchemyRepository):
    model = PrivozOrder


class PrivozManager:
    def __init__(self, order_repo: AbstractRepository):
        self.order_repo = order_repo

    async def create_order(self, fields):
        order_dict = fields.model_dump()
        order_id = await self.order_repo.create(**order_dict)
        return order_id

    async def get_order_by_id(self, id):
        return await self.order_repo.read_one(id)

    async def get_all_orders(self):
        return await self.order_repo.read_all()

    async def update_order(self, id, update_dict):
        return await self.order_repo.update(id, **update_dict)

    async def delete_order(self, id):
        return await self.order_repo.delete(id)

    async def get_by_privoz_order_id(self, id):
        return await self.order_repo.search_one(PrivozOrder.privoz_order == id)

    async def parse_privoz(self):
        session = requests.Session()
        session.post("https://client.privoz.pl/users/login/", data={"username": "bugaidaniil@mail.ru", "password": "pix475"})
        response = session.get("https://client.privoz.pl/orders")
        soup = BeautifulSoup(response.text, 'html.parser')
        page_max = int(soup.find("div", {"class": "paginator"}).find_next("p").text.split(" ")[-1])

        orders = []
        for tr in soup.find_all("tr")[1:-1]:
            orders.append({"privoz_order": tr.find_next("a").text, "state": tr.find_all("td")[2].text})

        for page in range(2, page_max + 1):
            html = session.get(f"https://client.privoz.pl/orders?page={page}").text
            soup = BeautifulSoup(html, 'html.parser')
            for tr in soup.find_all("tr")[1:-1]:
                orders.append({"privoz_order": tr.find_next("a").text, "state": tr.find_all("td")[2].text})

        await self.order_repo.upsert(orders)

        return orders



