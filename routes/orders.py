import json
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, File, UploadFile, Form
from pydantic import BaseModel

from db.models.users import User
from db.schemas.orders import OrderCreate
from manager.orders import OrderManager, OrderItemsManager
from routes.users import current_user_dependency
from dependecies import (orders as dependency_orders, bitrix as dependency_bitrix)

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("")
async def get_user_orders(
        user: User = Depends(current_user_dependency),
        order_manager: OrderManager = Depends(dependency_orders.get_order_manager)
):
    return await order_manager.get_user_orders(user)


@router.get("/items/{order_id}")
async def get_user_orders(
        order_id: int,
        user: User = Depends(current_user_dependency),
        order_manager: OrderItemsManager = Depends(dependency_orders.get_order_items_manager)
):
    return await order_manager.get_order_items(order_id)


# @router.post("/file")
# async def get_file(file: UploadFile = File(), title: str = Form(...), count: int = Form(...)):
#     if not file:
#         return "File not found"
#     return file.filename, title, count

@router.post("/file")
async def get_file(file: Annotated[bytes, File()], first_line_header: bool = Form(...)):
    if not file:
        return "File not found"
    df = pd.read_excel(file)
    df_dict = json.loads(df.to_json(orient="values"))
    if first_line_header:
        header = df_dict[0]
        data = df_dict[1:]
    else:
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

