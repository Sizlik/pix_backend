import logging
import random
import uuid
from typing import Optional

import requests
from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin, models
from starlette.requests import Request

from bot.sender import telegram_sender
from config import Settings, get_settings, require_secret
from db import postgres
from db.models.users import User, UserDatabase, get_user_db
from db.redis import redis
from db.schemas import moysklad as schemas_moysklad
from db.schemas.users import UserUpdate
from dependecies import moysklad

logger = logging.getLogger(__name__)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    user_db: UserDatabase

    def __init__(
        self,
        user_db: UserDatabase,
        settings: Settings | None = None,
    ):
        super().__init__(user_db)
        settings = settings or get_settings()
        self.verification_token_secret = settings.verification_token_secret.get_secret_value()
        self.reset_password_token_secret = settings.reset_password_token_secret.get_secret_value()

    async def verify(self, token: str, request: Optional[Request] = None) -> models.UP:
        data = await request.json()
        email = data.get("email")
        redis_key = f"verify:{email}:{token}"
        token = await redis.get(redis_key)
        return await super().verify(token, request)

    async def on_after_request_verify(self, user: models.UP, token: str, request: Optional[Request] = None) -> None:
        verification_code = generate_code()
        redis_key = f"verify:{user.email}:{verification_code}"
        await redis.set(redis_key, token, ex=300)  # TTL 5 минут
        send_verification_code(user.email, verification_code)

    async def ensure_moysklad_counterparty(
        self,
        user: User,
        request: Optional[Request] = None,
    ):
        if user.moysklad_counterparty_id:
            return user, None

        counterparty_manager = await moysklad.get_counterparty_manager()
        counterparty_data = schemas_moysklad.CounterpartyCreate(
            name=f"{user.first_name} Клиент #{user.name_id}",
            description=f"Информация с сайта pixlogistics:\nid = {user.id}",
            email=user.email,
            phone=user.phone_number,
        )
        resolution = await counterparty_manager.resolve_user_counterparty(
            counterparty_data
        )
        counterparty = resolution.counterparty
        user_update_data = UserUpdate(
            moysklad_counterparty_id=counterparty["id"],
            moysklad_counterparty_meta=counterparty["meta"],
        )
        updated_user = await self.update(
            user_update_data,
            user,
            request=request,
        )
        return updated_user, resolution

    async def on_after_verify(self, user: User, request: Optional[Request] = None) -> None:
        try:
            user, resolution = await self.ensure_moysklad_counterparty(
                user,
                request,
            )
        except Exception:
            logger.exception("Failed to link verified user to MoySklad")
            return

        try:
            if resolution is None:
                await telegram_sender.send_group_message(
                    f'<a href="{user.moysklad_counterparty_meta.get("uuidHref")}">Пользователь подтвердил почту!</a>\n{user.first_name} Клиент #{user.name_id}'
                )
                return

            counterparty = resolution.counterparty
            notification_title = (
                "Новый пользователь на сайте!"
                if resolution.created
                else "Пользователь связан с существующим контрагентом!"
            )
            await telegram_sender.send_group_message(
                f'<a href="{counterparty["meta"]["uuidHref"]}">'
                f"{notification_title}</a>\n"
                f"{user.first_name} Клиент #{user.name_id}"
            )
        except Exception:
            logger.exception(
                "Failed to send MoySklad user verification notification"
            )

    async def on_after_register(self, user: models.UP, request: Optional[Request] = None) -> None:
        await self.request_verify(user, request)

    async def on_after_forgot_password(self, user: models.UP, token: str, request: Optional[Request] = None) -> None:
        verification_code = generate_code()
        redis_key = f"reset:{user.email}:{verification_code}"
        await redis.set(redis_key, token, ex=300)  # TTL 5 минут
        send_verification_code(user.email, verification_code)

    async def reset_password(self, token: str, password: str, request: Optional[Request] = None) -> models.UP:
        data = await request.json()
        email = data.get("email")
        redis_key = f"reset:{email}:{token}"
        token = await redis.get(redis_key)
        return await super().reset_password(token, password)


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db, get_settings())


async def authenticate_websocket_user(token, strategy):
    async with postgres.async_session_maker() as session:
        user_db = UserDatabase(session, User)
        user_manager = UserManager(user_db, get_settings())
        return await strategy.read_token(token, user_manager)


def generate_code(length=6) -> str:
    return "".join(random.choices("0123456789", k=length))


def send_verification_code(
    email: str,
    code: str,
    settings: Settings | None = None,
):
    url = "https://api.smtp.bz/v1/smtp/send"
    headers = {
        "Authorization": require_secret(
            (settings or get_settings()).mailersend_token,
            "email",
        )
    }

    data = {
        "name": "PixLogistic",
        "from": "info@pixlogistic.com",
        "subject": "PixLogistic Код подтверждения",
        "to": email,
        "html": f"""<html>
                <head></head>
                <body>
                    <h2>Ваш код подтверждения</h2>
                    <p>Пожалуйста, используйте следующий код для завершения регистрации:</p>
                    <div style="font-size: 24px; font-weight: bold;">{code}</div>
                    <p>Код действителен в течение 5 минут. Если вы не запрашивали код, просто проигнорируйте это письмо.</p>
                    <div style="margin-top: 20px; color: #999;">© 2025 PixLogistic. Все права защищены.</div>
                </body>
            </html>""",
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
