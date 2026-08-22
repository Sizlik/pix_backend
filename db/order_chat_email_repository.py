from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update

from db.models.order_chat import (
    OrderChatAttachment,
    OrderChatEmailOutbox,
    OrderChatMessage,
    OrderChatState,
)
from db.postgres import async_session_maker
from manager.order_chat_email import OrderChatEmailContent


@dataclass(frozen=True, slots=True)
class ClaimedOrderChatEmail:
    outbox_id: UUID
    attempts: int
    content: OrderChatEmailContent


def _order_name(order_id: UUID, cached_name: str | None) -> str:
    if cached_name is not None and cached_name.strip():
        return cached_name.strip()
    return f"…{str(order_id)[-8:]}"


def _sender_label(sender_kind: str) -> str:
    return "Менеджер Pix Logistic" if sender_kind == "manager" else "Клиент"


class OrderChatEmailOutboxRepository:
    def __init__(self, session_factory=async_session_maker):
        self._session_factory = session_factory

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_before: datetime,
    ) -> list[ClaimedOrderChatEmail]:
        attachment_counts = (
            select(
                OrderChatAttachment.message_id.label("message_id"),
                func.count(OrderChatAttachment.id).label("attachment_count"),
            )
            .group_by(OrderChatAttachment.message_id)
            .subquery()
        )
        statement = (
            select(
                OrderChatEmailOutbox,
                OrderChatMessage,
                OrderChatState,
                func.coalesce(attachment_counts.c.attachment_count, 0),
            )
            .join(
                OrderChatMessage,
                OrderChatMessage.id == OrderChatEmailOutbox.message_id,
            )
            .join(
                OrderChatState,
                OrderChatState.order_id == OrderChatMessage.order_id,
            )
            .outerjoin(
                attachment_counts,
                attachment_counts.c.message_id == OrderChatMessage.id,
            )
            .where(
                or_(
                    and_(
                        OrderChatEmailOutbox.status == "pending",
                        OrderChatEmailOutbox.available_at <= now,
                    ),
                    and_(
                        OrderChatEmailOutbox.status == "processing",
                        OrderChatEmailOutbox.locked_at.is_not(None),
                        OrderChatEmailOutbox.locked_at <= lease_before,
                    ),
                )
            )
            .order_by(
                OrderChatEmailOutbox.available_at,
                OrderChatEmailOutbox.created_at,
                OrderChatEmailOutbox.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True, of=OrderChatEmailOutbox)
        )

        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(statement)
                rows = list(result.all())
                jobs = []
                for outbox, message, state, attachment_count in rows:
                    outbox.status = "processing"
                    outbox.locked_at = now
                    outbox.attempts += 1
                    jobs.append(
                        ClaimedOrderChatEmail(
                            outbox_id=outbox.id,
                            attempts=outbox.attempts,
                            content=OrderChatEmailContent(
                                recipient_email=outbox.recipient_email,
                                recipient_kind=outbox.recipient_kind,
                                order_id=message.order_id,
                                order_name=_order_name(
                                    message.order_id,
                                    state.order_name,
                                ),
                                sender_label=_sender_label(message.sender_kind),
                                message=message.body,
                                attachment_count=int(attachment_count),
                            ),
                        )
                    )
                await session.flush()
                return jobs

    async def mark_sent(self, outbox_id: UUID, *, sent_at: datetime) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(OrderChatEmailOutbox)
                    .where(
                        OrderChatEmailOutbox.id == outbox_id,
                        OrderChatEmailOutbox.status == "processing",
                    )
                    .values(
                        status="sent",
                        sent_at=sent_at,
                        locked_at=None,
                        last_error=None,
                    )
                )

    async def mark_failed(
        self,
        outbox_id: UUID,
        *,
        category: str,
        available_at: datetime | None,
        dead: bool,
    ) -> None:
        values = {
            "status": "dead" if dead else "pending",
            "locked_at": None,
            "last_error": category[:255],
        }
        if available_at is not None:
            values["available_at"] = available_at
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(OrderChatEmailOutbox)
                    .where(
                        OrderChatEmailOutbox.id == outbox_id,
                        OrderChatEmailOutbox.status == "processing",
                    )
                    .values(**values)
                )
