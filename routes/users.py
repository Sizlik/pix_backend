import uuid

from fastapi import APIRouter, Depends, Query
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import BearerTransport, AuthenticationBackend

from bot.sender import telegram_sender
from dependecies import moysklad
from db.models.users import User
from db.redis import get_redis_strategy
from db.schemas.users import UserRead, UserCreate, UserUpdate
from manager.moysklad import CounterpartyReportManager, OperationManager
from manager.users import get_user_manager, UserManager

bearer_transport = BearerTransport(tokenUrl="api_v1/users/auth/jwt/login")

auth_backend = AuthenticationBackend(name="jwt", transport=bearer_transport, get_strategy=get_redis_strategy)

router = APIRouter(prefix="/users")

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_user_dependency = fastapi_users.current_user()

router.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"])
router.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"])


@router.get("/updatedMe", tags=["users"])
async def get_me(
        user: User = Depends(current_user_dependency),
        operation_manager: OperationManager = Depends(moysklad.get_operation_manager),
        user_manager: UserManager = Depends(get_user_manager),
):
    operations = await operation_manager.get_operations(user)
    user_balance = sum([x.get("sum") if x.get("meta", {}).get("type") == "paymentin" else -x.get("sum") for x in operations.get("rows")])
    if user_balance is not None and user.balance != user_balance:
        user_update_data = UserUpdate(balance=user_balance)
        await user_manager.update(user_update_data, user)

    return user


@router.get("/operations", tags=["users"])
async def get_operations(user: User = Depends(current_user_dependency),
        operation_manager: OperationManager = Depends(moysklad.get_operation_manager)):
    return await operation_manager.get_operations(user)


@router.put("/telegram/{telegram_id}", tags=["users"])
async def set_telegram_id(
        telegram_id: int,
        user: User = Depends(current_user_dependency),
        user_manager: UserManager = Depends(get_user_manager),
):
    user_update_data = UserUpdate(telegram_id=telegram_id)
    await user_manager.update(user_update_data, user)
    await telegram_sender.send_user_message(telegram_id, f"Вы успешно связали аккаунт {user.email}")

# @router.post("/resetPassword", tags=["users"])
# async def reset_password(email: Query(), user_manager: UserManager = Depends(get_user_manager)):

