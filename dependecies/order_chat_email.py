from config import OrderChatEmailSettings
from db.order_chat_email_repository import OrderChatEmailOutboxRepository
from manager.order_chat_email import SmtpBzOrderChatEmailSender
from manager.order_chat_email_dispatcher import OrderChatEmailDispatcher


def build_order_chat_email_dispatcher(
    settings: OrderChatEmailSettings,
) -> OrderChatEmailDispatcher:
    return OrderChatEmailDispatcher(
        repository=OrderChatEmailOutboxRepository(),
        sender=SmtpBzOrderChatEmailSender(settings.smtp_bz_token),
        public_site_url=settings.public_site_url,
    )
