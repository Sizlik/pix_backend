from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class NotificationTypes(str, Enum):
    ORDER_MESSAGE = "ORDER_MESSAGE"
    ORDER_UPDATED = "ORDER_UPDATED"


class NotificationCreate(BaseModel):
    user_id: str
    type: NotificationTypes
    object_id: str


class NotificationCountResponse(BaseModel):
    unread_count: int = Field(ge=0)


class NotificationCountEvent(NotificationCountResponse):
    type: Literal["notification_count"] = "notification_count"
    version: int | None = Field(default=None, ge=1)

