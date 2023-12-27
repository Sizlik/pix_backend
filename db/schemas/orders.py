from typing import List
from uuid import UUID

from pydantic import BaseModel


class OrderItemBase(BaseModel):
    comment: str
    count: int
    link: str


class OrderItemCreate(OrderItemBase):
    pass


class OrderItemRead(OrderItemBase):
    order_id: int


class OrderBase(BaseModel):
    order_items: List[OrderItemCreate]


class OrderCreate(OrderBase):
    pass


class OrderRead(OrderBase):
    id: int
    bitrix_deal_id: int


class MoySkladIntegrationOrder(BaseModel):
    moysklad_product_folder_id: UUID
    moysklad_product_folder_meta: dict


class MoySkladIntegrationCustomerOrder(BaseModel):
    moysklad_customer_order_id: UUID
    moysklad_customer_order_meta: dict
