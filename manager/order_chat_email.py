from dataclasses import dataclass
from html import escape
from typing import Literal, Protocol
from uuid import UUID

import requests

MAX_PREVIEW_CHARACTERS = 300
SMTP_BZ_URL = "https://api.smtp.bz/v1/smtp/send"


@dataclass(frozen=True, slots=True)
class OrderChatEmailContent:
    recipient_email: str
    recipient_kind: Literal["client", "manager"]
    order_id: UUID
    order_name: str
    sender_label: str
    message: str
    attachment_count: int


@dataclass(frozen=True, slots=True)
class EmailEnvelope:
    recipient_email: str
    subject: str
    html: str
    text: str


class OrderChatEmailSender(Protocol):
    def send(self, envelope: EmailEnvelope) -> None: ...


class OrderChatEmailSendError(RuntimeError):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def safe_message_preview(message: str) -> str:
    normalized = message.strip()
    if not normalized:
        return "Прикреплены файлы"
    if len(normalized) <= MAX_PREVIEW_CHARACTERS:
        return normalized
    return normalized[: MAX_PREVIEW_CHARACTERS - 1] + "…"


def _single_line(value: str) -> str:
    return " ".join(value.splitlines()).strip()


def _message_link(content: OrderChatEmailContent, public_site_url: str) -> str:
    if content.recipient_kind == "manager":
        return (
            "https://online.moysklad.ru/app/"
            f"#customerorder/edit?id={content.order_id}"
        )
    return (
        f"{public_site_url.rstrip('/')}/dashboard/orders/{content.order_id}"
        "?openChat=1#order-chat"
    )


def render_order_chat_email(
    content: OrderChatEmailContent,
    public_site_url: str,
) -> EmailEnvelope:
    order_name = _single_line(content.order_name)
    sender_label = _single_line(content.sender_label)
    preview = safe_message_preview(content.message)
    link = _message_link(content, public_site_url)
    subject = (
        f"Новое сообщение клиента по заказу №{order_name}"
        if content.recipient_kind == "manager"
        else f"Новое сообщение по заказу №{order_name}"
    )

    escaped_order_name = escape(order_name, quote=True)
    escaped_sender_label = escape(sender_label, quote=True)
    escaped_preview = escape(preview, quote=True).replace("\n", "<br>")
    escaped_link = escape(link, quote=True)
    html = f"""<!doctype html>
<html lang="ru">
  <body>
    <h2>{escape(subject, quote=True)}</h2>
    <p><strong>Заказ №{escaped_order_name}</strong></p>
    <p>Отправитель: {escaped_sender_label}</p>
    <p>{escaped_preview}</p>
    <p>Вложений: {content.attachment_count}</p>
    <p><a href="{escaped_link}">Открыть заказ</a></p>
  </body>
</html>"""
    text = "\n".join(
        (
            subject,
            f"Заказ №{order_name}",
            f"Отправитель: {sender_label}",
            preview,
            f"Вложений: {content.attachment_count}",
            f"Открыть заказ: {link}",
        )
    )
    return EmailEnvelope(
        recipient_email=content.recipient_email,
        subject=subject,
        html=html,
        text=text,
    )


class SmtpBzOrderChatEmailSender:
    def __init__(self, token: str, *, request=requests.post):
        self._token = token
        self._request = request

    def send(self, envelope: EmailEnvelope) -> None:
        try:
            response = self._request(
                SMTP_BZ_URL,
                headers={"Authorization": self._token},
                data={
                    "name": "PixLogistic",
                    "from": "info@pixlogistic.com",
                    "subject": envelope.subject,
                    "to": envelope.recipient_email,
                    "html": envelope.html,
                    "text": envelope.text,
                },
                timeout=(3.05, 10),
            )
        except requests.Timeout:
            raise OrderChatEmailSendError("timeout") from None
        except requests.RequestException:
            raise OrderChatEmailSendError("transport") from None

        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and 200 <= status_code < 300:
            return
        if isinstance(status_code, int) and status_code >= 500:
            raise OrderChatEmailSendError("provider_5xx")
        if isinstance(status_code, int) and status_code >= 400:
            raise OrderChatEmailSendError("provider_4xx")
        raise OrderChatEmailSendError("invalid_response")
