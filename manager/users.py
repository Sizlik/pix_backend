import base64
import os
import random
import uuid
from typing import Optional

import requests
from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin, models
from starlette.requests import Request

from bot.sender import telegram_sender
from db.models.users import get_user_db, User, UserDatabase
from db.redis import redis
from db.schemas.users import UserUpdate
from db.schemas import moysklad as schemas_moysklad
from dependecies import moysklad


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    user_db: UserDatabase
    verification_token_secret = os.getenv("VERIFICATION_TOKEN_SECRET")
    reset_password_token_secret = os.getenv("RESET_PASSWORD_TOKEN_SECRET")

    async def verify(self, token: str, request: Optional[Request] = None) -> models.UP:
        data = await request.json()
        email = data.get("email")
        redis_key = f"verify:{email}:{token}"
        token = await redis.get(redis_key)
        return await super().verify(token, request)

    async def on_after_request_verify(
        self, user: models.UP, token: str, request: Optional[Request] = None
    ) -> None:
        verification_code = generate_code()
        redis_key = f"verify:{user.email}:{verification_code}"
        await redis.set(redis_key, token, ex=300)  # TTL 5 минут
        send_verification_code(user.email, verification_code)

    async def on_after_verify(
        self, user: User, request: Optional[Request] = None
    ) -> None:
        if user.moysklad_counterparty_id:
            await telegram_sender.send_group_message(f'<a href="{user.moysklad_counterparty_meta.get("uuidHref")}">Пользователь подтвердил почту!</a>\n{user.first_name} Клиент #{user.name_id}')
            return

        counterparty_manager = await moysklad.get_counterparty_manager()
        counterparty_data = schemas_moysklad.CounterpartyCreate(
            name=f"{user.first_name} Клиент #{user.name_id}",
            description=f"Информация с сайта pixlogistics:\nid = {user.id}",
            email="",
            phone=""
        )
        moysklad_counterparty = await counterparty_manager.create_user_counterparty(counterparty_data)
        user_update_data = UserUpdate(
            moysklad_counterparty_id=moysklad_counterparty.get("id"),
            moysklad_counterparty_meta=moysklad_counterparty.get("meta")
        )
        await telegram_sender.send_group_message(
            f'<a href="{moysklad_counterparty.get("meta").get("uuidHref")}">Новый пользователь на сайте!</a>\n{user.first_name} Клиент #{user.name_id}')
        await self.update(user_update_data, user, request=request)


    async def on_after_register(
        self, user: models.UP, request: Optional[Request] = None
    ) -> None:
        await self.request_verify(user, request)

    async def on_after_forgot_password(
        self, user: models.UP, token: str, request: Optional[Request] = None
    ) -> None:
        verification_code = generate_code()
        redis_key = f"reset:{user.email}:{verification_code}"
        await redis.set(redis_key, token, ex=300)  # TTL 5 минут
        send_verification_code(user.email, verification_code)

    async def reset_password(
        self, token: str, password: str, request: Optional[Request] = None
    ) -> models.UP:
        data = await request.json()
        email = data.get("email")
        redis_key = f"reset:{email}:{token}"
        token = await redis.get(redis_key)
        return await super().reset_password(token, password)


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


def generate_code(length=6) -> str:
    return ''.join(random.choices("0123456789", k=length))


def send_verification_code(email: str, code: str):
    url = 'https://api.smtp.bz/v1/smtp/send'
    headers = {
        'Authorization': os.getenv('MAILERSEND_TOKEN')
    }

    data = {
        'name': 'PixLogistic',
        'from': 'info@pixlogistic.com',
        'subject': 'PixLogistic Код подтверждения',
        'to': email,
        'html': f'''<html>
                <head></head>
                <body>
                    <h2>Ваш код подтверждения</h2>
                    <p>Пожалуйста, используйте следующий код для завершения регистрации:</p>
                    <div style="font-size: 24px; font-weight: bold;">{code}</div>
                    <p>Код действителен в течение 5 минут. Если вы не запрашивали код, просто проигнорируйте это письмо.</p>
                    <div style="margin-top: 20px; color: #999;">© 2025 PixLogistic. Все права защищены.</div>
                </body>
            </html>'''
    }
    response = requests.post(url, headers=headers, data=data)
    print(response.text)
    # mailer = emails.NewEmail(os.getenv("MAILERSEND_TOKEN"))
    #
    # # define an empty dict to populate with mail values
    # mail_body = {}
    #
    # mail_from = {
    #     "name": "PixLogistic",
    #     "email": "info@pixlogistic.com",
    # }
    #
    # recipients = [
    #     {
    #         "name": "Recipient",
    #         "email": email,
    #     }
    # ]
    # personalization = [
    #     {
    #         "email": email,
    #         "data": {
    #             "code": code
    #         }
    #     }
    # ]
    # mailer.set_mail_from(mail_from, mail_body)
    # mailer.set_mail_to(recipients, mail_body)
    # mailer.set_subject("PixLogistic Код подтверждения", mail_body)
    # mailer.set_template("jy7zpl99m15l5vx6", mail_body)
    # mailer.set_personalization(personalization, mail_body)
    #
    # mailer.send(mail_body)
