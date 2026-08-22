from types import SimpleNamespace
from uuid import UUID

import pytest
import requests

try:
    import manager.order_chat_email as email_module
except ModuleNotFoundError:
    email_module = SimpleNamespace()


ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")


def content(**overrides):
    values = {
        "recipient_email": "recipient@example.com",
        "recipient_kind": "manager",
        "order_id": ORDER_ID,
        "order_name": "12345",
        "sender_label": "Клиент",
        "message": "Проверьте заказ",
        "attachment_count": 2,
    }
    values.update(overrides)
    assert hasattr(email_module, "OrderChatEmailContent")
    return email_module.OrderChatEmailContent(**values)


def test_manager_email_uses_manager_subject_and_exact_moysklad_link():
    envelope = email_module.render_order_chat_email(
        content(),
        "https://pixlogistic.com",
    )

    link = (
        "https://online.moysklad.ru/app/"
        f"#customerorder/edit?id={ORDER_ID}"
    )
    assert envelope.recipient_email == "recipient@example.com"
    assert envelope.subject == "Новое сообщение клиента по заказу №12345"
    assert link in envelope.html
    assert link in envelope.text
    assert "Клиент" in envelope.html
    assert "Вложений: 2" in envelope.text


def test_client_email_uses_client_subject_and_one_shot_website_link():
    envelope = email_module.render_order_chat_email(
        content(recipient_kind="client", sender_label="Менеджер Pix Logistic"),
        "https://pixlogistic.com/",
    )

    link = (
        f"https://pixlogistic.com/dashboard/orders/{ORDER_ID}"
        "?openChat=1#order-chat"
    )
    assert envelope.subject == "Новое сообщение по заказу №12345"
    assert link in envelope.html
    assert link in envelope.text


def test_html_escapes_message_order_and_sender_but_plain_text_keeps_readable_content():
    envelope = email_module.render_order_chat_email(
        content(
            order_name='12\r\nBcc: victim@example.com <b>"',
            sender_label="<Менеджер>",
            message='<script>alert("x")</script>\nВторая строка',
        ),
        "https://pixlogistic.com",
    )

    assert "\r" not in envelope.subject
    assert "\n" not in envelope.subject
    assert "<script>" not in envelope.html
    assert "&lt;script&gt;" in envelope.html
    assert "&lt;Менеджер&gt;" in envelope.html
    assert "<br>" in envelope.html
    assert '<script>alert("x")</script>' in envelope.text
    assert "Bcc: victim@example.com" in envelope.text


def test_preview_is_at_most_300_unicode_characters_and_marks_truncation():
    preview = email_module.safe_message_preview("я" * 301)

    assert len(preview) == 300
    assert preview == "я" * 299 + "…"


def test_empty_message_uses_attachment_fallback_without_attachment_names():
    envelope = email_module.render_order_chat_email(
        content(message=" \n ", attachment_count=1),
        "https://pixlogistic.com",
    )

    assert "Прикреплены файлы" in envelope.html
    assert "Прикреплены файлы" in envelope.text
    assert "invoice.pdf" not in envelope.html
    assert "invoice.pdf" not in envelope.text


class RequestRecorder:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_smtp_bz_sender_posts_bounded_form_request_without_logging_private_data(caplog):
    request = RequestRecorder(SimpleNamespace(status_code=202, text="private response"))
    sender = email_module.SmtpBzOrderChatEmailSender(
        "private-token",
        request=request,
    )
    envelope = email_module.EmailEnvelope(
        recipient_email="recipient@example.com",
        subject="Subject",
        html="<p>private body</p>",
        text="private body",
    )

    sender.send(envelope)

    assert len(request.calls) == 1
    args, kwargs = request.calls[0]
    assert args == ("https://api.smtp.bz/v1/smtp/send",)
    assert kwargs["headers"] == {"Authorization": "private-token"}
    assert kwargs["timeout"] == (3.05, 10)
    assert kwargs["data"] == {
        "name": "PixLogistic",
        "from": "info@pixlogistic.com",
        "subject": "Subject",
        "to": "recipient@example.com",
        "html": "<p>private body</p>",
        "text": "private body",
    }
    assert caplog.text == ""


@pytest.mark.parametrize(
    ("result", "category"),
    [
        (requests.Timeout("private timeout"), "timeout"),
        (requests.ConnectionError("private transport"), "transport"),
        (SimpleNamespace(status_code=503, text="private response"), "provider_5xx"),
        (SimpleNamespace(status_code=400, text="private response"), "provider_4xx"),
    ],
)
def test_smtp_bz_sender_exposes_only_safe_failure_category(
    result,
    category,
    caplog,
):
    sender = email_module.SmtpBzOrderChatEmailSender(
        "private-token",
        request=RequestRecorder(result),
    )
    envelope = email_module.EmailEnvelope(
        recipient_email="recipient@example.com",
        subject="Subject",
        html="<p>private body</p>",
        text="private body",
    )

    with pytest.raises(email_module.OrderChatEmailSendError) as caught:
        sender.send(envelope)

    assert caught.value.category == category
    assert str(caught.value) == category
    private_values = {
        "private-token",
        "recipient@example.com",
        "private body",
        "private response",
        "private timeout",
        "private transport",
    }
    assert all(value not in str(caught.value) for value in private_values)
    assert all(value not in caplog.text for value in private_values)
