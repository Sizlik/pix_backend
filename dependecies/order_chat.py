from dataclasses import dataclass
from functools import lru_cache

from config import Settings, get_settings
from db.moysklad_order_chat_repository import (
    MoySkladOrderChatRepository,
)
from db.order_chat_repository import OrderChatRepository
from dependecies.chat import get_chat_realtime
from dependecies.notifications import build_notification_manager
from manager.chat_outbox import OrderChatOutboxWorker
from manager.chat_storage import MinioObjectStorage
from manager.moysklad_order_chat import MoySkladOrderChatSynchronizer
from manager.order_chat import (
    OperatorOrderChatAccessPolicy,
    OrderChatAccessPolicy,
    OrderChatService,
)
from manager.order_chat_auth import OperatorChatAuthenticator


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
    repository = OrderChatRepository()
    return OrderChatService(
        repository=repository,
        storage=get_order_chat_storage(),
        access_policy=OrderChatAccessPolicy(moysklad),
        operator_access_policy=OperatorOrderChatAccessPolicy(moysklad, repository),
        notification_manager=build_notification_manager(),
        attachment_max_count=chat_settings.attachment_max_count,
        attachment_max_bytes=chat_settings.attachment_max_bytes,
        realtime=get_chat_realtime(),
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


def get_order_chat_webhook_receiver():
    from routes.integration.order_chat_webhook import OrderChatWebhookReceiver

    chat_settings = get_settings().require_order_chat()
    return OrderChatWebhookReceiver(
        repository=OrderChatRepository(),
        secret=chat_settings.webhook_secret,
    )


@dataclass(frozen=True, slots=True)
class OrderChatRuntime:
    storage: MinioObjectStorage
    worker: OrderChatOutboxWorker


def get_order_chat_runtime(settings: Settings, realtime=None) -> OrderChatRuntime:
    chat_settings = settings.require_order_chat()
    storage = MinioObjectStorage(
        endpoint=chat_settings.endpoint,
        access_key=chat_settings.access_key,
        secret_key=chat_settings.secret_key,
        bucket=chat_settings.bucket,
        secure=chat_settings.secure,
    )
    repository = OrderChatRepository()
    moysklad = MoySkladOrderChatRepository(settings)
    realtime = realtime or get_chat_realtime()
    synchronizer = MoySkladOrderChatSynchronizer(
        repository=repository,
        moysklad=moysklad,
        storage=storage,
        attachment_max_count=chat_settings.attachment_max_count,
        attachment_max_bytes=chat_settings.attachment_max_bytes,
        realtime=realtime,
        notification_manager=build_notification_manager(),
    )
    worker = OrderChatOutboxWorker(
        repository=repository,
        order_lock=repository.order_lock,
        handlers={
            "sync_order": lambda event: synchronizer.sync_order(event.order_id),
            "process_moysklad_update": synchronizer.process_moysklad_update,
        },
        max_attempts=chat_settings.outbox_max_attempts,
        base_delay_seconds=chat_settings.outbox_base_delay_seconds,
        realtime=realtime,
    )
    return OrderChatRuntime(storage=storage, worker=worker)
