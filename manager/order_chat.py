import asyncio
import logging
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

from db.order_chat_repository import (
    NewAttachment,
    NewEmailDelivery,
    OrderChatRepository,
    StoredConversation,
    StoredMessage,
    object_key,
)
from db.schemas.chat import (
    ConversationLastMessage,
    ConversationPage,
    ConversationSummary,
    ConversationUpdatedEvent,
    OperatorReadResponse,
    OrderChatAttachmentResponse,
    OrderChatMessageResponse,
    OrderChatPageResponse,
)
from errors import MoySkladOrderLookupUnavailable
from manager.chat_files import validate_upload_batch
from manager.chat_storage import ObjectStorage
from manager.order_chat_email import safe_message_preview

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PendingUpload:
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class DownloadedAttachment:
    filename: str
    mime_type: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ResolvedOperatorOrder:
    client: object
    order_name: str | None


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


class OperatorOrderChatAccessPolicy:
    def __init__(self, moysklad, repository: OrderChatRepository):
        self._moysklad = moysklad
        self._repository = repository

    async def resolve_client(self, order_id: UUID):
        order = await self._moysklad.get_order(order_id)
        try:
            href = order["agent"]["meta"]["href"]
            counterparty_id = UUID(href.rstrip("/").rsplit("/", 1)[-1])
        except (AttributeError, KeyError, TypeError, ValueError):
            raise OrderChatNotFound() from None
        client = await self._repository.get_state_client(order_id)
        if client is not None:
            if client.moysklad_counterparty_id != counterparty_id:
                raise OrderChatNotFound()
        else:
            client = await self._repository.get_user_by_moysklad_counterparty(counterparty_id)
            if client is None:
                raise OrderChatNotFound()
        try:
            await self._repository.ensure_state(order_id, client.id)
        except LookupError:
            raise OrderChatNotFound() from None
        return ResolvedOperatorOrder(
            client=client,
            order_name=_order_name(order),
        )


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
        operator_access_policy: OperatorOrderChatAccessPolicy | None = None,
        notification_manager=None,
        inbox_realtime=None,
        manager_email: str | None = None,
    ):
        self._repository = repository
        self._storage = storage
        self._access_policy = access_policy
        self._attachment_max_count = attachment_max_count
        self._attachment_max_bytes = attachment_max_bytes
        self._realtime = realtime
        self._operator_access_policy = operator_access_policy
        self._notification_manager = notification_manager
        self._inbox_realtime = inbox_realtime
        self._manager_email = manager_email

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

    async def list_operator_messages(
        self,
        order_id: UUID,
        before: UUID | None,
        limit: int,
    ) -> OrderChatPageResponse:
        await self.prepare_operator_order(order_id)
        messages, next_before = await self._repository.list_messages(order_id, before, limit)
        return OrderChatPageResponse(
            items=[await self._response(item) for item in messages],
            next_before=next_before,
        )

    async def list_operator_conversations(
        self,
        before: UUID | None,
        limit: int,
    ) -> ConversationPage:
        conversations, next_before = await self._repository.list_conversations(
            before,
            limit,
        )
        hydrated = await self._hydrate_missing_order_names(conversations)
        total_unread = await self._repository.total_operator_unread()
        return ConversationPage(
            items=[self._conversation_response(item) for item in hydrated],
            next_before=next_before,
            total_unread=total_unread,
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
        new_attachments: tuple[NewAttachment, ...] = ()
        stored_keys: tuple[str, ...] = ()
        try:
            new_attachments, stored_keys = await self._store_attachments(
                order_id,
                message_id,
                validated,
                origin="site",
            )
            stored = await self._repository.create_client_message_with_delivery(
                message_id=message_id,
                order_id=order_id,
                client_id=user.id,
                source="site",
                body=normalized_body,
                attachments=new_attachments,
                order_name=_order_name(order),
                email_delivery=(
                    NewEmailDelivery(self._manager_email, "manager")
                    if self._manager_email is not None
                    else None
                ),
            )
        except Exception:
            for key in stored_keys:
                await self._storage.delete(key)
            raise
        response = await self._response(stored)
        await self._publish_message(order_id, response)
        await self._publish_inbox_update(order_id)
        return response

    async def create_manager_message(
        self,
        order_id: UUID,
        body: str,
        uploads: list[PendingUpload],
    ) -> OrderChatMessageResponse:
        resolved = await self.prepare_operator_order(order_id)
        client = resolved.client
        normalized_body = body.strip()
        if not normalized_body and not uploads:
            raise EmptyOrderChatMessage()
        validated = validate_upload_batch(
            [(item.filename, item.content) for item in uploads],
            self._attachment_max_count,
            self._attachment_max_bytes,
        )

        message_id = uuid4()
        new_attachments: tuple[NewAttachment, ...] = ()
        stored_keys: tuple[str, ...] = ()
        try:
            new_attachments, stored_keys = await self._store_attachments(
                order_id,
                message_id,
                validated,
                origin="extension",
            )
            stored = await self._repository.create_manager_message_with_notification(
                message_id=message_id,
                order_id=order_id,
                client_id=client.id,
                body=normalized_body,
                source="extension",
                external_key=None,
                attachments=new_attachments,
                order_name=resolved.order_name,
                email_delivery=(
                    NewEmailDelivery(client.email, "client")
                    if self._manager_email is not None
                    else None
                ),
            )
        except Exception:
            for key in stored_keys:
                await self._storage.delete(key)
            raise

        response = await self._response(stored)
        await self._publish_message(order_id, response)
        await self._publish_inbox_update(order_id)
        if self._notification_manager is not None:
            try:
                await self._notification_manager.notify_count_changed(client.id)
            except Exception:
                logger.warning("order chat notification count publication failed")
        return response

    async def mark_operator_read(self, order_id: UUID) -> OperatorReadResponse:
        await self.prepare_operator_order(order_id)
        total_unread = await self._repository.clear_operator_unread(order_id)
        conversation = await self._repository.conversation(order_id)
        if conversation is None:
            raise OrderChatNotFound()
        await self._publish_conversation_update(conversation, total_unread)
        return OperatorReadResponse(
            order_id=order_id,
            total_unread=total_unread,
        )

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

    async def get_operator_attachment(
        self,
        order_id: UUID,
        attachment_id: UUID,
    ) -> DownloadedAttachment:
        await self.prepare_operator_order(order_id)
        record = await self._repository.get_attachment_for_order(order_id, attachment_id)
        if record is None:
            raise OrderChatNotFound()
        attachment, _ = record
        return DownloadedAttachment(
            filename=attachment.original_filename,
            mime_type=attachment.mime_type,
            content=await self._storage.read(attachment.object_key),
        )

    async def prepare_operator_order(self, order_id: UUID):
        if self._operator_access_policy is None:
            raise OrderChatNotFound()
        return await self._operator_access_policy.resolve_client(order_id)

    async def _prepare_order(self, user, order_id: UUID) -> dict:
        order = await self._access_policy.assert_client_access(user, order_id)
        try:
            await self._repository.ensure_state(order_id, user.id)
        except LookupError:
            raise OrderChatNotFound() from None
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
        )

    async def _hydrate_missing_order_names(
        self,
        conversations: list[StoredConversation],
    ) -> list[StoredConversation]:
        semaphore = asyncio.Semaphore(5)

        async def hydrate(item: StoredConversation) -> StoredConversation:
            if item.order_name is not None and item.order_name.strip():
                return item
            if self._operator_access_policy is None:
                return item
            try:
                async with semaphore:
                    resolved = await self._operator_access_policy.resolve_client(
                        item.order_id
                    )
            except (MoySkladOrderLookupUnavailable, OrderChatNotFound):
                return item
            if resolved.order_name is None or not resolved.order_name.strip():
                return item
            order_name = resolved.order_name.strip()
            try:
                await self._repository.cache_order_name(
                    item.order_id,
                    order_name,
                )
            except Exception:
                logger.warning("order chat name cache update failed")
            return replace(item, order_name=order_name)

        return list(await asyncio.gather(*(hydrate(item) for item in conversations)))

    @staticmethod
    def _conversation_response(
        conversation: StoredConversation,
    ) -> ConversationSummary:
        message = conversation.last_message
        sender_label = (
            "Менеджер Pix Logistic"
            if message.sender_kind == "manager"
            else "Клиент"
        )
        return ConversationSummary(
            order_id=conversation.order_id,
            order_name=(
                conversation.order_name.strip()
                if conversation.order_name is not None
                and conversation.order_name.strip()
                else _fallback_order_name(conversation.order_id)
            ),
            last_message=ConversationLastMessage(
                id=message.id,
                sender_kind=message.sender_kind,
                sender_label=sender_label,
                message=safe_message_preview(message.body),
                created_at=message.created_at,
                attachment_count=conversation.attachment_count,
            ),
            unread_count=conversation.unread_count,
        )

    async def _store_attachments(
        self,
        order_id: UUID,
        message_id: UUID,
        uploads,
        *,
        origin: str,
    ) -> tuple[tuple[NewAttachment, ...], tuple[str, ...]]:
        attachments: list[NewAttachment] = []
        stored_keys: list[str] = []
        try:
            for upload in uploads:
                attachment_id = uuid4()
                key = object_key(order_id, message_id, attachment_id)
                await self._storage.put(key, upload.content, upload.mime_type)
                stored_keys.append(key)
                attachments.append(
                    NewAttachment(
                        id=attachment_id,
                        object_key=key,
                        original_filename=upload.filename,
                        mime_type=upload.mime_type,
                        size_bytes=upload.size_bytes,
                        sha256=upload.sha256,
                        origin=origin,
                    )
                )
        except Exception:
            for key in stored_keys:
                await self._storage.delete(key)
            raise
        return tuple(attachments), tuple(stored_keys)

    async def _publish_message(
        self,
        order_id: UUID,
        response: OrderChatMessageResponse,
    ) -> None:
        if self._realtime is None:
            return
        try:
            await self._realtime.publish(str(order_id), response.model_dump(mode="json"))
        except Exception:
            logger.warning("order chat room publication failed")

    async def _publish_inbox_update(self, order_id: UUID) -> None:
        if self._inbox_realtime is None:
            return
        try:
            conversation = await self._repository.conversation(order_id)
            if conversation is None:
                return
            total_unread = await self._repository.total_operator_unread()
            await self._publish_conversation_update(
                conversation,
                total_unread,
            )
        except Exception:
            logger.warning("order chat inbox publication failed")

    async def _publish_conversation_update(
        self,
        conversation: StoredConversation,
        total_unread: int,
    ) -> None:
        if self._inbox_realtime is None:
            return
        event = ConversationUpdatedEvent(
            item=self._conversation_response(conversation),
            total_unread=total_unread,
        )
        try:
            await self._inbox_realtime.publish(
                "global",
                event.model_dump(mode="json"),
            )
        except Exception:
            logger.warning("order chat inbox publication failed")


def _order_name(order: dict) -> str | None:
    try:
        name = order.get("name")
    except AttributeError:
        return None
    return name.strip() if isinstance(name, str) and name.strip() else None


def _fallback_order_name(order_id: UUID) -> str:
    return f"…{str(order_id)[-8:]}"
