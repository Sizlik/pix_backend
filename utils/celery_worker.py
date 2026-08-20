import json

from db.models.users import User, UserDatabase
from db.postgres import async_session_maker
from db.schemas.notifications import NotificationCreate, NotificationTypes
from dependecies.notifications import build_notification_manager
from manager.moysklad import (
    CustomerOrderManager,
    CustomerOrderRepository,
    PurchaseOrderManager,
    PurchaseOrderRepository,
)
from manager.privoz_order import PrivozManager, PrivozRepository

privoz_manager = PrivozManager(PrivozRepository())
customer_order_manager = CustomerOrderManager(CustomerOrderRepository())
purchase_order_manager = PurchaseOrderManager(PurchaseOrderRepository())
notification_manager = build_notification_manager()


async def change_states_on_moysklad():
    try:
        await privoz_manager.parse_privoz()
    except Exception as e:
        print(e)

    orders = await customer_order_manager.get_orders()
    with open('test.json', 'w', encoding='utf-8') as f:
        f.write(json.dumps(orders))
    for order in orders.get("rows"):
        if order is None:
            continue
        if purchases := order.get("purchaseOrders"):
            purchaseId = purchases[0].get("meta", {}).get("href", "").split("/")[-1]
            purchase = await purchase_order_manager.get_by_id(purchaseId)
            privoz_number = f"#{purchase.get('name')}"
        # if order.get("shipmentAddressFull", {}).get("comment") and order.get("shipmentAddressFull", {}).get("comment").startswith("#"):
        #     print(order.get("shipmentAddressFull").get("comment"))
        #     privoz_order = await privoz_manager.get_order_by_id(order.get("shipmentAddressFull").get("comment"))
            privoz_order = await privoz_manager.get_order_by_id(privoz_number)
            if privoz_order is None:
                continue
            if privoz_order.state != order.get("state").get("name"):
                await customer_order_manager.change_state(order.get("id"), privoz_order.state)
                async with async_session_maker() as session:
                    try:
                        user = await UserDatabase(session, User).get_by_moysklad(
                            order.get("agent", {}).get("meta", {}).get("href", "").split("/")[-1])
                        if user is not None:
                            notification_data = NotificationCreate(
                                user_id=str(user.id),
                                type=NotificationTypes.ORDER_UPDATED,
                                object_id=str(order.get("id")),
                            )
                            await notification_manager.create_notification(
                                notification_data
                            )
                    except Exception as e:
                        print(e)

    print("parsed")


