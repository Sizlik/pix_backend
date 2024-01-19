from manager.privoz_order import PrivozRepository, PrivozManager


async def get_privoz_manager():
    yield PrivozManager(PrivozRepository())

