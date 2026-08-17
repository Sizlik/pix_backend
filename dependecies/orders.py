from bot.sender import telegram_sender
from config import get_settings
from db.address_repository import AddressRepository
from db.redis import redis
from manager.addresses import AddressManager
from manager.moysklad import (
    CustomerOrderManager,
    CustomerOrderRepository,
    ProductManager,
    ProductRepository,
)
from manager.order_changes import OrderChangesManager
from manager.order_creation import OrderCreationManager
from manager.order_idempotency import RedisOrderCreationIdempotency
from manager.orders import (
    OrderActionsManager,
    OrderActionsRepository,
    OrderItemsManager,
    OrderItemsRepository,
    OrderManager,
    OrderRepository,
)
from manager.telegram_notifications import BestEffortGroupNotifier


async def get_order_manager():
    yield OrderManager(OrderRepository())


async def get_order_items_manager():
    yield OrderItemsManager(OrderItemsRepository())


async def get_order_actions_manager():
    yield OrderActionsManager(OrderActionsRepository())


def get_order_notifier() -> BestEffortGroupNotifier:
    settings = get_settings()
    return BestEffortGroupNotifier(
        telegram_sender,
        timeout_seconds=settings.telegram_notification_timeout_seconds,
    )


async def get_order_changes_manager():
    yield OrderChangesManager(
        CustomerOrderManager(CustomerOrderRepository()),
        ProductManager(ProductRepository()),
        get_order_notifier(),
    )


async def get_order_creation_manager():
    yield OrderCreationManager(
        AddressManager(AddressRepository()),
        ProductManager(ProductRepository()),
        CustomerOrderManager(CustomerOrderRepository()),
        RedisOrderCreationIdempotency(redis),
        get_order_notifier(),
    )
