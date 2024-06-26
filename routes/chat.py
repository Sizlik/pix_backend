# import requests
import uuid
from uuid import UUID

import jwt
import requests
from fastapi import APIRouter, WebSocket, Depends, WebSocketDisconnect, Body
from fastapi_users.authentication import RedisStrategy

from bot.sender import telegram_sender
from db.models.users import User, UserDatabase, get_user_db
from db.redis import get_redis_strategy
from db.schemas.notifications import NotificationCreate, NotificationTypes
from dependecies.chat import get_chat_manager, get_chat_room_manager, get_message_manager
from dependecies.notifications import get_notification_manager
from manager.chat import ChatManager, ChatRoomManager, MessageManager
from manager.notifications import NotificationManager
from manager.users import get_user_manager
from routes.users import current_user_dependency

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.websocket("/ws")
async def websocket_connection(websocket: WebSocket, redis_strategy: RedisStrategy = Depends(get_redis_strategy),
                               user_manager=Depends(get_user_manager),
                               chat_manager: ChatManager = Depends(get_chat_manager)):
    token = websocket.query_params["auth"]
    user = await redis_strategy.read_token(token, user_manager)

    if not user:
        await websocket.close()
        return

    room_id = websocket.query_params.get("room", str(user.id))
    print(room_id)
    await chat_manager.connect(room_id, websocket)

    try:
        while True:
            ws_data = await websocket.receive_json()
            if not ws_data.get("to_chat_room_id"):
                ws_data["to_chat_room_id"] = user.id

            data = {
                "message": ws_data["message"],
                "from_user_id": str(user.id),
                "to_chat_room_id": str(ws_data["to_chat_room_id"]),
            }
            await chat_manager.send_message_from_client(data, room_id, user)

    except WebSocketDisconnect:
        chat_manager.disconnect(room_id, websocket)


@router.post("/send_message")
async def send_message_by_endpoint(message: str = Body(),
                                   to_chat_room: str = Body(),
                                   client_id: str = Body(),
                                   user=Depends(current_user_dependency),
                                   chat_manager: ChatManager = Depends(get_chat_manager),
                                   notification_manager: NotificationManager = Depends(get_notification_manager),
                                   user_db: UserDatabase = Depends(get_user_db)):
    if user.email == "bot@pixlogistic.com":
        data = {"message": message, "from_user_id": str(user.id), "to_chat_room_id": to_chat_room}
        message_id = await chat_manager.send_message_from_client(data, to_chat_room, user)
        notification_data = NotificationCreate(user_id=client_id, type=NotificationTypes.MESSAGE.value if client_id == to_chat_room else NotificationTypes.ORDER_MESSAGE.value, object_id=str(message_id))
        await notification_manager.create_notification(notification_data)
        client = await user_db.get(client_id)
        if client.telegram_id:
            await telegram_sender.send_user_message(client.telegram_id, f'У вас новое сообщение от менеджера на <a href="https://client.pixlogistic.com/dashboard/notifications">сайте</a>\n\n{message}', disable_web_page_preview=True)


@router.post("/{order_id}")
async def create_order_chat_room(order_id: uuid.UUID, user: User = Depends(current_user_dependency), chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager)):
    return await chat_room_manager.create_order_chat(user, order_id)


# @router.post("/messages")
# async def create_message(user: User = Depends(current_user_dependency), message: str = Body(...), message_manager: MessageManager = Depends(get_message_manager), chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager)):
#     chat_room = await chat_room_manager.get_my_chat(user)
#     data = {
#         "message": message,
#         "from_user_id": user.id,
#         "to_chat_room_id": chat_room.id
#     }
#     return await message_manager.create_one(data)


# @router.get("/")
# async def get_chat_rooms(chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager)):
#     return await chat_room_manager.get_all()

@router.get("/messages")
async def get_messages_by_user_id(user: User = Depends(current_user_dependency), message_manager: MessageManager = Depends(get_message_manager)):
    return await message_manager.get_messages_by_user_id(user.id)


@router.get("/messages/{chat_id}")
async def get_messages_by_chat_id(chat_id: UUID, user: User = Depends(current_user_dependency), message_manager: MessageManager = Depends(get_message_manager)):
    return await message_manager.get_messages_by_chat_id(chat_id)


@router.get("/{order_id}")
async def get_order_chat_room(order_id: uuid.UUID, user: User = Depends(current_user_dependency),
                              chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager)):
    return await chat_room_manager.get_order_chat(user, order_id)


@router.get("/")
async def get_chat_rooms(user: User = Depends(current_user_dependency),
                         chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager)):
    return await chat_room_manager.get_all()


# @router.get("/messages/me")
# async def get_my_messages(user: User = Depends(current_user_dependency),
#                           message_manager: MessageManager = Depends(get_message_manager),
#                           chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager)):
#     chat_room = await chat_room_manager.get_my_chat(user)
#     return await message_manager.get_messages_by_chat_id(chat_room.id)




