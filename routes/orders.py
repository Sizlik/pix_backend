import json
import uuid
from typing import Annotated

import pandas as pd
import requests
from fastapi import APIRouter, Depends, File, UploadFile, Form, Body
from pydantic import BaseModel

from bot.sender import telegram_sender
from db.models.users import User
from db.schemas.moysklad import ProductFolderCreate
from db.schemas.orders import OrderCreate
from manager.orders import OrderManager, OrderItemsManager
from manager.moysklad import CustomerOrderManager, ProductManager, ProductFolderManager
from manager.privoz_order import PrivozManager
from routes.users import current_user_dependency
from dependecies import (orders as dependency_orders, bitrix as dependency_bitrix, moysklad as dependency_moysklad, privoz_orders as dependency_privoz)

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("")
async def create_order(
    order: OrderCreate,
    user: User = Depends(current_user_dependency),
    customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager),
    product_manager: ProductManager = Depends(dependency_moysklad.get_product_manager),
):
    products = await product_manager.create_products(order, user)

    order_items = []
    for product, order_item in zip(products, order.order_items):
        order_items.append({
            "count": order_item.count,
            "moysklad_product_meta": product.get("meta")
        })

    customer_orders = await customer_order_manager.create_order_by_request(order_items, user)
    await telegram_sender.send_group_message(f'<a href="{customer_orders.get("meta").get("uuidHref")}">Новый заказ</a>\nПользователь: {user.first_name} Клиент #{user.name_id}')
    return customer_orders


@router.put("/state/{order_id}")
async def change_order_state(order_id, user: User = Depends(current_user_dependency), customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager),):
    order = await customer_order_manager.change_state(order_id, "Подтвержден клиентом")
    await telegram_sender.send_group_message(
        f'<a href="{order.get("meta").get("uuidHref")}">Заказ подтверждён</a>\nПользователь: {user.first_name} Клиент #{user.name_id}')
    return order


@router.get("")
async def get_user_orders(
    user: User = Depends(current_user_dependency),
    customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager),
    privoz_manager: PrivozManager = Depends(dependency_privoz.get_privoz_manager)
):
    customer_orders = await customer_order_manager.get_orders_by_user(user)

    orders = []
    for order in customer_orders.get("rows"):
        if order.get("shipmentAddressFull", {}).get("comment") and order.get("shipmentAddressFull", {}).get("comment").startswith("#"):
            privoz_order = await privoz_manager.get_order_by_id(order.get("shipmentAddressFull").get("comment"))
            order.update({"state": {"name": privoz_order.state}})
        orders.append(order)

    return orders


@router.get("/test")
async def test(
    customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager),
    privoz_manager: PrivozManager = Depends(dependency_privoz.get_privoz_manager)
):
    return await privoz_manager.parse_privoz()


@router.get("/{order_id}")
async def get_user_order(
    order_id: uuid.UUID,
    user: User = Depends(current_user_dependency),
    customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager),
    privoz_manager: PrivozManager = Depends(dependency_privoz.get_privoz_manager),
):
    customer_order = await customer_order_manager.get_order_by_id(order_id)
    if customer_order.get("shipmentAddressFull", {}).get("comment") and customer_order.get("shipmentAddressFull", {}).get(
            "comment").startswith("#"):
        privoz_order = await privoz_manager.get_order_by_id(customer_order.get("shipmentAddressFull").get("comment"))
        customer_order.update({"state": {"name": privoz_order.state}})
    return customer_order


@router.delete("/{order_id}/positions/{position_id}")
async def delete_order_position(
        order_id: str, position_id: str,
        user: User = Depends(current_user_dependency),
        customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager)
):
    return await customer_order_manager.delete_order_position_by_id(order_id, position_id)


@router.put("/{order_id}/positions/{position_id}")
async def update_order_position(
        order_id: str, position_id: str, count: int = Body(...),
        user: User = Depends(current_user_dependency),
        customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager)
):
    return await customer_order_manager.update_order_position(order_id, position_id, count)


@router.put("/{order_id}/positions")
async def update_order_position(
        order_id: str,
        order: OrderCreate,
        user: User = Depends(current_user_dependency),
        customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager),
        product_manager: ProductManager = Depends(dependency_moysklad.get_product_manager),
):
    products = await product_manager.create_products(order, user)
    order_items = []
    for product, order_item in zip(products, order.order_items):
        order_items.append({
            "count": order_item.count,
            "moysklad_product_meta": product.get("meta")
        })

    customer_order = await customer_order_manager.add_order_position(order_id, order_items)
    await telegram_sender.send_group_message(f'<a href="https://online.moysklad.ru/app/#customerorder/edit?id={order_id}">В заказ добавлена позиция</a>\nПользователь: {user.first_name} Клиент #{user.name_id}')
    return customer_order


@router.delete("/{order_id}")
async def cancel_order(
        order_id: str,
        user: User = Depends(current_user_dependency),
        customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager)
):
    order = await customer_order_manager.change_state(order_id, "Отменен")
    await telegram_sender.send_group_message(f'<a href="{order.get("meta").get("uuidHref")}">Заказ отменён</a>\nПользователь: {user.first_name} Клиент #{user.name_id}')
    return order


# @router.get("")
# async def get_user_orders(
#         user: User = Depends(current_user_dependency),
#         order_manager: OrderManager = Depends(dependency_orders.get_order_manager)
# ):
#     return await order_manager.get_user_orders(user)
#
#
# @router.get("/items/{order_id}")
# async def get_user_orders(
#         order_id: int,
#         user: User = Depends(current_user_dependency),
#         order_manager: OrderItemsManager = Depends(dependency_orders.get_order_items_manager)
# ):
#     return await order_manager.get_order_items(order_id)


@router.post("/file")
async def get_file(file: Annotated[bytes, File()]):
    if not file:
        return "File not found"
    df = pd.read_excel(file)

    df_dict = json.loads(df.to_json(orient="values"))

    header = None
    data = df_dict
    response_data = []
    for i in data:
        count = 0
        for k in i:
            if k:
                count += 1
                if count == 2:
                    response_data.append(i)
                    break

    return {"header": header, "data": response_data}

