import uuid
from typing import Optional

from fastapi_users import schemas
from pydantic import BaseModel, json


class BaseUser(BaseModel):
    first_name: str
    last_name: str
    phone_number: str


class UserRead(schemas.BaseUser[uuid.UUID], BaseUser):
    pass


class UserCreate(schemas.BaseUserCreate, BaseUser):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    moysklad_counterparty_id: Optional[uuid.UUID] = None
    moysklad_counterparty_meta: Optional[dict] = None
    balance: Optional[int] = None


