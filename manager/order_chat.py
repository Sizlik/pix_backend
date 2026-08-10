from dataclasses import dataclass
from uuid import UUID, uuid4

from db.order_chat_repository import (
    NewAttachment,
    NewOutboxEvent,
    OrderChatRepository,
    StoredMessage,
    object_key,
)
from db.schemas.chat import (
    OrderChatAttachmentResponse,
    OrderChatMessageResponse,
    OrderChatPageResponse,
)
from manager.chat_files import validate_upload_batch
from manager.chat_storage import ObjectStorage


@dataclass(frozen=True, slots=True)
class PendingUpload:
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class DownloadedAttachment:
    filename: str
    mime_type: str
    content: bytes


class OrderChatNotFound(LookupError):
    pass


class EmptyOrderChatMessage(ValueError):
    pass


class OrderChatAccessPolicy:
    def __init__(self, moysklad):
        self._moysklad = moysklad

    async def assert_client_access(self, user, order_id: UUID) -> dict:
        order = await self._moysklad.get_order(order_id)
        try:
            href = order["agent"]["meta"]["href"]
            counterparty_id = href.rstrip("/").rsplit("/", 1)[-1]
            expected = str(user.moysklad_counterparty_id)
        except (AttributeError, KeyError, TypeError):
            raise OrderChatNotFound() from None
        if not expected or counterparty_id.lower() != expected.lower():
            raise OrderChatNotFound()
        return order


class OrderChatService:
    def __init__(
        self,
        *,
        repository: OrderChatRepository,
        storage: ObjectStorage,
        access_policy: OrderChatAccessPolicy,
        attachment_max_count: int,
        attachment_max_bytes: int,
        realtime=None,
    ):
        self._repository = repository
        self._storage = storage
        self._access_policy = access_policy
        self._attachment_max_count = attachment_max_count
        self._attachment_max_bytes = attachment_max_bytes
        self._realtime = realtime

    async def list_messages(
        self,
        user,
        order_id: UUID,
        before: UUID | None,
        limit: int,
    ) -> OrderChatPageResponse:
        await self._prepare_order(user, order_id)
        messages, next_before = await self._repository.list_messages(order_id, before, limit)
        return OrderChatPageResponse(
            items=[await self._response(item) for item in messages],
            next_before=next_before,
        )

    async def create_client_message(
        self,
        user,
        order_id: UUID,
        body: str,
        uploads: list[PendingUpload],
    ) -> OrderChatMessageResponse:
        order = await self._prepare_order(user, order_id)
        normalized_body = body.strip()
        if not normalized_body and not uploads:
            raise EmptyOrderChatMessage()
        validated = validate_upload_batch(
            [(item.filename, item.content) for item in uploads],
            self._attachment_max_count,
            self._attachment_max_bytes,
        )

        message_id = uuid4()
        new_attachments: list[NewAttachment] = []
        stored_keys: list[str] = []
        try:
            for upload in validated:
                attachment_id = uuid4()
                key = object_key(order_id, message_id, attachment_id)
                await self._storage.put(key, upload.content, upload.mime_type)
                stored_keys.append(key)
                new_attachments.append(
                    NewAttachment(
                        id=attachment_id,
                        object_key=key,
                        original_filename=upload.filename,
                        mime_type=upload.mime_type,
                        size_bytes=upload.size_bytes,
                        sha256=upload.sha256,
                        origin="site",
                    )
                )

            events = (
                NewOutboxEvent(
                    event_type="sync_order",
                    order_id=order_id,
                    dedup_key=f"sync_order:{message_id}",
                    payload={"message_id": str(message_id)},
                ),
                NewOutboxEvent(
                    event_type="telegram_client_alert",
                    order_id=order_id,
                    dedup_key=f"telegram_client:{message_id}",
                    payload={
                        "message_id": str(message_id),
                        "order_name": order.get("name", str(order_id)),
                        "client_name": user.first_name,
                        "client_number": user.name_id,
                        "filenames": [upload.filename for upload in validated],
                    },
                ),
            )
            stored = await self._repository.create_message(
                message_id=message_id,
                order_id=order_id,
                client_id=user.id,
                sender_kind="client",
                source="site",
                body=normalized_body,
                attachments=tuple(new_attachments),
                outbox_events=events,
            )
        except Exception:
            for key in stored_keys:
                await self._storage.delete(key)
            raise
        response = await self._response(stored)
        if self._realtime is not None:
            try:
                await self._realtime.publish(str(order_id), response.model_dump(mode="json"))
            except Exception:
                pass
        return response

    async def get_attachment(self, user, attachment_id: UUID) -> DownloadedAttachment:
        record = await self._repository.get_attachment_for_client(attachment_id)
        if record is None:
            raise OrderChatNotFound()
        attachment, message = record
        await self._access_policy.assert_client_access(user, message.order_id)
        return DownloadedAttachment(
            filename=attachment.original_filename,
            mime_type=attachment.mime_type,
            content=await self._storage.read(attachment.object_key),
        )

    async def _prepare_order(self, user, order_id: UUID) -> dict:
        order = await self._access_policy.assert_client_access(user, order_id)
        try:
            await self._repository.ensure_state(order_id, user.id)
        except LookupError:
            raise OrderChatNotFound() from None
        await self._repository.import_legacy_messages(order_id, user.id)
        return order

    async def _response(self, message: StoredMessage) -> OrderChatMessageResponse:
        sender_label = "Менеджер Pix Logistic" if message.sender_kind == "manager" else "Клиент"
        return OrderChatMessageResponse(
            id=message.id,
            order_id=message.order_id,
            sender_kind=message.sender_kind,
            sender_label=sender_label,
            message=message.body,
            created_at=message.created_at,
            attachments=[
                OrderChatAttachmentResponse(
                    id=item.id,
                    filename=item.original_filename,
                    mime_type=item.mime_type,
                    size_bytes=item.size_bytes,
                )
                for item in message.attachments
            ],
            delivery_state=await self._repository.delivery_state_for(message),
        )
