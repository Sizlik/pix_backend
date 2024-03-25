from db.models.organizations import Organization
from db.models.users import User
from db.repository import SQLAlchemyRepository


class OrganizationRepository(SQLAlchemyRepository):
    model = Organization


class OrganizationManager:

    def __init__(self, repo: SQLAlchemyRepository):
        self.__repo = repo

    async def create_organization(self, user: User):
        return await self.__repo.create(owner=user.id)

    async def get_organization_by_owner(self, user):
        return await self.__repo.search_one(Organization.owner == user.id)



