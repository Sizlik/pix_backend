from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import requests

from db.models.orders import OrderItems
from db.models.users import User
from db.repository import AbstractRepository, MoySkladRepository
from db.schemas import moysklad
from db.schemas.orders import CheckoutOrderCreate, OrderCreate
from errors import (
    MoySkladDocumentExportError,
    MoySkladOrderStateMissing,
    OrderNotAccessible,
)
from manager.addresses import DeliveryAddressSnapshot
from manager.phone_numbers import normalize_phone, phone_search_variants


def moysklad_delivery_payload(address: DeliveryAddressSnapshot) -> dict:
    parts = []
    if address.postal_code:
        parts.append(address.postal_code)
    parts.extend(["Россия", address.city, address.street, f"дом {address.house}"])
    if address.building:
        parts.append(address.building)
    if address.apartment:
        parts.append(f"кв./офис {address.apartment}")

    full = {
        "city": address.city,
        "street": address.street,
        "house": ", ".join(
            value for value in (address.house, address.building) if value
        ),
    }
    if address.postal_code:
        full["postalCode"] = address.postal_code
    if address.apartment:
        full["apartment"] = address.apartment
    if address.delivery_comment:
        full["addInfo"] = address.delivery_comment
    return {"shipmentAddress": ", ".join(parts), "shipmentAddressFull": full}


