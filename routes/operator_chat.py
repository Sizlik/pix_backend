import asyncio
from inspect import isawaitable
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from db.schemas.chat import (
    ConversationPage,
    OperatorReadResponse,
    OrderChatMessageResponse,
    OrderChatPageResponse,
)
from dependecies.chat import get_chat_realtime
from dependecies.operator_inbox import get_operator_inbox_realtime
from dependecies.order_chat import get_operator_chat_authenticator, get_order_chat_service
from errors import IntegrationNotConfigured, MoySkladOrderLookupUnavailable
from manager.chat_files import ChatFileRejected
from manager.order_chat import (
    EmptyOrderChatMessage,
    OrderChatNotFound,
    OrderChatService,
    PendingUpload,
)
from manager.order_chat_auth import OperatorChatAuthenticator


def require_operator_chat_enabled(request: Request) -> None:
    if not request.app.state.settings.enable_moysklad_order_chat:
        raise IntegrationNotConfigured("moysklad order chat")


router = APIRouter(
    prefix="/chat/operator",
    tags=["Operator Order Chat"],
)


async def require_operator_chat_secret(
    secret: Annotated[str | None, Header(alias="X-Pix-Chat-Secret")] = None,
    authenticator: OperatorChatAuthenticator = Depends(get_operator_chat_authenticator),
) -> None:
    if not authenticator.matches(secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


operator_rest_dependencies = [
    Depends(require_operator_chat_enabled),
    Depends(require_operator_chat_secret),
]


def _resource_id(value: str, detail: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise HTTPException(status_code=404, detail=detail) from error


def _lookup_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Chat temporarily unavailable")


@router.get(
    "/conversations",
    response_model=ConversationPage,
    dependencies=operator_rest_dependencies,
)
async def list_operator_conversations(
    before: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    service: OrderChatService = Depends(get_order_chat_service),
):
    try:
        return await service.list_operator_conversations(before, limit)
    except OrderChatNotFound as error:
        raise HTTPException(status_code=404, detail="Order not found") from error
    except MoySkladOrderLookupUnavailable as error:
        raise _lookup_unavailable() from error


@router.post(
    "/orders/{order_id}/read",
    response_model=OperatorReadResponse,
    dependencies=operator_rest_dependencies,
)
async def mark_operator_order_read(
    order_id: str,
    service: OrderChatService = Depends(get_order_chat_service),
):
    parsed_order_id = _resource_id(order_id, "Order not found")
    try:
        return await service.mark_operator_read(parsed_order_id)
    except OrderChatNotFound as error:
        raise HTTPException(status_code=404, detail="Order not found") from error
    except MoySkladOrderLookupUnavailable as error:
        raise _lookup_unavailable() from error


@router.get(
    "/orders/{order_id}/messages",
    response_model=OrderChatPageResponse,
    dependencies=operator_rest_dependencies,
)
async def list_operator_order_messages(
    order_id: str,
    before: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    service: OrderChatService = Depends(get_order_chat_service),
):
    parsed_order_id = _resource_id(order_id, "Order not found")
    try:
        return await service.list_operator_messages(parsed_order_id, before, limit)
    except OrderChatNotFound as error:
        raise HTTPException(status_code=404, detail="Order not found") from error
    except MoySkladOrderLookupUnavailable as error:
        raise _lookup_unavailable() from error


@router.post(
    "/orders/{order_id}/messages",
    response_model=OrderChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=operator_rest_dependencies,
)
async def send_operator_order_message(
    order_id: str,
    message: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    service: OrderChatService = Depends(get_order_chat_service),
):
    parsed_order_id = _resource_id(order_id, "Order not found")
    uploads = [PendingUpload(file.filename or "file", await file.read()) for file in files]
    if not (message or "").strip() and not uploads:
        raise HTTPException(
            status_code=422,
            detail="Message text or at least one file is required",
        )
    try:
        return await service.create_manager_message(parsed_order_id, message or "", uploads)
    except OrderChatNotFound as error:
        raise HTTPException(status_code=404, detail="Order not found") from error
    except (EmptyOrderChatMessage, ChatFileRejected) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MoySkladOrderLookupUnavailable as error:
        raise _lookup_unavailable() from error


@router.get(
    "/orders/{order_id}/attachments/{attachment_id}",
    dependencies=operator_rest_dependencies,
)
async def download_operator_order_attachment(
    order_id: str,
    attachment_id: str,
    service: OrderChatService = Depends(get_order_chat_service),
):
    parsed_order_id = _resource_id(order_id, "Order not found")
    parsed_attachment_id = _resource_id(attachment_id, "File not found")
    try:
        download = await service.get_operator_attachment(parsed_order_id, parsed_attachment_id)
    except OrderChatNotFound as error:
        raise HTTPException(status_code=404, detail="File not found") from error
    except MoySkladOrderLookupUnavailable as error:
        raise _lookup_unavailable() from error
    disposition = f"attachment; filename=download; filename*=UTF-8''{quote(download.filename, safe='')}"
    return Response(
        content=download.content,
        media_type=download.mime_type,
        headers={"Content-Disposition": disposition},
    )


async def receive_operator_authentication(
    websocket: WebSocket,
    authenticator: OperatorChatAuthenticator,
    *,
    timeout_seconds: float = 5,
) -> bool:
    try:
        async with asyncio.timeout(timeout_seconds):
            frame = await websocket.receive_json()
    except (TimeoutError, ValueError, TypeError, WebSocketDisconnect):
        return False
    return (
        isinstance(frame, dict)
        and set(frame) == {"type", "secret"}
        and frame.get("type") == "authenticate"
        and isinstance(frame.get("secret"), str)
        and authenticator.matches(frame["secret"])
    )


async def _socket_dependency(websocket: WebSocket, provider):
    dependency = websocket.app.dependency_overrides.get(provider, provider)
    value = dependency()
    return await value if isawaitable(value) else value


async def register_authenticated_socket(websocket, realtime, room_id: str) -> None:
    await realtime.register(room_id, websocket)
    try:
        await websocket.send_json({"type": "authenticated"})
    except BaseException:
        await realtime.disconnect(room_id, websocket)
        raise


@router.websocket("/ws")
async def operator_chat_websocket(websocket: WebSocket):
    room = websocket.query_params.get("room")
    await websocket.accept()
    if not websocket.app.state.settings.enable_moysklad_order_chat or not room:
        await websocket.close(code=4404)
        return
    try:
        order_id = UUID(room)
    except (TypeError, ValueError):
        await websocket.close(code=4404)
        return

    try:
        authenticator = await _socket_dependency(websocket, get_operator_chat_authenticator)
    except IntegrationNotConfigured:
        await websocket.close(code=4404)
        return
    if not await receive_operator_authentication(websocket, authenticator, timeout_seconds=5):
        await websocket.close(code=4401)
        return

    try:
        service = await _socket_dependency(websocket, get_order_chat_service)
        await service.prepare_operator_order(order_id)
    except (OrderChatNotFound, IntegrationNotConfigured, MoySkladOrderLookupUnavailable):
        await websocket.close(code=4404)
        return

    registered = False
    realtime = None
    try:
        realtime = await _socket_dependency(websocket, get_chat_realtime)
        await register_authenticated_socket(websocket, realtime, str(order_id))
        registered = True
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
        if registered:
            await realtime.disconnect(str(order_id), websocket)


@router.websocket("/inbox/ws")
async def operator_inbox_websocket(websocket: WebSocket):
    await websocket.accept()
    if not websocket.app.state.settings.enable_moysklad_order_chat:
        await websocket.close(code=4404)
        return
    try:
        authenticator = await _socket_dependency(
            websocket,
            get_operator_chat_authenticator,
        )
    except IntegrationNotConfigured:
        await websocket.close(code=4404)
        return
    if not await receive_operator_authentication(
        websocket,
        authenticator,
        timeout_seconds=5,
    ):
        await websocket.close(code=4401)
        return

    registered = False
    realtime = None
    try:
        realtime = await _socket_dependency(
            websocket,
            get_operator_inbox_realtime,
        )
        await register_authenticated_socket(websocket, realtime, "global")
        registered = True
        while True:
            await websocket.receive_json()
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "operator_inbox_read_only",
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        if registered:
            await realtime.disconnect("global", websocket)
