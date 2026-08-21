from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models.notifications import Notifications
from db.models.order_chat import (
    OrderChatAttachment,
    OrderChatMessage,
    OrderChatState,
)
from db.models.users import User
from db.postgres import async_session_maker


class OrderChatNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class NewAttachment:
    id: UUID
    object_key: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    origin: str
    origin_external_file_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class StoredMessage:
    id: UUID
    order_id: UUID
    client_id: UUID
    sender_kind: str
    source: str
    body: str
    created_at: datetime
    attachments: tuple[OrderChatAttachment, ...]
    external_key: str | None = None


def object_key(order_id: UUID, message_id: UUID, attachment_id: UUID) -> str:
    return f"orders/{order_id}/messages/{message_id}/attachments/{attachment_id}"


def _stored_message(
    message: OrderChatMessage,
    attachments: tuple[OrderChatAttachment, ...] = (),
) -> StoredMessage:
    return StoredMessage(
        id=message.id,
        order_id=message.order_id,
        client_id=message.client_id,
        sender_kind=message.sender_kind,
        source=message.source,
        body=message.body,
        created_at=message.created_at,
        attachments=attachments,
        external_key=message.external_key,
    )


class OrderChatRepository:
    def __init__(self, session_factory=async_session_maker):
        self._session_factory = session_factory

    async def ensure_state(self, order_id: UUID, client_id: UUID) -> OrderChatState:
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(OrderChatState).where(OrderChatState.order_id == order_id).with_for_update()
                )
                state = result.scalar_one_or_none()
                if state is not None:
                    if state.client_id != client_id:
                        raise OrderChatNotFound()
                    return state

                state = OrderChatState(order_id=order_id, client_id=client_id)
                session.add(state)
                await session.flush()
                return state

    async def get_state(self, order_id: UUID) -> OrderChatState | None:
        async with self._session_factory() as session:
            result = await session.execute(select(OrderChatState).where(OrderChatState.order_id == order_id))
            return result.scalar_one_or_none()

    async def update_state(self, order_id: UUID, **values) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(OrderChatState)
                    .where(OrderChatState.order_id == order_id)
                    .values(**values, updated_at=func.now())
                )

    async def get_state_client(self, order_id: UUID) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User)
                .join(OrderChatState, OrderChatState.client_id == User.id)
                .where(OrderChatState.order_id == order_id)
            )
            return result.scalar_one_or_none()

    async def get_user_by_moysklad_counterparty(self, counterparty_id: UUID) -> User | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(User).where(User.moysklad_counterparty_id == counterparty_id).limit(2)
            )
            users = list(result.scalars())
            return users[0] if len(users) == 1 else None

    async def create_message(
        self,
        *,
        message_id: UUID,
        order_id: UUID,
        client_id: UUID,
        sender_kind: str,
        source: str,
        body: str,
        attachments: tuple[NewAttachment, ...] = (),
        external_key: str | None = None,
        legacy_message_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> StoredMessage:
        async with self._session_factory() as session:
            async with session.begin():
                message, inserted = await self._insert_message(
                    session,
                    message_id=message_id,
                    order_id=order_id,
                    client_id=client_id,
                    sender_kind=sender_kind,
                    source=source,
                    body=body,
                    external_key=external_key,
                    legacy_message_id=legacy_message_id,
                    created_at=created_at,
                )
                if inserted:
                    stored_attachments = await self._insert_attachments(session, message.id, attachments)
                else:
                    stored_attachments = await self._load_attachments(session, message.id)
                return _stored_message(message, stored_attachments)

    async def create_manager_message_with_notification(
        self,
        *,
        message_id: UUID,
        order_id: UUID,
        client_id: UUID,
        body: str,
        source: str = "moysklad",
        external_key: str | None = None,
        attachments: tuple[NewAttachment, ...] = (),
        created_at: datetime | None = None,
    ) -> StoredMessage:
        async with self._session_factory() as session:
            async with session.begin():
                message, inserted = await self._insert_message(
                    session,
                    message_id=message_id,
                    order_id=order_id,
                    client_id=client_id,
                    sender_kind="manager",
                    source=source,
                    body=body,
                    external_key=external_key,
                    legacy_message_id=None,
                    created_at=created_at,
                )
                if inserted:
                    stored_attachments = await self._insert_attachments(session, message.id, attachments)
                    session.add(
                        Notifications(
                            user_id=client_id,
                            type="ORDER_MESSAGE",
                            object_id=message.id,
                        )
                    )
                else:
                    stored_attachments = await self._load_attachments(session, message.id)
                return _stored_message(message, stored_attachments)

    async def list_messages(
        self,
        order_id: UUID,
        before: UUID | None,
        limit: int,
    ) -> tuple[list[StoredMessage], UUID | None]:
        async with self._session_factory() as session:
            cursor = None
            if before is not None:
                result = await session.execute(
                    select(OrderChatMessage).where(
                        OrderChatMessage.id == before,
                        OrderChatMessage.order_id == order_id,
                    )
                )
                cursor = result.scalar_one_or_none()
                if cursor is None:
                    raise OrderChatNotFound()

            statement = select(OrderChatMessage).where(OrderChatMessage.order_id == order_id)
            if cursor is not None:
                statement = statement.where(
                    or_(
                        OrderChatMessage.created_at < cursor.created_at,
                        and_(
                            OrderChatMessage.created_at == cursor.created_at,
                            OrderChatMessage.id < cursor.id,
                        ),
                    )
                )
            result = await session.execute(
                statement.order_by(
                    OrderChatMessage.created_at.desc(),
                    OrderChatMessage.id.desc(),
                ).limit(limit + 1)
            )
            descending = list(result.scalars())
            has_more = len(descending) > limit
            selected = descending[:limit]
            attachments = await self._attachments_by_message(session, [message.id for message in selected])
            messages = [
                _stored_message(message, tuple(attachments.get(message.id, ()))) for message in reversed(selected)
            ]
            next_before = selected[-1].id if has_more and selected else None
            return messages, next_before

    async def list_transcript(self, order_id: UUID) -> list[StoredMessage]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderChatMessage)
                .where(OrderChatMessage.order_id == order_id)
                .order_by(OrderChatMessage.created_at, OrderChatMessage.id)
            )
            rows = list(result.scalars())
            attachments = await self._attachments_by_message(session, [row.id for row in rows])
            return [_stored_message(row, tuple(attachments.get(row.id, ()))) for row in rows]

    async def get_message(self, message_id: UUID) -> StoredMessage | None:
        async with self._session_factory() as session:
            result = await session.execute(select(OrderChatMessage).where(OrderChatMessage.id == message_id))
            message = result.scalar_one_or_none()
            if message is None:
                return None
            attachments = await self._load_attachments(session, message.id)
            return _stored_message(message, attachments)

    async def get_message_by_external_key(self, external_key: str) -> StoredMessage | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderChatMessage).where(OrderChatMessage.external_key == external_key)
            )
            message = result.scalar_one_or_none()
            if message is None:
                return None
            attachments = await self._load_attachments(session, message.id)
            return _stored_message(message, attachments)

    async def get_attachment_for_client(self, attachment_id: UUID) -> tuple[OrderChatAttachment, StoredMessage] | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderChatAttachment, OrderChatMessage)
                .join(
                    OrderChatMessage,
                    OrderChatMessage.id == OrderChatAttachment.message_id,
                )
                .where(OrderChatAttachment.id == attachment_id)
            )
            row = result.one_or_none()
            if row is None:
                return None
            attachment, message = row
            return attachment, _stored_message(message, (attachment,))

    async def get_attachment_for_order(
        self,
        order_id: UUID,
        attachment_id: UUID,
    ) -> tuple[OrderChatAttachment, StoredMessage] | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(OrderChatAttachment, OrderChatMessage)
                .join(
                    OrderChatMessage,
                    OrderChatMessage.id == OrderChatAttachment.message_id,
                )
                .where(
                    OrderChatAttachment.id == attachment_id,
                    OrderChatMessage.order_id == order_id,
                )
            )
            row = result.one_or_none()
            if row is None:
                return None
            attachment, message = row
            return attachment, _stored_message(message, (attachment,))

    async def _insert_message(
        self,
        session,
        *,
        message_id: UUID,
        order_id: UUID,
        client_id: UUID,
        sender_kind: str,
        source: str,
        body: str,
        external_key: str | None,
        legacy_message_id: UUID | None,
        created_at: datetime | None,
    ) -> tuple[OrderChatMessage, bool]:
        values = {
            "id": message_id,
            "order_id": order_id,
            "client_id": client_id,
            "sender_kind": sender_kind,
            "source": source,
            "body": body,
            "external_key": external_key,
            "legacy_message_id": legacy_message_id,
        }
        if created_at is not None:
            values["created_at"] = created_at
        result = await session.execute(
            pg_insert(OrderChatMessage).values(**values).on_conflict_do_nothing().returning(OrderChatMessage)
        )
        message = result.scalar_one_or_none()
        if message is not None:
            return message, True
        predicates = [OrderChatMessage.id == message_id]
        if external_key is not None:
            predicates.append(OrderChatMessage.external_key == external_key)
        if legacy_message_id is not None:
            predicates.append(OrderChatMessage.legacy_message_id == legacy_message_id)
        existing = await session.execute(select(OrderChatMessage).where(or_(*predicates)))
        message = existing.scalars().first()
        if message is None:
            raise RuntimeError("message insert conflict could not be resolved")
        return message, False

    async def _insert_attachments(
        self,
        session,
        message_id: UUID,
        attachments: tuple[NewAttachment, ...],
    ) -> tuple[OrderChatAttachment, ...]:
        models = tuple(
            OrderChatAttachment(
                id=item.id,
                message_id=message_id,
                object_key=item.object_key,
                original_filename=item.original_filename,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                origin=item.origin,
                origin_external_file_id=item.origin_external_file_id,
            )
            for item in attachments
        )
        session.add_all(models)
        await session.flush()
        return models

    async def _load_attachments(self, session, message_id: UUID) -> tuple[OrderChatAttachment, ...]:
        result = await session.execute(
            select(OrderChatAttachment)
            .where(OrderChatAttachment.message_id == message_id)
            .order_by(OrderChatAttachment.created_at, OrderChatAttachment.id)
        )
        return tuple(result.scalars())

    async def _attachments_by_message(self, session, message_ids: list[UUID]) -> dict[UUID, list[OrderChatAttachment]]:
        if not message_ids:
            return {}
        result = await session.execute(
            select(OrderChatAttachment)
            .where(OrderChatAttachment.message_id.in_(message_ids))
            .order_by(OrderChatAttachment.created_at, OrderChatAttachment.id)
        )
        grouped: dict[UUID, list[OrderChatAttachment]] = {}
        for attachment in result.scalars():
            grouped.setdefault(attachment.message_id, []).append(attachment)
        return grouped