class CounterpartyRepository(MoySkladRepository):
    model = "entity/counterparty"

    async def find_by_phone_candidates(
        self,
        phones: tuple[str, ...],
    ) -> list[dict]:
        if not phones:
            return []
        response = requests.get(
            f"{self.base_url}{self.model}",
            headers=self._headers(),
            params={
                "filter": ";".join(f"phone={phone}" for phone in phones),
                "limit": 1000,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("invalid MoySklad counterparty collection")
        rows = payload.get("rows")
        if not isinstance(rows, list) or not all(
            isinstance(row, dict) for row in rows
        ):
            raise ValueError("invalid MoySklad counterparty collection")
        return rows


class CounterpartyReportRepository(MoySkladRepository):
    model = "report/counterparty"


class OperationRepository(MoySkladRepository):
    model = "entity/operation"


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


class PurchaseOrderRepository(MoySkladRepository):
    model = "entity/purchaseorder"


@dataclass(frozen=True)
class CounterpartyResolution:
    counterparty: dict
    created: bool


class CounterpartyManager:
    def __init__(self, repo: CounterpartyRepository):
        self.__repo = repo

    async def create_user_counterparty(
        self,
        counterparty_data: moysklad.CounterpartyCreate,
    ):
        counterparty_dict = counterparty_data.model_dump()
        return await self.__repo.create(**counterparty_dict)

    async def resolve_user_counterparty(
        self,
        counterparty_data: moysklad.CounterpartyCreate,
    ) -> CounterpartyResolution:
        normalized_phone = normalize_phone(counterparty_data.phone)
        candidates = await self.__repo.find_by_phone_candidates(
            phone_search_variants(counterparty_data.phone)
        )

        matches = []
        for candidate in candidates:
            phone = candidate.get("phone")
            if not isinstance(phone, str):
                raise ValueError("invalid MoySklad counterparty candidate")
            if normalize_phone(phone) == normalized_phone:
                matches.append(candidate)

        if len(matches) == 1:
            match = matches[0]
            meta = match.get("meta")
            if (
                not isinstance(match.get("id"), str)
                or not match["id"]
                or not isinstance(meta, dict)
                or not isinstance(meta.get("uuidHref"), str)
                or not meta["uuidHref"]
            ):
                raise ValueError("invalid MoySklad counterparty match")
            return CounterpartyResolution(match, created=False)

        created = await self.create_user_counterparty(counterparty_data)
        return CounterpartyResolution(created, created=True)


class CounterpartyReportManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def get_user_counterparty_report(self, user):
        return await self.__repo.read_one(user.moysklad_counterparty_id)


class OperationManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def get_operations(self, user):
        data = await self.__repo.read_all(
            filter=f"agent=https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{user.moysklad_counterparty_id};type=paymentin;type=demand;type=customerorder"
        )
        result = {"rows": []}
        for i in data.get("rows") or []:
            try:
                if i.get("meta", {}).get("type") == "customerorder":
                    if i.get("state", {}).get("name").lower() not in [
                        "заказ доставляется",
                        "выдан частично",
                        "склад польша",
                        "склад беларусь",
                        "отгружен",
                        "отгружен частично",
                    ]:
                        continue
                result["rows"].append(i)
            except Exception as e:
                print(e)
        return result


class ProductFolderManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_product_folder(self, product_folder_data: moysklad.ProductFolderCreate):
        product_folder_dict = product_folder_data.model_dump()
        return await self.__repo.create(**product_folder_dict)


class ProductManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_products_from_orders(
        self, order_items: list[OrderItems], product_folder_meta: dict, order_id: int, user: User
    ):
        products = []
        for order_item in order_items:
            product = moysklad.ProductCreate(
                name=f"{order_item.link} - Заказ: #{order_id}",
                description=f"""id на pixlogistic: {order_item.id}
Комментарий: {order_item.comment}
Телефон: {user.phone_number}
""",
                productFolder={"meta": product_folder_meta},
            ).model_dump()
            products.append(product)

        return await self.__repo.create_multiply(products)

    async def create_products(
        self,
        order: OrderCreate | CheckoutOrderCreate,
        user: User,
        sync_ids: Sequence[UUID] | None = None,
    ):
        if sync_ids is not None and len(sync_ids) != len(order.order_items):
            raise ValueError("one sync id is required per product")
        products = []
        for index, item in enumerate(order.order_items):
            product = moysklad.ProductCreate(
                name=f"{item.link}",
                description=f"{item.comment}",
                syncId=str(sync_ids[index]) if sync_ids is not None else None,
            ).model_dump(exclude_none=True)

            products.append(product)

        return await self.__repo.create_multiply(products)


def enrich_order_currency(order: dict) -> dict:
    rate = order.get("rate")
    currency = rate.get("currency") if isinstance(rate, dict) else None
    iso_code = currency.get("isoCode") if isinstance(currency, dict) else None
    if isinstance(iso_code, str) and iso_code.strip():
        order["currency_code"] = iso_code.strip().upper()
    else:
        order.pop("currency_code", None)
    return order


def first_embedded_template(payload: object) -> dict:
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise MoySkladDocumentExportError("template_missing")
    return rows[0]


def ensure_document_owner(payload: object, user: User) -> None:
    if not isinstance(payload, dict) or not payload.get("id"):
        raise OrderNotAccessible()
    agent = payload.get("agent")
    meta = agent.get("meta") if isinstance(agent, dict) else None
    href = meta.get("href") if isinstance(meta, dict) else None
    owner_id = href.rsplit("/", 1)[-1] if isinstance(href, str) else None
    if owner_id != str(user.moysklad_counterparty_id):
        raise OrderNotAccessible()


class CustomerOrderManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def get_metadata(self):
        return await self.__repo.read_all(metadata="/metadata")

    async def export_template(self, id, user: User):
        context = await self.__repo.read_export_context(str(id))
        ensure_document_owner(context, user)
        payload = await self.__repo.read_embedded_templates()
        return await self.__repo.export_document(
            str(id),
            template=first_embedded_template(payload),
            extension="pdf",
        )

    async def change_state(self, id, state_name):
        state_meta = await self.get_state_meta(state_name)
        return await self.__repo.update(id, state={"meta": state_meta})

    async def get_state_meta(self, state_name: str) -> dict:
        metadata = await self.get_metadata()
        for state in metadata.get("states", []):
            if state.get("name") == state_name:
                return state["meta"]
        raise MoySkladOrderStateMissing(state_name)

    async def replace_positions_and_state(
        self,
        order_id,
        positions: list[dict],
        state_meta: dict,
    ):
        await self.__repo.update(
            order_id,
            positions=positions,
            state={"meta": state_meta},
        )
        return await self.get_order_by_id(order_id)

    async def update_order_position(self, order_id, position_id, count):
        return await self.__repo.update(order_id, link=f"/positions/{position_id}", quantity=count)

    async def add_order_position(self, order_id, order_items):
        return await self.__repo.create(
            link=f"{order_id}/positions",
            quantity=order_items[0]["count"],
            assortment={"meta": order_items[0]["moysklad_product_meta"]},
        )

    async def create_order(self, order_items: list[OrderItems], user: User):
        organization = await self.__repo.get_default_company()
        positions = []
        for order_item in order_items:
            position = {"quantity": order_item.count, "assortment": {"meta": order_item.moysklad_product_meta}}
            positions.append(position)

        customer_order = {
            "organization": {"meta": organization.get("meta")},
            "agent": {"meta": user.moysklad_counterparty_meta},
            "positions": positions,
        }
        return await self.__repo.create(**customer_order)

    async def create_order_by_request(
        self,
        order_items,
        user: User,
        delivery_address: DeliveryAddressSnapshot,
        *,
        sync_id: UUID,
    ):
        organization = await self.__repo.get_default_company()
        positions = []
        for order_item in order_items:
            position = {"quantity": order_item["count"], "assortment": {"meta": order_item["moysklad_product_meta"]}}
            positions.append(position)

        customer_order = {
            "syncId": str(sync_id),
            "organization": {"meta": organization.get("meta")},
            "agent": {"meta": user.moysklad_counterparty_meta},
            "positions": positions,
            **moysklad_delivery_payload(delivery_address),
        }
        return await self.__repo.create(**customer_order)

    async def get_order_by_id(self, id):
        order = await self.__repo.read_one(
            id,
            link="expand=positions.assortment,state,rate.currency",
        )
        return enrich_order_currency(order)

    async def get_orders_by_user(self, user: User):
        result = await self.__repo.read_all(
            f"agent=https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{user.moysklad_counterparty_id}&expand=state,rate.currency&limit=100&order=created,desc"
        )
        rows = result.get("rows")
        if isinstance(rows, list):
            for order in rows:
                if isinstance(order, dict):
                    enrich_order_currency(order)
        return result

    async def delete_order_position_by_id(self, order_id, position_id):
        return await self.__repo.delete(order_id, link=f"/positions/{position_id}")

    async def get_orders(self):
        return await self.__repo.read_all(filter="&limit=100&expand=state&order=created,desc")


class InvoiceOutManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def export_template(self, id, user: User):
        context = await self.__repo.read_export_context(str(id))
        ensure_document_owner(context, user)
        payload = await self.__repo.read_embedded_templates()
        return await self.__repo.export_document(
            str(id),
            template=first_embedded_template(payload),
            extension="pdf",
        )

    async def get_user_invoices(self, user: User):
        return await self.__repo.read_all(
            f"agent=https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{user.moysklad_counterparty_id}"
        )

    async def get_invoice_by_id(self, id):
        return await self.__repo.read_one(id)

    async def get_invoice_positions(self, id):
        return await self.__repo.read_one(str(id) + "/positions")


class PaymentInManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def create_payment_in(self, user: User, sum):
        organization = await self.__repo.get_default_company()
        payment_in_data = {"organization": organization, "agent": {"meta": user.moysklad_counterparty_meta}, "sum": sum}
        return await self.__repo.create(**payment_in_data)

    async def link_payment_in(self, id, order_meta):
        return await self.__repo.update(id, operations=[{"meta": order_meta}])

    async def get_all_user_payment_ins(self, user: User):
        return await self.__repo.read_all(
            filter=f"agent=https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{user.moysklad_counterparty_id}&order=created,desc&expand=operations&limit=100"
        )


# class StateManager:
#     def __init__(self, repo: AbstractRepository):
#         self.__repo = repo


class PurchaseOrderManager:
    def __init__(self, repo: AbstractRepository):
        self.__repo = repo

    async def export_template(self, id, user: User):
        if not user.is_superuser:
            raise OrderNotAccessible()
        payload = await self.__repo.read_embedded_templates()
        return await self.__repo.export_document(
            str(id),
            template=first_embedded_template(payload),
            extension="pdf",
        )

    async def get_by_id(self, id):
        return await self.__repo.read_one(id)
