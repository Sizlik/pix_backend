from dataclasses import dataclass
from functools import lru_cache

from bot.sender import telegram_sender
from config import Settings, get_settings
from db.moysklad_order_chat_repository import (
    MoySkladOrderChatRepository,
)
from db.order_chat_repository import OrderChatRepository
from manager.chat_outbox import (
    OrderChatOutboxWorker,
    OrderChatTelegramHandlers,
)
from manager.chat_storage import MinioObjectStorage
from manager.moysklad_order_chat import MoySkladOrderChatSynchronizer
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


def get_order_chat_repository() -> OrderChatRepository:
    return OrderChatRepository()


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


def get_order_chat_runtime(settings: Settings) -> OrderChatRuntime:
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
    synchronizer = MoySkladOrderChatSynchronizer(
        repository=repository,
        moysklad=moysklad,
        storage=storage,
        attachment_max_count=chat_settings.attachment_max_count,
        attachment_max_bytes=chat_settings.attachment_max_bytes,
    )
    telegram_handlers = OrderChatTelegramHandlers(repository, telegram_sender)
    worker = OrderChatOutboxWorker(
        repository=repository,
        order_lock=repository.order_lock,
        handlers={
            "sync_order": lambda event: synchronizer.sync_order(event.order_id),
            "telegram_client_alert": telegram_handlers.client_alert,
            "process_moysklad_update": synchronizer.process_moysklad_update,
        },
        max_attempts=chat_settings.outbox_max_attempts,
        base_delay_seconds=chat_settings.outbox_base_delay_seconds,
    )
    return OrderChatRuntime(storage=storage, worker=worker)
