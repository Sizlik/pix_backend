from manager.orders import OrderManager, OrderRepository, OrderItemsManager, OrderItemsRepository


async def get_order_manager():
    yield OrderManager(OrderRepository())


async def get_order_items_manager():
    yield OrderItemsManager(OrderItemsRepository())
