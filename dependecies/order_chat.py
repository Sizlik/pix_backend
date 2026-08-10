from functools import lru_cache

from config import get_settings
from db.moysklad_order_chat_repository import (
    MoySkladOrderChatRepository,
)
from db.order_chat_repository import OrderChatRepository
from manager.chat_storage import MinioObjectStorage
from manager.order_chat import OrderChatAccessPolicy, OrderChatService


@lru_cache
def get_order_chat_storage() -> MinioObjectStorage:
    settings = get_settings().require_order_chat()
    return MinioObjectStorage(
        endpoint=settings.endpoint,
        access_key=settings.access_key,
        secret_key=settings.secret_key,
        bucket=settings.bucket,
        secure=settings.secure,
    )


def get_order_chat_service() -> OrderChatService:
    settings = get_settings()
    chat_settings = settings.require_order_chat()
    moysklad = MoySkladOrderChatRepository(settings)
    return OrderChatService(
        repository=OrderChatRepository(),
        storage=get_order_chat_storage(),
        access_policy=OrderChatAccessPolicy(moysklad),
        attachment_max_count=chat_settings.attachment_max_count,
        attachment_max_bytes=chat_settings.attachment_max_bytes,
    )
