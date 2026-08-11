from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi_users.authentication import RedisStrategy

from db.models.users import User
from db.order_chat_repository import OrderChatRepository
from db.redis import get_redis_strategy
from db.schemas.notifications import (
    NotificationCountResponse,
    NotificationCreate,
    NotificationTypes,
)
from dependecies.chat import get_message_manager
from dependecies.moysklad import get_customer_order_manager
from dependecies.notifications import (
    get_notification_manager,
    get_notification_realtime,
)
from dependecies.order_chat import get_order_chat_repository
from manager.chat import MessageManager
from manager.moysklad import CustomerOrderManager
from manager.notification_realtime import NotificationRealtime
from manager.notifications import NotificationManager
from manager.users import get_user_manager
from routes.users import current_user_dependency

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/")
async def create_notification(
    notification: NotificationCreate,
    user: User = Depends(current_user_dependency),
    notification_manager: NotificationManager = Depends(get_notification_manager),
):
    user_notification = notification.model_copy(update={"user_id": str(user.id)})
    return await notification_manager.create_notification(user_notification)


@router.get("/")
async def get_user_notifications(
    user: User = Depends(current_user_dependency),
    notification_manager: NotificationManager = Depends(get_notification_manager),
    order_manager: CustomerOrderManager = Depends(get_customer_order_manager),
    message_manager: MessageManager = Depends(get_message_manager),
    order_chat_repository: OrderChatRepository = Depends(get_order_chat_repository),
):
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
                order_message = await order_chat_repository.get_message(notification.object_id)
                if order_message is not None:
                    response.append(
                        {
                            **notification.__dict__,
                            "id": notification.id,
                            "object_id": str(order_message.id),
                            "message": order_message.body,
                            "first_name": "bot",
                            "from_user_id": None,
                            "to_chat_room_id": str(order_message.order_id),
                            "time_created": order_message.created_at,
                        }
                    )
                else:
                    message = await message_manager.get_message_by_id(notification.object_id)
                    item = message.__dict__
                    item.update(notification.__dict__)
                    response.append(item)

            case NotificationTypes.ORDER_UPDATED.value:
                order = await order_manager.get_order_by_id(notification.object_id)
                order.update(notification.__dict__)
                response.append(order)

    return response


@router.get("/unread-count", response_model=NotificationCountResponse)
async def unread_count(
    user: User = Depends(current_user_dependency),
    notification_manager: NotificationManager = Depends(get_notification_manager),
):
    count = await notification_manager.unread_count(user.id)
    return NotificationCountResponse(unread_count=count)


@router.post("/read/{id}")
async def read_one_notification(
    id: UUID,
    user: User = Depends(current_user_dependency),
    notification_manager: NotificationManager = Depends(get_notification_manager),
):
    count = await notification_manager.read_notification(user.id, id)
    return NotificationCountResponse(unread_count=count)


@router.post("/read")
async def read_all_notifications(
    user: User = Depends(current_user_dependency),
    notification_manager: NotificationManager = Depends(get_notification_manager),
):
    count = await notification_manager.read_all_notifications(user.id)
    return NotificationCountResponse(unread_count=count)


@router.websocket("/ws")
async def notification_websocket(
    websocket: WebSocket,
    redis_strategy: RedisStrategy = Depends(get_redis_strategy),
    user_manager=Depends(get_user_manager),
    notification_manager: NotificationManager = Depends(get_notification_manager),
    realtime: NotificationRealtime = Depends(get_notification_realtime),
):
    token = websocket.query_params.get("auth")
    if not token:
        await websocket.close(code=4401)
        return
    user = await redis_strategy.read_token(token, user_manager)
    if not user:
        await websocket.close(code=4401)
        return

    user_id = str(user.id)
    await realtime.connect(user_id, websocket)
    try:
        await notification_manager.send_current_count(user.id, websocket.send_json)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await realtime.disconnect(user_id, websocket)
