import uuid
from typing import Optional

from fastapi_users import schemas
from pydantic import BaseModel, json


class BaseUser(BaseModel):
    first_name: str
    last_name: str
    phone_number: str
    is_organization_user: bool = False
    organization_id: Optional[uuid.UUID] = None


class UserRead(schemas.BaseUser[uuid.UUID], BaseUser):
    name_id: int


class UserCreate(schemas.BaseUserCreate, BaseUser):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    moysklad_counterparty_id: Optional[uuid.UUID] = None
    moysklad_counterparty_meta: Optional[dict] = None
    balance: Optional[int] = None
    telegram_id: Optional[int] = None
    organization_id: Optional[uuid.UUID] = None


