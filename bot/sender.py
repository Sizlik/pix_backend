from os import getenv

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db.models.users import User
from db.schemas.transactions import AcceptTransaction


class Sender:
    TOKEN = getenv("BOT_TOKEN")
    bot = Bot(TOKEN, parse_mode=ParseMode.HTML)

    @staticmethod
    async def keyboard():
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Принять", callback_data="accept"),
                                                      InlineKeyboardButton(text="Отклонить", callback_data="decline")]])

    async def accept_transaction_message(self, user: User, transaction: AcceptTransaction):
        await self.bot.send_message(592901349, f"Пользователь: {user.email} пополнил счёт!\nБанк: {transaction.bank}\nНа сумму: {transaction.sum_rub} ₽ \\ {transaction.sum_dol} $\nНа счёт: {transaction.card}\nID заказа: {transaction.order_id}", reply_markup=await self.keyboard())
        # await self.bot.send_message(592901349, f"Пользователь: {user.email} пополнил счёт!\nБанк: {transaction.bank}\nНа сумму: {transaction.sum_rub} ₽ \\ {transaction.sum_dol} $\nНа счёт: {transaction.card}\nID заказа: {transaction.order_id}", reply_markup=await self.keyboard())


telegram_sender = Sender()
