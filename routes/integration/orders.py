from fastapi import APIRouter, Depends, BackgroundTasks

from db.models.users import User
from db.schemas.bitrix_contact import AddDealFields
from db.schemas.moysklad import ProductFolderCreate
from db.schemas.orders import OrderCreate, MoySkladIntegrationOrder, MoySkladIntegrationCustomerOrder
from manager.bitrix import BitrixManagerFull
from manager.moysklad import ProductFolderManager, ProductManager, CustomerOrderManager, InvoiceOutManager
from manager.orders import OrderManager, OrderItemsManager
from routes.users import current_user_dependency
from dependecies import (orders as dependency_orders, bitrix as dependency_bitrix, moysklad as dependency_moysklad)


router = APIRouter(prefix="/orders", tags=["Integration Orders"])


async def background_create_order(order_create_data, user: User, order_id: int, order_manager: OrderManager,
                                  order_items_manager: OrderItemsManager, bitrix_manager: BitrixManagerFull,
                                  moysklad_product_folder_manager: ProductFolderManager,
                                  moysklad_product_manager: ProductManager,
                                  moysklad_customer_order_manager: CustomerOrderManager):
    product_folder_data = ProductFolderCreate(
        name=f"Заказ: #{order_id} - {user.last_name} {user.first_name} - {user.email}",
        description=f"id на pixlogistic: {user.id}",
    )
    product_folder = await moysklad_product_folder_manager.create_product_folder(product_folder_data)

    moysklad_data = MoySkladIntegrationOrder(
        moysklad_product_folder_id=product_folder.get("id"),
        moysklad_product_folder_meta=product_folder.get("meta"),
    )

    await order_manager.moysklad_product_folder_insert(order_id, moysklad_data)

    bitrix_contact_id = bitrix_manager.get_or_create_contact_by_user(user)
    bitrix_deal_data = AddDealFields(
        TITLE=f"#{order_id}",
        OPPORTUNITY=0,
        CONTACT_ID=str(bitrix_contact_id),
        UF_CRM_1701183146524=order_id
    )
    bitrix_deal_id = bitrix_manager.deal_manager.add(bitrix_deal_data.model_dump()).get("result")
    order_items = await order_items_manager.create_orders(order_create_data, order_id=order_id)
    bitrix_manager.insert_products(order_create_data, bitrix_deal_id)
    products = await moysklad_product_manager.create_products_from_orders(order_items,
                                                                          product_folder_meta=product_folder.get(
                                                                              "meta"),
                                                                          order_id=order_id,
                                                                          user=user)

    order_items = await order_items_manager.moysklad_products_insert(products, order_items)

    customerorder = await moysklad_customer_order_manager.create_order(order_items, user)

    customerorder_data = MoySkladIntegrationCustomerOrder(
        moysklad_customer_order_id=customerorder.get("id"),
        moysklad_customer_order_meta=customerorder.get("meta"),
    )
    data = await order_manager.moysklad_product_folder_insert(order_id, customerorder_data)
    print(data)


@router.post("/")
async def create_order(
        order_create_data: OrderCreate,
        background_tasks: BackgroundTasks,
        user: User = Depends(current_user_dependency),
        order_manager: OrderManager = Depends(dependency_orders.get_order_manager),
        order_items_manager: OrderItemsManager = Depends(dependency_orders.get_order_items_manager),
        bitrix_manager: BitrixManagerFull = Depends(dependency_bitrix.get_bitrix_crm_full_manager),
        moysklad_product_folder_manager: ProductFolderManager = Depends(dependency_moysklad.get_product_folder_manager),
        moysklad_product_manager: ProductManager = Depends(dependency_moysklad.get_product_manager),
        moysklad_customer_order_manager: CustomerOrderManager = Depends(dependency_moysklad.get_customer_order_manager)
):
    order_id = await order_manager.create_order(user, is_bitrix_deal=True)
    background_tasks.add_task(background_create_order, order_create_data=order_create_data, user=user,
                              order_id=order_id, order_manager=order_manager, order_items_manager=order_items_manager,
                              bitrix_manager=bitrix_manager,
                              moysklad_product_folder_manager=moysklad_product_folder_manager,
                              moysklad_product_manager=moysklad_product_manager,
                              moysklad_customer_order_manager=moysklad_customer_order_manager)
    return {"detail": "in progress"}


@router.get("/invoice_out")
async def get_invoices(
        user: User = Depends(current_user_dependency),
        moysklad_invoice_out_manager: InvoiceOutManager = Depends(dependency_moysklad.get_invoice_out_manager),
):
    return await moysklad_invoice_out_manager.get_user_invoices(user)
