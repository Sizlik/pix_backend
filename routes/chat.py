# import requests
import uuid
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi_users.authentication import RedisStrategy

from bot.sender import telegram_sender
from db.models.users import User, UserDatabase, get_user_db
from db.redis import get_redis_strategy
from db.schemas.chat import OrderChatMessageResponse, OrderChatPageResponse
from db.schemas.notifications import NotificationCreate, NotificationTypes
from dependecies.chat import get_chat_manager, get_chat_room_manager, get_message_manager
from dependecies.notifications import get_notification_manager
from dependecies.order_chat import (
    get_order_chat_access_policy,
    get_order_chat_service,
)
from errors import IntegrationNotConfigured
from manager.chat import ChatManager, ChatRoomManager, MessageManager
from manager.chat_files import ChatFileRejected
from manager.notifications import NotificationManager
from manager.order_chat import (
    EmptyOrderChatMessage,
    OrderChatAccessPolicy,
    OrderChatNotFound,
    OrderChatService,
    PendingUpload,
)
from manager.users import get_user_manager
from routes.users import current_user_dependency

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.get(
    "/orders/{order_id}/messages",
    response_model=OrderChatPageResponse,
)
async def list_order_messages(
    order_id: UUID,
    before: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(current_user_dependency),
    service: OrderChatService = Depends(get_order_chat_service),
):
    try:
        return await service.list_messages(user, order_id, before, limit)
    except OrderChatNotFound as error:
        raise HTTPException(status_code=404, detail="Order not found") from error


@router.post(
    "/orders/{order_id}/messages",
    response_model=OrderChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_order_message(
    order_id: UUID,
    message: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    user: User = Depends(current_user_dependency),
    service: OrderChatService = Depends(get_order_chat_service),
):
    uploads = [PendingUpload(file.filename or "file", await file.read()) for file in files]
    if not (message or "").strip() and not uploads:
        raise HTTPException(
            status_code=422,
            detail="Message text or at least one file is required",
        )
    try:
        return await service.create_client_message(user, order_id, message or "", uploads)
    except OrderChatNotFound as error:
        raise HTTPException(status_code=404, detail="Order not found") from error
    except (EmptyOrderChatMessage, ChatFileRejected) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/attachments/{attachment_id}")
async def download_order_chat_attachment(
    attachment_id: UUID,
    user: User = Depends(current_user_dependency),
    service: OrderChatService = Depends(get_order_chat_service),
):
    try:
        download = await service.get_attachment(user, attachment_id)
    except OrderChatNotFound as error:
        raise HTTPException(status_code=404, detail="File not found") from error
    disposition = f"attachment; filename=download; filename*=UTF-8''{quote(download.filename, safe='')}"
    return Response(
        content=download.content,
        media_type=download.mime_type,
        headers={"Content-Disposition": disposition},
    )


@router.websocket("/ws")
async def websocket_connection(
    websocket: WebSocket,
    redis_strategy: RedisStrategy = Depends(get_redis_strategy),
    user_manager=Depends(get_user_manager),
    chat_manager: ChatManager = Depends(get_chat_manager),
    order_access_policy: OrderChatAccessPolicy = Depends(get_order_chat_access_policy),
):
    token = websocket.query_params.get("auth")
    if not token:
        await websocket.close(code=4401)
        return
    user = await redis_strategy.read_token(token, user_manager)

    if not user:
        await websocket.close(code=4401)
        return

    room_id = websocket.query_params.get("room", str(user.id))
    support_room = str(room_id) == str(user.id)
    if not support_room:
        try:
            order_id = UUID(str(room_id))
            await order_access_policy.assert_client_access(user, order_id)
        except (ValueError, OrderChatNotFound, IntegrationNotConfigured):
            await websocket.close(code=4404)
            return
    await chat_manager.connect(room_id, websocket)

    try:
        while True:
            ws_data = await websocket.receive_json()
            if not support_room:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "order_chat_http_required",
                    }
                )
                continue
            await chat_manager.send_message_from_client(
                {
                    "message": ws_data["message"],
                    "from_user_id": str(user.id),
                    "to_chat_room_id": str(user.id),
                },
                room_id,
                user,
            )

    except WebSocketDisconnect:
        pass
    finally:
        await chat_manager.disconnect(room_id, websocket)


@router.post("/send_message")
async def send_message_by_endpoint(
    message: str = Body(),
    to_chat_room: str = Body(),
    client_id: str = Body(),
    user=Depends(current_user_dependency),
    chat_manager: ChatManager = Depends(get_chat_manager),
    notification_manager: NotificationManager = Depends(get_notification_manager),
    user_db: UserDatabase = Depends(get_user_db),
):
    if str(client_id) != str(to_chat_room):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "order_reply_in_moysklad_required",
                "message": "Reply in the MoySklad customer order comment",
            },
        )
    if user.email == "bot@pixlogistic.com":
        data = {"message": message, "from_user_id": str(user.id), "to_chat_room_id": to_chat_room}
        message_id = await chat_manager.send_message_from_client(data, to_chat_room, user)
        notification_data = NotificationCreate(
            user_id=client_id,
            type=NotificationTypes.MESSAGE.value
            if client_id == to_chat_room
            else NotificationTypes.ORDER_MESSAGE.value,
            object_id=str(message_id),
        )
        await notification_manager.create_notification(notification_data)
        client = await user_db.get(client_id)
        if client.telegram_id:
            await telegram_sender.send_user_message(
                client.telegram_id,
                f'У вас новое сообщение от менеджера на <a href="https://client.pixlogistic.com/dashboard/notifications">сайте</a>\n\n{message}',
                disable_web_page_preview=True,
            )


@router.post("/{order_id}")
async def create_order_chat_room(
    order_id: uuid.UUID,
    user: User = Depends(current_user_dependency),
    chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager),
):
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
async def get_messages_by_user_id(
    user: User = Depends(current_user_dependency), message_manager: MessageManager = Depends(get_message_manager)
):
    return await message_manager.get_messages_by_user_id(user.id)


@router.get("/messages/{chat_id}")
async def get_messages_by_chat_id(
    chat_id: UUID,
    user: User = Depends(current_user_dependency),
    message_manager: MessageManager = Depends(get_message_manager),
):
    return await message_manager.get_messages_by_chat_id(chat_id)


@router.get("/{order_id}")
async def get_order_chat_room(
    order_id: uuid.UUID,
    user: User = Depends(current_user_dependency),
    chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager),
):
    return await chat_room_manager.get_order_chat(user, order_id)


@router.get("/")
async def get_chat_rooms(
    user: User = Depends(current_user_dependency), chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager)
):
    return await chat_room_manager.get_all()


# @router.get("/messages/me")
# async def get_my_messages(user: User = Depends(current_user_dependency),
#                           message_manager: MessageManager = Depends(get_message_manager),
#                           chat_room_manager: ChatRoomManager = Depends(get_chat_room_manager)):
#     chat_room = await chat_room_manager.get_my_chat(user)
#     return await message_manager.get_messages_by_chat_id(chat_room.id)
