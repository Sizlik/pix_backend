from os import getenv

from aiogram import Bot
from aiogram.enums import ParseMode

from db.models.users import User
from db.schemas.transactions import AcceptTransaction


class Sender:
    TOKEN = getenv("BOT_TOKEN")
    bot = Bot(TOKEN, parse_mode=ParseMode.HTML)

    async def accept_transaction_message(self, user: User, transaction: AcceptTransaction):
        await self.bot.send_message(592901349, f"Пользователь: {user.email} пополнил счёт!\nБанк: {transaction.bank}\nНа сумму: {transaction.sum_rub} ₽ \\ {transaction.sum_dol} $\nНа счёт: {transaction.card}")


telegram_sender = Sender()
