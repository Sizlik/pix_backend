import uuid

from fastapi import APIRouter, Depends, Query

from bot.sender import telegram_sender
from db.models.users import UserDatabase, get_user_db
from db.schemas.notifications import NotificationCreate, NotificationTypes
from dependecies.notifications import get_notification_manager
from manager.moysklad import InvoiceOutManager, CustomerOrderManager
from dependecies import (orders as dependency_orders, bitrix as dependency_bitrix, moysklad as dependency_moysklad)
from manager.notifications import NotificationManager
from manager.orders import OrderManager, OrderItemsManager, OrderActionsManager

router = APIRouter(prefix="/webhooks", tags=["Integration Webhooks"])


@router.post("/invoice")
async def created_invoice_webhook(
        id=Query(uuid.UUID),
        moysklad_invoice_out_manager: InvoiceOutManager = Depends(dependency_moysklad.get_invoice_out_manager),
        order_manager: OrderManager = Depends(dependency_orders.get_order_manager),
        order_items_manager: OrderItemsManager = Depends(dependency_orders.get_order_items_manager),
):
    invoice = await moysklad_invoice_out_manager.get_invoice_by_id(id)
    if not invoice and not invoice.get("customerOrder"): return ;
    invoice_positions = await moysklad_invoice_out_manager.get_invoice_positions(id)
    order = await order_manager.get_order_by_moysklad_customer_order_id(invoice["customerOrder"]["meta"]["href"].split("/")[-1])

    order_update_data = {
        "payedSum": invoice["payedSum"],
        "shippedSum": invoice["shippedSum"],
        "sum": invoice["sum"],
        "moysklad_invoice_out_id": invoice["id"]
    }

    await order_manager.update_order(order.id, order_update_data)

    product_ids = [x["assortment"]["meta"]["href"].split("/")[-1] for x in invoice_positions["rows"]]

    order_items = await order_items_manager.get_order_items_by_moysklad_product_ids(product_ids)

    for i in invoice_positions["rows"]:
        for k in order_items:
            print(k.moysklad_product_id, i["assortment"]["meta"]["href"].split("/")[-1])
            if str(k.moysklad_product_id) == i["assortment"]["meta"]["href"].split("/")[-1]:
                order_item_update_data = {
                    "moysklad_invoice_item_id": i["id"],
                    "quantity": i["quantity"],
                    "price": i["price"],
                }
                await order_items_manager.update_order_item(k.id, order_item_update_data)
                break

    return invoice


@router.post("/accept_order")
async def accepted_status_order_webhook(
        id=Query(uuid.UUID),
        moysklad_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager),
        order_manager: OrderManager = Depends(dependency_orders.get_order_manager)
):
    moysklad_order = await moysklad_order_manager.get_order_by_id(id)

    order = await order_manager.get_order_by_moysklad_customer_order_id(moysklad_order.get(id))
    await order_manager.update_order(order.id, {"moysklad_customer_order_state": "Подтверждён"})


@router.post("/state_changed")
async def state_changed_webhook(
        id=Query(uuid.UUID),
        order_actions_manager: OrderActionsManager = Depends(dependency_orders.get_order_actions_manager),
        moysklad_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager)
):
    moysklad_order = await moysklad_order_manager.get_order_by_id(id)
    await order_actions_manager.create_action(id, moysklad_order.get("state").get("name"))


@router.post("/order_wait")
async def state_changed_webhook(
        id=Query(uuid.UUID),
        moysklad_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager),
        notification_manager: NotificationManager = Depends(get_notification_manager),
        user_db: UserDatabase = Depends(get_user_db),
):
    moysklad_order = await moysklad_order_manager.get_order_by_id(id)
    user = await user_db.get_by_moysklad(moysklad_order.get("agent", {}).get("meta", {}).get("href", "").split("/")[-1])
    if user and user.telegram_id:
        await telegram_sender.send_user_message(user.telegram_id, f"<a href='https://client.pixlogistic.com/dashboard/orders/{moysklad_order.get('id')}'>Заказ #{moysklad_order.get('name')}</a> изменил статус на <b>{moysklad_order.get('state', {}).get('name')}</b>")
    notification_data = NotificationCreate(user_id=str(user.id),
                                           type=NotificationTypes.ORDER_UPDATED.value,
                                           object_id=str(moysklad_order.get("id")))
    await notification_manager.create_notification(notification_data)
