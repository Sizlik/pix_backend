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
    status,
)

from db.schemas.chat import OrderChatMessageResponse, OrderChatPageResponse
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
    dependencies=[Depends(require_operator_chat_enabled)],
)


async def require_operator_chat_secret(
    secret: Annotated[str | None, Header(alias="X-Pix-Chat-Secret")] = None,
    authenticator: OperatorChatAuthenticator = Depends(get_operator_chat_authenticator),
) -> None:
    if not authenticator.matches(secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _resource_id(value: str, detail: str) -> UUID:
    try:
        return UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise HTTPException(status_code=404, detail=detail) from error


def _lookup_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Chat temporarily unavailable")


@router.get(
    "/orders/{order_id}/messages",
    response_model=OrderChatPageResponse,
    dependencies=[Depends(require_operator_chat_secret)],
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
    dependencies=[Depends(require_operator_chat_secret)],
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
    dependencies=[Depends(require_operator_chat_secret)],
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
