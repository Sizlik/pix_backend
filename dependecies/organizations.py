from manager.organizations import OrganizationManager, OrganizationRepository


async def get_organization_manager():
    yield OrganizationManager(OrganizationRepository())
