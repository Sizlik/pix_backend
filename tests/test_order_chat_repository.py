from datetime import datetime, timedelta, timezone
from uuid import UUID

from db.order_chat_repository import object_key, retry_at


def test_object_key_never_contains_client_filename():
    order_id = UUID("00000000-0000-0000-0000-000000000001")
    message_id = UUID("00000000-0000-0000-0000-000000000002")
    attachment_id = UUID("00000000-0000-0000-0000-000000000003")

    assert object_key(order_id, message_id, attachment_id) == (
        "orders/00000000-0000-0000-0000-000000000001/"
        "messages/00000000-0000-0000-0000-000000000002/"
        "attachments/00000000-0000-0000-0000-000000000003"
    )


def test_retry_backoff_is_exponential_and_capped_at_one_hour():
    now = datetime(2026, 8, 10, tzinfo=timezone.utc)

    assert retry_at(now, attempts=1, base_seconds=5, jitter_seconds=0) == now + timedelta(seconds=5)
    assert retry_at(now, attempts=4, base_seconds=5, jitter_seconds=0) == now + timedelta(seconds=40)
    assert retry_at(now, attempts=20, base_seconds=5, jitter_seconds=0) == now + timedelta(hours=1)
