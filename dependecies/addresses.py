from db.address_repository import AddressRepository
from manager.addresses import AddressManager


async def get_address_manager():
    yield AddressManager(AddressRepository())
