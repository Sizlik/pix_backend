from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SenderKind(StrEnum):
    CLIENT = "client"
    MANAGER = "manager"


class MessageSource(StrEnum):
    SITE = "site"
    MOYSKLAD = "moysklad"
    LEGACY = "legacy"


class AttachmentOrigin(StrEnum):
    SITE = "site"
    MOYSKLAD = "moysklad"


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
    delivery_state: Literal["pending", "synced", "failed"]


class OrderChatPageResponse(BaseModel):
    items: list[OrderChatMessageResponse]
    next_before: UUID | None


class MoySkladWebhookMeta(BaseModel):
    type: str
    href: HttpUrl


class MoySkladWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    meta: MoySkladWebhookMeta
    action: str
    accountId: UUID
    updatedFields: list[str] = Field(default_factory=list)


class MoySkladAuditContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    meta: MoySkladWebhookMeta
    moment: str
    uid: str


class MoySkladWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    auditContext: MoySkladAuditContext | None = None
    events: list[MoySkladWebhookEvent]
