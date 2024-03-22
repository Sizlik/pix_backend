from fastapi import APIRouter, Depends

from db.models.users import User
from db.schemas.notifications import NotificationCreate, NotificationTypes
from dependecies.chat import get_message_manager
from dependecies.moysklad import get_customer_order_manager
from dependecies.notifications import get_notification_manager
from manager.chat import MessageManager
from manager.moysklad import CustomerOrderManager
from manager.notifications import NotificationManager
from routes.users import current_user_dependency

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/")
async def create_notification(notification: NotificationCreate, notification_manager: NotificationManager = Depends(get_notification_manager)):
    return await notification_manager.create_notification(notification)


@router.get("/")
async def get_user_notifications(user: User = Depends(current_user_dependency), notification_manager: NotificationManager = Depends(get_notification_manager), order_manager: CustomerOrderManager = Depends(get_customer_order_manager), message_manager: MessageManager = Depends(get_message_manager)):
    notifications = await notification_manager.get_notifications_by_user(user)
    response = []
    for notification in notifications:
        match notification.type:
            case NotificationTypes.MESSAGE.value:
                message = await message_manager.get_message_by_id(notification.object_id)
                item = message.__dict__
                item.update(notification.__dict__)
                response.append(item)
            case NotificationTypes.ORDER_MESSAGE.value:
                message = await message_manager.get_message_by_id(notification.object_id)
                item = message.__dict__
                item.update(notification.__dict__)
                response.append(item)

            case NotificationTypes.ORDER_UPDATED.value:
                order = await order_manager.get_order_by_id(notification.object_id)
                order.update(notification.__dict__)
                response.append(order)

    return response


@router.post("/read/{id}")
async def read_one_notification(id: str, user: User = Depends(current_user_dependency), notification_manager: NotificationManager = Depends(get_notification_manager)):
    return await notification_manager.read_notification(id)


@router.post("/read")
async def read_all_notifications(user: User = Depends(current_user_dependency), notification_manager: NotificationManager = Depends(get_notification_manager)):
    notifications = await notification_manager.get_unreaded_notifications_by_user(user)

    for i in notifications:
        await notification_manager.read_notification(i.id)

    return
