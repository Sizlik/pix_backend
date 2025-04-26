import json

import requests
from fastapi import APIRouter, Depends, Body

from db.models.users import User
from db.redis import redis
from db.schemas.payments import CreatePayment
from dependecies.moysklad import get_payment_in_manager, get_customer_order_manager
from manager.moysklad import PaymentInManager, CustomerOrderManager
from manager.users import get_user_manager, UserManager
from routes.users import current_user_dependency

router = APIRouter(tags=["Payment"], prefix="/payment")


@router.post("/")
async def create_payment(
        payment_data: CreatePayment,
        user_manager: UserManager = Depends(get_user_manager),
        order_manager: CustomerOrderManager = Depends(get_customer_order_manager),
        user: User = Depends(current_user_dependency),
        payment_manager: PaymentInManager = Depends(get_payment_in_manager)
):
    client_user = await user_manager.get_by_email(payment_data.email)
    payment = await payment_manager.create_payment_in(client_user, payment_data.sum * 100)
    order = await order_manager.get_order_by_id(payment_data.order_id)
    return await payment_manager.link_payment_in(payment.get("id"), order.get("meta"))


@router.get("/vault_courses")
async def get_vault_courses():
    vault_curses = await redis.get("vault_courses")
    if vault_curses is None:
        vault_curses = requests.get("https://api.frankfurter.dev/v1/latest?from=PLN&to=USD,EUR").json()
        await redis.set("vault_courses", json.dumps(vault_curses), ex=60*60)
    else:
        vault_curses = json.loads(vault_curses)
    return vault_curses


@router.get("/")
async def get_user_payments(
        payment_manager: PaymentInManager = Depends(get_payment_in_manager),
        user: User = Depends(current_user_dependency),
):
    return await payment_manager.get_all_user_payment_ins(user)


