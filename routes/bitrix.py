from fastapi import APIRouter

from db.schemas.bitrix_contact import AddContactFields, AddDealFields, AddProductFields
from manager.bitrix import BitrixCrmContact, BitrixCrmDeal, BitrixCrmProduct, BitrixManager
from routes.integration.order_chat_webhook import router as router_order_chat_webhook
from routes.integration.orders import router as router_orders
from routes.integration.vaults import router as router_vaults
from routes.integration.webhooks import router as router_webhooks

router = APIRouter(prefix="/integration", tags=["Integration"])
router.include_router(router_orders)
router.include_router(router_webhooks)
router.include_router(router_vaults)
router.include_router(router_order_chat_webhook)


@router.get("/bitrix/contacts/{contact_id}")
async def get_bitrix_contact(contact_id: str):
    return BitrixManager(BitrixCrmContact()).get(contact_id)


@router.post("/bitrix/contacts/")
async def create_bitrix_contact(fields: AddContactFields):
    return BitrixManager(BitrixCrmContact()).add(fields.model_dump())


@router.get("/bitrix/deal/{deal_id}")
async def get_bitrix_deal(deal_id: str):
    return BitrixManager(BitrixCrmDeal()).get(deal_id)


@router.post("/bitrix/deal/")
async def create_bitrix_deal(fields: AddDealFields):
    return BitrixManager(BitrixCrmDeal()).add(fields.model_dump())


@router.get("/bitrix/product/{product_id}")
async def get_bitrix_product(product_id: str):
    return BitrixManager(BitrixCrmProduct()).get(product_id)


@router.post("/bitrix/product/")
async def create_bitrix_product(fields: AddProductFields):
    return BitrixManager(BitrixCrmProduct()).add(fields.model_dump())
