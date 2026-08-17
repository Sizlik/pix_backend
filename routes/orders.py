import json
import uuid
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Response

from db.models.users import User
from db.schemas.orders import (
    CheckoutOrderCreate,
    OrderChangesRequest,
    OrderChangesResponse,
    OrderCreate,
)
from dependecies import (
    moysklad as dependency_moysklad,
)
from dependecies import (
    orders as dependency_orders,
)
from dependecies import (
    privoz_orders as dependency_privoz,
)
from errors import (
    IdempotencyKeyReused,
    InvalidOrderChanges,
    OrderCreationIdempotencyUnavailable,
    OrderCreationInProgress,
    OrderNotAccessible,
    OrderNotEditable,
    OrderVersionConflict,
)
from manager.moysklad import (
    CustomerOrderManager,
    InvoiceOutManager,
    PurchaseOrderManager,
)
from manager.order_changes import OrderChangesManager
from manager.order_creation import OrderCreationManager
from manager.orders import OrderActionsManager
from manager.privoz_order import PrivozManager
from manager.telegram_notifications import BestEffortGroupNotifier
from routes.users import current_user_dependency

router = APIRouter(prefix="/orders", tags=["Orders"])


def pdf_attachment(content: bytes, filename: str) -> Response:
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def order_creation_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, IdempotencyKeyReused):
        return HTTPException(
            409,
            detail={
                "code": "idempotency_key_reused",
                "message": "Idempotency key was already used for another order",
            },
        )
    if isinstance(exc, OrderCreationInProgress):
        return HTTPException(
            409,
            detail={
                "code": "order_creation_in_progress",
                "message": "Order creation is still in progress",
            },
        )
    return HTTPException(
        503,
        detail={
            "code": "order_idempotency_unavailable",
            "message": "Order creation is temporarily unavailable",
        },
    )


def order_change_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OrderNotAccessible):
        return HTTPException(
            404,
            detail={"code": "order_not_found", "message": "Order not found"},
        )
    if isinstance(exc, OrderNotEditable):
        return HTTPException(
            409,
            detail={"code": "order_not_editable", "message": "Order is not editable"},
        )
    if isinstance(exc, OrderVersionConflict):
        return HTTPException(
            409,
            detail={"code": "order_version_conflict", "message": "Order was updated"},
        )
    return HTTPException(
        422,
        detail={"code": "invalid_order_changes", "message": str(exc)},
    )


@router.post("")
async def create_order(
    order: CheckoutOrderCreate,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
    user: User = Depends(current_user_dependency),
    manager: OrderCreationManager = Depends(
        dependency_orders.get_order_creation_manager
    ),
):
    try:
        return await manager.create(order, user, idempotency_key)
    except (
        IdempotencyKeyReused,
        OrderCreationInProgress,
        OrderCreationIdempotencyUnavailable,
    ) as exc:
        raise order_creation_http_error(exc) from None


@router.get("/export/{id}")
async def export_pdf(
    id: str,
    _user: User = Depends(current_user_dependency),
    customer_order_manager: CustomerOrderManager = Depends(
        dependency_moysklad.get_customer_order_manager
    ),
):
    try:
        content = await customer_order_manager.export_template(id, _user)
    except OrderNotAccessible as exc:
        raise order_change_http_error(exc) from None
    return pdf_attachment(content, f"customer-order-{id}.pdf")


@router.get("/purchaseorder/export/{id}")
async def export_pdf_purchaseorder(
    id: str,
    _user: User = Depends(current_user_dependency),
    purchase_order_manager: PurchaseOrderManager = Depends(
        dependency_moysklad.get_purchase_order_manager
    ),
):
    try:
        content = await purchase_order_manager.export_template(id, _user)
    except OrderNotAccessible as exc:
        raise order_change_http_error(exc) from None
    return pdf_attachment(content, f"purchase-order-{id}.pdf")


@router.get("/invoiceout/export/{id}")
async def export_pdf_invoice_out(
    id: str,
    _user: User = Depends(current_user_dependency),
    invoice_out_manager: InvoiceOutManager = Depends(
        dependency_moysklad.get_invoice_out_manager
    ),
):
    try:
        content = await invoice_out_manager.export_template(id, _user)
    except OrderNotAccessible as exc:
        raise order_change_http_error(exc) from None
    return pdf_attachment(content, f"invoice-out-{id}.pdf")


