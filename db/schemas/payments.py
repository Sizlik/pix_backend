import uuid

from pydantic import BaseModel


class CreatePayment(BaseModel):
    sum: float
    email: str
    order_id: uuid.UUID
