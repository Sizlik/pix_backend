from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SenderKind(StrEnum):
    CLIENT = "client"
    MANAGER = "manager"


class MessageSource(StrEnum):
    SITE = "site"
    MOYSKLAD = "moysklad"
    LEGACY = "legacy"
    EXTENSION = "extension"


class AttachmentOrigin(StrEnum):
    SITE = "site"
    MOYSKLAD = "moysklad"
    EXTENSION = "extension"


class OrderChatAttachmentResponse(BaseModel):
    id: UUID
    filename: str
    mime_type: str
    size_bytes: int


class OrderChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    sender_kind: SenderKind
    sender_label: str
    message: str
    created_at: datetime
    attachments: list[OrderChatAttachmentResponse]


class OrderChatPageResponse(BaseModel):
    items: list[OrderChatMessageResponse]
    next_before: UUID | None
