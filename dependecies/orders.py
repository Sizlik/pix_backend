from bot.sender import telegram_sender
from manager.moysklad import (
    CustomerOrderManager,
    CustomerOrderRepository,
    ProductManager,
    ProductRepository,
)
from manager.order_changes import OrderChangesManager
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
