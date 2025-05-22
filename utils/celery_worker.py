import asyncio
import json

from bot.sender import telegram_sender
from db.models.users import UserDatabase, User
from db.postgres import async_session_maker
from db.schemas.notifications import NotificationCreate, NotificationTypes
from manager.moysklad import CustomerOrderRepository, CustomerOrderManager, PurchaseOrderManager, \
    PurchaseOrderRepository
from manager.notifications import NotificationManager, NotificationRepository
from manager.privoz_order import PrivozManager, PrivozRepository
from manager.users import get_user_manager

privoz_manager = PrivozManager(PrivozRepository())
customer_order_manager = CustomerOrderManager(CustomerOrderRepository())
purchase_order_manager = PurchaseOrderManager(PurchaseOrderRepository())
notification_manager = NotificationManager(NotificationRepository())


async def change_states_on_moysklad():
    try:
        states = await privoz_manager.parse_privoz()
    except Exception as e:
        print(e)

    orders = await customer_order_manager.get_orders()
    with open('test.json', 'w', encoding='utf-8') as f:
        f.write(json.dumps(orders))
    for order in orders.get("rows"):
        if purchases := order.get("purchaseOrders"):
            purchaseId = purchases[0].get("meta", {}).get("href", "").split("/")[-1]
            purchase = await purchase_order_manager.get_by_id(purchaseId)
            privoz_number = f"#{purchase.get('name')}"
        # if order.get("shipmentAddressFull", {}).get("comment") and order.get("shipmentAddressFull", {}).get("comment").startswith("#"):
        #     print(order.get("shipmentAddressFull").get("comment"))
        #     privoz_order = await privoz_manager.get_order_by_id(order.get("shipmentAddressFull").get("comment"))
            privoz_order = await privoz_manager.get_order_by_id(privoz_number)
            if privoz_order.state != order.get("state").get("name"):
                await customer_order_manager.change_state(order.get("id"), privoz_order.state)
                async with async_session_maker() as session:
                    try:
                        user = await UserDatabase(session, User).get_by_moysklad(
                            order.get("agent", {}).get("meta", {}).get("href", "").split("/")[-1])
                        if user and user.telegram_id:
                            await telegram_sender.send_user_message(user.telegram_id, f"<a href='https://client.pixlogistic.com/dashboard/orders/{order.get('id')}'>Заказ #{order.get('name')}</a> изменил статус на <b>{privoz_order.state}</b>")
                        notification_data = NotificationCreate(user_id=str(user.id),
                                                               type=NotificationTypes.ORDER_UPDATED.value,
                                                               object_id=str(order.get("id")))
                        await notification_manager.create_notification(notification_data)
                    except Exception as e:
                        print(e)

    print("parsed")


