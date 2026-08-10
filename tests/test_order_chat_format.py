from datetime import datetime, timezone
from uuid import UUID

import pytest

from manager.order_chat_format import (
    CHAT_HEADER,
    HISTORY_FILENAME,
    REPLY_PROMPT,
    FileDisposition,
    MalformedOrderChatComment,
    TranscriptEntry,
    classify_moysklad_filename,
    client_copy_filename,
    extract_manager_reply,
    manager_public_filename,
    render_order_comment,
)


def entry(number: int, body: str) -> TranscriptEntry:
    return TranscriptEntry(
        sender_kind="client" if number % 2 else "manager",
        created_at=datetime(2026, 8, 10, 10, number, tzinfo=timezone.utc),
        body=body,
        filenames=(f"file-{number}.pdf",) if number == 1 else (),
    )


def test_comment_has_generic_signature_and_extracts_only_text_below_prompt():
    rendered = render_order_comment([entry(1, "Где заказ?"), entry(2, "Проверяем")])

    assert rendered.text.startswith(CHAT_HEADER)
    assert "Клиент:" in rendered.text
    assert "Менеджер Pix Logistic:" in rendered.text
    assert rendered.text.endswith(REPLY_PROMPT)
    assert extract_manager_reply(rendered.text + "\nОтправим сегодня") == ("Отправим сегодня")


def test_comment_never_exceeds_moysklad_limit_and_requests_history_file():
    rendered = render_order_comment([entry(number, "x" * 700) for number in range(1, 12)])

    assert len(rendered.text) <= 4096
    assert rendered.truncated is True
    assert rendered.history_filename == HISTORY_FILENAME
    assert "Показаны последние" in rendered.text
    assert "x" * 700 in rendered.full_history


def test_missing_prompt_is_not_interpreted_as_a_client_facing_reply():
    with pytest.raises(MalformedOrderChatComment):
        extract_manager_reply("менеджер случайно удалил служебный маркер")


def test_moysklad_file_prefixes_are_unambiguous():
    message_id = UUID("00000000-0000-0000-0000-000000000123")

    assert client_copy_filename(message_id, "../../счёт.pdf", 1) == (
        "[ЧАТ-КЛИЕНТ][00000000-0000-0000-0000-000000000123] счёт.pdf"
    )
    assert classify_moysklad_filename("[КЛИЕНТ] фото.jpg") is FileDisposition.MANAGER_PUBLIC
    assert manager_public_filename("[КЛИЕНТ] фото.jpg") == "фото.jpg"
    assert classify_moysklad_filename("[ЧАТ-КЛИЕНТ][m] фото.jpg") is FileDisposition.CLIENT_MIRROR
    assert classify_moysklad_filename("[PIX] История переписки.txt") is FileDisposition.SYSTEM
    assert classify_moysklad_filename("накладная.pdf") is FileDisposition.INTERNAL


def test_managed_filename_ordinal_is_added_before_extension():
    message_id = UUID("00000000-0000-0000-0000-000000000123")

    assert client_copy_filename(message_id, "scan.pdf", 2).endswith("scan (2).pdf")
