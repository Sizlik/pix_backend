from enum import Enum

from pydantic import BaseModel


class NotificationTypes(str, Enum):
    MESSAGE = "MESSAGE"
    ORDER_MESSAGE = "ORDER_MESSAGE"
    ORDER_UPDATED = "ORDER_UPDATED"


class NotificationCreate(BaseModel):
    user_id: str
    type: NotificationTypes
    object_id: str

