from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import get_settings, require_secret, require_value
from db.models.users import User
from db.schemas.transactions import AcceptTransaction
from manager.moysklad import CustomerOrderManager, CustomerOrderRepository

customer_order_manager = CustomerOrderManager(CustomerOrderRepository())


class Sender:
    def __init__(self, settings_provider=get_settings):
        self._settings_provider = settings_provider
        self._bot_client = None

    def _bot(self) -> Bot:
        if self._bot_client is None:
            token = require_secret(self._settings_provider().bot_token, "telegram")
            self._bot_client = Bot(token, parse_mode=ParseMode.HTML)
        return self._bot_client

    @property
    def chat_id(self) -> str:
        value = self._settings_provider().chat_id
        return require_value(str(value) if value is not None else None, "telegram")

    @property
    def help_chat_id(self) -> str:
        value = self._settings_provider().help_chat_id
        return require_value(str(value) if value is not None else None, "telegram")

    @staticmethod
    async def keyboard():
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Принять", callback_data="accept"),
                    InlineKeyboardButton(text="Отклонить", callback_data="decline"),
                ]
            ]
        )

    @staticmethod
    async def chat_keyboard():
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="показать прошлые сообщения", callback_data="last_messages")]]
        )

    async def accept_transaction_message(self, user: User, transaction: AcceptTransaction):
        await self._bot().send_message(
            self.chat_id,
            f"Пользователь: {user.email} пополнил счёт!\nБанк: {transaction.bank}\nНа сумму: {transaction.sum_rub} ₽ \\ {transaction.sum_dol} $\nНа счёт: {transaction.card}\nID заказа: {transaction.order_id}",
            reply_markup=await self.keyboard(),
        )

    async def send_group_message(self, text):
        await self._bot().send_message(self.chat_id, text, parse_mode=ParseMode.HTML)

    async def send_user_message(self, user_id, text, disable_web_page_preview=False):
        await self._bot().send_message(
            user_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=disable_web_page_preview
        )

    async def send_chat_message(self, text, user: User, chat_id):
        if str(chat_id) != str(user.id):
            order = await customer_order_manager.get_order_by_id(chat_id)
            order.get("name")
            message = f'{chat_id}\nid: {user.id}\nПользователь: {user.first_name}\nЗаказ: <a href="https://online.moysklad.ru/app/#customerorder/edit?id={chat_id}">#{order.get("name")}</a>\nКлиент #{user.name_id}\nНаписал в поддержку:\n\n{text}'
        else:
            message = (
                f"{chat_id}\nПользователь: {user.first_name} Клиент #{user.name_id}\nНаписал в поддержку:\n\n{text}"
            )
        await self._bot().send_message(self.help_chat_id, message, reply_markup=await self.chat_keyboard())


telegram_sender = Sender()
