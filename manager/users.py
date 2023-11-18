import uuid

from fastapi import Depends
from fastapi_users import BaseUserManager

from db.postgres import User, get_user_db


# class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID])

async def get_user_manager(user_db=Depends(get_user_db)):
    yield BaseUserManager(user_db)

