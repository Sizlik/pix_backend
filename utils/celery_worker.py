import asyncio

from bot.sender import telegram_sender
from manager.moysklad import CustomerOrderRepository, CustomerOrderManager
from manager.privoz_order import PrivozManager, PrivozRepository

privoz_manager = PrivozManager(PrivozRepository())
customer_order_manager = CustomerOrderManager(CustomerOrderRepository())


async def change_states_on_moysklad():
    print("here")
    try:
        states = await privoz_manager.parse_privoz()
    except Exception as e:
        print(e)

    orders = await customer_order_manager.get_orders()
    for order in orders.get("rows"):
        if order.get("shipmentAddressFull", {}).get("comment") and order.get("shipmentAddressFull", {}).get("comment").startswith("#"):
            print(order.get("shipmentAddressFull").get("comment"))
            privoz_order = await privoz_manager.get_order_by_id(order.get("shipmentAddressFull").get("comment"))
            if privoz_order.state != order.get("state").get("name"):
                await customer_order_manager.change_state(order.get("id"), privoz_order.state)
                telegram_sender.send_message(f"Заказ {order.get('meta').get('')} изменил статус на {privoz_order.state}")
    print("parsed")