@router.put("/state/{order_id}")
async def change_order_state(
    order_id,
    user: User = Depends(current_user_dependency),
    customer_order_manager: CustomerOrderManager = Depends(
        dependency_moysklad.get_customer_order_manager
    ),
    notifier: BestEffortGroupNotifier = Depends(
        dependency_orders.get_order_notifier
    ),
):
    order = await customer_order_manager.change_state(order_id, "Подтвержден клиентом")
    await notifier.send_group_message(
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
            if privoz_order:
                order.update({"state": {"name": privoz_order.state}})
        orders.append(order)

    return orders


@router.get("/test")
async def test(
    customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager),
    privoz_manager: PrivozManager = Depends(dependency_privoz.get_privoz_manager)
):
    return await privoz_manager.parse_privoz()


@router.get("/actions/{order_id}")
async def get_user_order_actions(
    order_id: uuid.UUID,
    user: User = Depends(current_user_dependency),
    order_actions_manager: OrderActionsManager = Depends(dependency_orders.get_order_actions_manager),
):
    return await order_actions_manager.get_order_actions(order_id)


@router.put("/{order_id}/changes", response_model=OrderChangesResponse)
async def save_order_changes(
    order_id: uuid.UUID,
    request: OrderChangesRequest,
    user: User = Depends(current_user_dependency),
    manager: OrderChangesManager = Depends(
        dependency_orders.get_order_changes_manager
    ),
):
    try:
        return await manager.save_changes(user, order_id, request)
    except (
        OrderNotAccessible,
        OrderNotEditable,
        OrderVersionConflict,
        InvalidOrderChanges,
    ) as exc:
        raise order_change_http_error(exc) from None


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
    order_id: uuid.UUID,
    position_id: uuid.UUID,
    user: User = Depends(current_user_dependency),
    manager: OrderChangesManager = Depends(
        dependency_orders.get_order_changes_manager
    ),
):
    try:
        return (await manager.remove_position(user, order_id, position_id)).order
    except (
        OrderNotAccessible,
        OrderNotEditable,
        OrderVersionConflict,
        InvalidOrderChanges,
    ) as exc:
        raise order_change_http_error(exc) from None


@router.put("/{order_id}/positions/{position_id}")
async def update_order_position_count(
    order_id: uuid.UUID,
    position_id: uuid.UUID,
    count: int = Body(..., gt=0),
    user: User = Depends(current_user_dependency),
    manager: OrderChangesManager = Depends(
        dependency_orders.get_order_changes_manager
    ),
):
    try:
        return (
            await manager.change_quantity(user, order_id, position_id, count)
        ).order
    except (
        OrderNotAccessible,
        OrderNotEditable,
        OrderVersionConflict,
        InvalidOrderChanges,
    ) as exc:
        raise order_change_http_error(exc) from None


@router.put("/{order_id}/positions")
async def add_order_positions(
    order_id: uuid.UUID,
    order: OrderCreate,
    user: User = Depends(current_user_dependency),
    manager: OrderChangesManager = Depends(
        dependency_orders.get_order_changes_manager
    ),
):
    try:
        return (await manager.add_positions(user, order_id, order)).order
    except (
        OrderNotAccessible,
        OrderNotEditable,
        OrderVersionConflict,
        InvalidOrderChanges,
    ) as exc:
        raise order_change_http_error(exc) from None


@router.delete("/{order_id}")
async def cancel_order(
        order_id: str,
        user: User = Depends(current_user_dependency),
        customer_order_manager: CustomerOrderManager = Depends(
            dependency_moysklad.get_customer_order_manager
        ),
        notifier: BestEffortGroupNotifier = Depends(
            dependency_orders.get_order_notifier
        ),
):
    order = await customer_order_manager.change_state(order_id, "Отменен")
    await notifier.send_group_message(f'<a href="{order.get("meta").get("uuidHref")}">Заказ отменён</a>\nПользователь: {user.first_name} Клиент #{user.name_id}')
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

