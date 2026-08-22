from functools import lru_cache

from config import OrderChatSettings, get_settings
from db.moysklad_order_chat_repository import (
    MoySkladOrderChatRepository,
)
from db.order_chat_repository import OrderChatRepository
from dependecies.chat import get_chat_realtime
from dependecies.notifications import build_notification_manager
from dependecies.operator_inbox import get_operator_inbox_realtime
from manager.chat_storage import MinioObjectStorage
from manager.order_chat import (
    OperatorOrderChatAccessPolicy,
    OrderChatAccessPolicy,
    OrderChatService,
)
from manager.order_chat_auth import OperatorChatAuthenticator


@lru_cache
def get_order_chat_storage() -> MinioObjectStorage:
    return build_order_chat_storage(get_settings().require_order_chat())


def build_order_chat_storage(settings: OrderChatSettings) -> MinioObjectStorage:
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
    repository = OrderChatRepository()
    email_settings = (
        settings.require_order_chat_email()
        if settings.enable_order_chat_email_notifications
        else None
    )
    return OrderChatService(
        repository=repository,
        storage=get_order_chat_storage(),
        access_policy=OrderChatAccessPolicy(moysklad),
        operator_access_policy=OperatorOrderChatAccessPolicy(moysklad, repository),
        notification_manager=build_notification_manager(),
        attachment_max_count=chat_settings.attachment_max_count,
        attachment_max_bytes=chat_settings.attachment_max_bytes,
        realtime=get_chat_realtime(),
        inbox_realtime=get_operator_inbox_realtime(),
        manager_email=(
            email_settings.manager_email if email_settings is not None else None
        ),
    )


def get_order_chat_repository() -> OrderChatRepository:
    return OrderChatRepository()


def get_order_chat_access_policy() -> OrderChatAccessPolicy:
    settings = get_settings()
    return OrderChatAccessPolicy(MoySkladOrderChatRepository(settings))


def get_operator_chat_authenticator() -> OperatorChatAuthenticator:
    return OperatorChatAuthenticator(
        get_settings().require_chat_extension_secret()
    )
