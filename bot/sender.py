from os import getenv

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db.models.users import User
from db.schemas.transactions import AcceptTransaction
from manager.moysklad import CustomerOrderManager, CustomerOrderRepository

customer_order_manager = CustomerOrderManager(CustomerOrderRepository())


class Sender:
    TOKEN = getenv("BOT_TOKEN")
    chat_id = getenv("CHAT_ID")
    help_chat_id = getenv("HELP_CHAT_ID")
    bot = Bot(TOKEN, parse_mode=ParseMode.HTML)

    @staticmethod
    async def keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Принять", callback_data="accept"),
                                                      InlineKeyboardButton(text="Отклонить", callback_data="decline")]])

    @staticmethod
    async def chat_keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="показать прошлые сообщения", callback_data="last_messages")]])

    async def accept_transaction_message(self, user: User, transaction: AcceptTransaction):
        await self.bot.send_message(592901349, f"Пользователь: {user.email} пополнил счёт!\nБанк: {transaction.bank}\nНа сумму: {transaction.sum_rub} ₽ \\ {transaction.sum_dol} $\nНа счёт: {transaction.card}\nID заказа: {transaction.order_id}", reply_markup=await self.keyboard())
        # await self.bot.send_message(592901349, f"Пользователь: {user.email} пополнил счёт!\nБанк: {transaction.bank}\nНа сумму: {transaction.sum_rub} ₽ \\ {transaction.sum_dol} $\nНа счёт: {transaction.card}\nID заказа: {transaction.order_id}", reply_markup=await self.keyboard())

    async def send_group_message(self, text):
        await self.bot.send_message(self.chat_id, text, parse_mode=ParseMode.HTML)

    async def send_user_message(self, user_id, text):
        await self.bot.send_message(user_id, text, parse_mode=ParseMode.HTML)

    async def send_chat_message(self, text, user: User, chat_id):
        if str(chat_id) != str(user.id):
            order = await customer_order_manager.get_order_by_id(chat_id)
            order.get("name")
            message = f'{chat_id}\nПользователь: {user.first_name}\nЗаказ: <a href="https://online.moysklad.ru/app/#customerorder/edit?id={chat_id}">#{order.get("name")}</a>\nКлиент #{user.name_id}\nНаписал в поддержку:\n\n{text}'
        else:
            message = f"{chat_id}\nПользователь: {user.first_name} Клиент #{user.name_id}\nНаписал в поддержку:\n\n{text}"
        await self.bot.send_message(self.help_chat_id, message, reply_markup=await self.chat_keyboard())


telegram_sender = Sender()
