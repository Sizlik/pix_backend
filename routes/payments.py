from fastapi import APIRouter, Depends, Body

from db.models.users import User
from dependecies.moysklad import get_payment_in_manager
from manager.moysklad import PaymentInManager
from routes.users import current_user_dependency

router = APIRouter(tags=["Payment"], prefix="/payment")


@router.post("/")
async def create_payment(sum: int = Body(...), user: User = Depends(current_user_dependency), payment_manager: PaymentInManager = Depends(get_payment_in_manager)):
    return await payment_manager.create_payment_in(user, sum)
