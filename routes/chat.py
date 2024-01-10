# import requests
import uuid
from uuid import UUID

import jwt
import requests
from fastapi import APIRouter, WebSocket, Depends, WebSocketDisconnect, Body
from fastapi_users.authentication import RedisStrategy

from db.models.users import User
from db.redis import get_redis_strategy
from dependecies.chat import get_chat_manager, get_chat_room_manager, get_message_manager
from manager.chat import ChatManager, ChatRoomManager, MessageManager
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

    room_id = websocket.query_params["room"]

    await chat_manager.connect(room_id, websocket)

    try:
        while True:
            ws_data = await websocket.receive_json()
            data = {
                "message": ws_data["message"],
                "from_user_id": str(user.id),
                "to_chat_room_id": ws_data["to_chat_room_id"],
            }
            await chat_manager.send_message_from_client(data, room_id, user)

    except WebSocketDisconnect:
        chat_manager.disconnect(room_id, websocket)


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


@router.get("/messages/{chat_id}")
async def get_messages_by_chat_id(chat_id: UUID, user: User = Depends(current_user_dependency), message_manager: MessageManager = Depends(get_message_manager)):
    return await message_manager.get_messages_by_chat_id(chat_id)


