from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
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

from db.models.users import User
from db.redis import get_redis_strategy
from db.schemas.chat import OrderChatMessageResponse, OrderChatPageResponse
from dependecies.chat import get_chat_realtime
from dependecies.order_chat import (
    get_order_chat_access_policy,
    get_order_chat_service,
)
from errors import IntegrationNotConfigured
from manager.chat_files import ChatFileRejected
from manager.order_chat import (
    EmptyOrderChatMessage,
    OrderChatAccessPolicy,
    OrderChatNotFound,
    OrderChatService,
    PendingUpload,
)
from manager.users import authenticate_websocket_user
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
    realtime=Depends(get_chat_realtime),
    order_access_policy: OrderChatAccessPolicy = Depends(get_order_chat_access_policy),
):
    token = websocket.query_params.get("auth")
    if not token:
        await websocket.close(code=4401)
        return
    user = await authenticate_websocket_user(token, redis_strategy)

    if not user:
        await websocket.close(code=4401)
        return

    room_id = websocket.query_params.get("room")
    if not room_id:
        await websocket.close(code=4400)
        return
    try:
        order_id = UUID(room_id)
        await order_access_policy.assert_client_access(user, order_id)
    except (ValueError, OrderChatNotFound, IntegrationNotConfigured):
        await websocket.close(code=4404)
        return

    await realtime.connect(room_id, websocket)

    try:
        while True:
            await websocket.receive_json()
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "order_chat_http_required",
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        await realtime.disconnect(room_id, websocket)
