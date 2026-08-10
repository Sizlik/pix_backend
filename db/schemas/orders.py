from typing import List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class CheckoutOrderCreate(OrderBase):
    address_id: UUID


class OrderRead(OrderBase):
    id: int
    bitrix_deal_id: int


class MoySkladIntegrationOrder(BaseModel):
    moysklad_product_folder_id: UUID
    moysklad_product_folder_meta: dict


class MoySkladIntegrationCustomerOrder(BaseModel):
    moysklad_customer_order_id: UUID
    moysklad_customer_order_meta: dict


class ExistingOrderPositionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    count: int = Field(gt=0)


class NewOrderPositionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str = Field(min_length=1)
    count: int = Field(gt=0)
    comment: str = ""

    @field_validator("link")
    @classmethod
    def strip_and_require_link(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("link must not be blank")
        return value


OrderPositionChange = ExistingOrderPositionChange | NewOrderPositionChange


class OrderChangesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated: str = Field(min_length=1)
    positions: list[OrderPositionChange] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_existing_ids(self):
        ids = [
            str(item.id)
            for item in self.positions
            if isinstance(item, ExistingOrderPositionChange)
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("existing position ids must be unique")
        return self


class OrderChangesResponse(BaseModel):
    order: dict
    changed: bool
    notification_sent: bool | None
