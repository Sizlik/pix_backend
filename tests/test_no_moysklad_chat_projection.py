from pathlib import Path

REMOVED = (
    "manager/chat_outbox.py",
    "manager/moysklad_order_chat.py",
    "manager/order_chat_format.py",
    "routes/integration/order_chat_webhook.py",
    "scripts/register_moysklad_order_chat_webhook.py",
)


def test_projection_runtime_files_are_removed():
    assert [path for path in REMOVED if Path(path).exists()] == []


def test_active_runtime_has_no_projection_tokens():
    sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "main.py",
            "dependecies/order_chat.py",
            "routes/bitrix.py",
            "manager/order_chat.py",
        )
    )
    for token in (
        "sync_order",
        "process_moysklad_update",
        "OrderChatOutboxWorker",
        "MoySkladOrderChatSynchronizer",
        "order_chat_delivery",
    ):
        assert token not in sources
