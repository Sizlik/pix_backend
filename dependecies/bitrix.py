from manager.bitrix import BitrixManager, BitrixCrmProduct, BitrixCrmDeal, BitrixCrmContact, BitrixManagerFull


async def get_bitrix_crm_deal_manager():
    yield BitrixManager(BitrixCrmDeal())


async def get_bitrix_crm_product_manager():
    yield BitrixManager(BitrixCrmProduct())


async def get_bitrix_crm_contact_manager():
    yield BitrixManager(BitrixCrmContact())


async def get_bitrix_crm_full_manager():
    yield BitrixManagerFull()
