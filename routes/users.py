import uuid

from fastapi import APIRouter
from fastapi_users import FastAPIUsers, BaseUserManager
from fastapi_users.authentication import BearerTransport, AuthenticationBackend

from db.postgres import User
from db.redis import get_redis_strategy
from db.schemas.users import UserRead, UserCreate, UserUpdate
from manager.users import get_user_manager

bearer_transport = BearerTransport(tokenUrl="users/auth/jwt/login")

auth_backend = AuthenticationBackend(name="jwt", transport=bearer_transport, get_strategy=get_redis_strategy)

router = APIRouter(prefix="/users")

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

router.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"])
router.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"])

