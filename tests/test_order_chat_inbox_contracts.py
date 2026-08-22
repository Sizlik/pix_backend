from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from config import OrderChatEmailSettings, Settings
from db.models.order_chat import OrderChatEmailOutbox, OrderChatState
from db.schemas.chat import (
    ConversationLastMessage,
    ConversationPage,
    ConversationSummary,
    ConversationUpdatedEvent,
    OperatorReadResponse,
)
from errors import IntegrationNotConfigured

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000002")


def conversation_summary(*, unread_count: int = 2) -> ConversationSummary:
    return ConversationSummary(
        order_id=ORDER_ID,
        order_name="12345",
        last_message=ConversationLastMessage(
            id=MESSAGE_ID,
            sender_kind="client",
            sender_label="Клиент",
            message="Проверка",
            created_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
            attachment_count=1,
        ),
        unread_count=unread_count,
    )


def test_order_chat_state_declares_inbox_projection_columns():
    columns = OrderChatState.__table__.c

    assert columns.order_name.type.length == 255
    assert columns.order_name.nullable is True
    assert columns.latest_message_id.nullable is True
    assert columns.latest_message_id.references(OrderChatEmailOutbox.__table__.c.message_id) is False
    assert {key.target_fullname for key in columns.latest_message_id.foreign_keys} == {
        "order_chat_message.id"
    }
    assert columns.operator_unread_count.nullable is False
    assert columns.operator_unread_count.server_default.arg == "0"
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in OrderChatState.__table__.constraints
        if constraint.name
    }
    assert checks["ck_order_chat_operator_unread_nonnegative"] == (
        "operator_unread_count >= 0"
    )


def test_email_outbox_declares_idempotency_and_safe_delivery_fields():
    assert OrderChatEmailOutbox.__tablename__ == "order_chat_email_outbox"
    columns = OrderChatEmailOutbox.__table__.c

    assert columns.message_id.unique is True
    assert columns.recipient_email.type.length == 320
    assert columns.last_error.type.length == 255
    assert columns.status.server_default.arg == "pending"
    assert columns.attempts.server_default.arg == "0"
    assert {key.target_fullname for key in columns.message_id.foreign_keys} == {
        "order_chat_message.id"
    }
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in OrderChatEmailOutbox.__table__.constraints
        if constraint.name
    }
    assert "recipient_kind IN ('client', 'manager')" in checks.values()
    assert "status IN ('pending', 'processing', 'sent', 'dead')" in checks.values()
    assert "attempts >= 0" in checks.values()
    assert "ix_order_chat_email_outbox_due" in {
        index.name for index in OrderChatEmailOutbox.__table__.indexes
    }


def test_inbox_schemas_serialize_the_public_contract():
    summary = conversation_summary()
    page = ConversationPage(
        items=[summary],
        next_before=MESSAGE_ID,
        total_unread=2,
    )
    event = ConversationUpdatedEvent(item=summary, total_unread=2)
    read = OperatorReadResponse(order_id=ORDER_ID, total_unread=0)

    assert page.model_dump(mode="json")["items"][0]["last_message"] == {
        "id": str(MESSAGE_ID),
        "sender_kind": "client",
        "sender_label": "Клиент",
        "message": "Проверка",
        "created_at": "2026-08-22T12:00:00Z",
        "attachment_count": 1,
    }
    assert event.type == "conversation_updated"
    assert read.unread_count == 0


@pytest.mark.parametrize(
    "factory",
    [
        lambda: conversation_summary(unread_count=-1),
        lambda: ConversationPage(items=[], next_before=None, total_unread=-1),
        lambda: OperatorReadResponse(
            order_id=ORDER_ID,
            unread_count=1,
            total_unread=0,
        ),
    ],
)
def test_inbox_schemas_reject_negative_or_nonzero_read_counts(factory):
    with pytest.raises(ValidationError):
        factory()


def test_order_chat_email_settings_are_opt_in_and_resolved_without_secrets_in_defaults():
    disabled = Settings(_env_file=None, app_env="test")

    assert disabled.enable_order_chat_email_notifications is False
    assert disabled.order_chat_manager_email is None
    assert disabled.pix_public_site_url is None
    with pytest.raises(IntegrationNotConfigured, match="order chat email notifications"):
        disabled.require_order_chat_email()

    enabled = Settings(
        _env_file=None,
        app_env="test",
        enable_order_chat_email_notifications=True,
        order_chat_manager_email="manager@example.com",
        pix_public_site_url="https://pixlogistic.com/",
        mailersend_token="smtp-token",
    )

    assert enabled.require_order_chat_email() == OrderChatEmailSettings(
        manager_email="manager@example.com",
        public_site_url="https://pixlogistic.com",
        smtp_bz_token="smtp-token",
    )
