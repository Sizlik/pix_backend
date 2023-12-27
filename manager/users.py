import base64
import uuid
from typing import Optional

import requests
from fastapi import Depends
from fastapi_users import BaseUserManager, UUIDIDMixin, models
from starlette.requests import Request

from db.models.users import get_user_db, User
from db.schemas.users import UserUpdate
from db.schemas import moysklad as schemas_moysklad
from dependecies import moysklad


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    async def on_after_register(
        self, user: models.UP, request: Optional[Request] = None
    ) -> None:
        counterparty_manager = await moysklad.get_counterparty_manager()

        counterparty_data = schemas_moysklad.CounterpartyCreate(
            name=f"Клиент - {user.first_name} {user.last_name} - {user.email}",
            description=f"Информация с сайта pixlogistics:\nid = {user.id}",
            email=user.email,
            phone=user.phone_number
        )
        moysklad_counterparty = await counterparty_manager.create_user_counterparty(counterparty_data)
        user_update_data = UserUpdate(
            moysklad_counterparty_id=moysklad_counterparty.get("id"),
            moysklad_counterparty_meta=moysklad_counterparty.get("meta")
        )
        await self.update(user_update_data, user, request=request)


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)

