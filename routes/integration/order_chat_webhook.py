import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from db.order_chat_repository import NewOutboxEvent
from db.schemas.chat import MoySkladWebhookPayload
from dependecies.order_chat import get_order_chat_webhook_receiver


class OrderChatWebhookReceiver:
    def __init__(self, *, repository, secret: str):
        self._repository = repository
        self.secret = secret

    async def enqueue(self, request_id: str, payload: MoySkladWebhookPayload) -> int:
        events: list[NewOutboxEvent] = []
        audit = payload.auditContext
        for item in payload.events:
            if item.action != "UPDATE" or item.meta.type != "customerorder":
                continue
            try:
                order_id = UUID(str(item.meta.href).rstrip("/").rsplit("/", 1)[-1])
            except ValueError:
                continue
            events.append(
                NewOutboxEvent(
                    event_type="process_moysklad_update",
                    order_id=order_id,
                    dedup_key=f"moysklad:{request_id}:{order_id}",
                    payload={
                        "request_id": request_id,
                        "audit_href": (str(audit.meta.href) if audit is not None else None),
                        "audit_moment": (audit.moment if audit is not None else None),
                        "updated_fields": item.updatedFields,
                    },
                )
            )
        if events:
            await self._repository.enqueue_events(tuple(events))
        return len(events)


router = APIRouter(prefix="/webhooks", tags=["Integration"])


@router.post("/order-chat/{secret}", status_code=204)
async def receive_order_chat_webhook(
    secret: str,
    payload: MoySkladWebhookPayload,
    request_id: str = Query(alias="requestId", min_length=1),
    receiver: OrderChatWebhookReceiver = Depends(get_order_chat_webhook_receiver),
):
    if not secrets.compare_digest(secret, receiver.secret):
        raise HTTPException(status_code=404, detail="Not found")
    await receiver.enqueue(request_id, payload)
    return Response(status_code=204)
