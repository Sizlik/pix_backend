from bot.sender import telegram_sender
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


async def get_order_manager():
    yield OrderManager(OrderRepository())


async def get_order_items_manager():
    yield OrderItemsManager(OrderItemsRepository())


async def get_order_actions_manager():
    yield OrderActionsManager(OrderActionsRepository())


async def get_order_changes_manager():
    yield OrderChangesManager(
        CustomerOrderManager(CustomerOrderRepository()),
        ProductManager(ProductRepository()),
        telegram_sender,
    )


async def get_order_creation_manager():
    yield OrderCreationManager(
        AddressManager(AddressRepository()),
        ProductManager(ProductRepository()),
        CustomerOrderManager(CustomerOrderRepository()),
        RedisOrderCreationIdempotency(redis),
        telegram_sender,
    )
