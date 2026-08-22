from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class ConversationLastMessage(BaseModel):
    id: UUID
    sender_kind: SenderKind
    sender_label: str
    message: str
    created_at: datetime
    attachment_count: int = Field(ge=0)


class ConversationSummary(BaseModel):
    order_id: UUID
    order_name: str
    last_message: ConversationLastMessage
    unread_count: int = Field(ge=0)


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    next_before: UUID | None
    total_unread: int = Field(ge=0)


class OperatorReadResponse(BaseModel):
    order_id: UUID
    unread_count: Literal[0] = 0
    total_unread: int = Field(ge=0)


class ConversationUpdatedEvent(BaseModel):
    type: Literal["conversation_updated"] = "conversation_updated"
    item: ConversationSummary
    total_unread: int = Field(ge=0)
