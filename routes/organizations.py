from fastapi import APIRouter, Depends

from db.models.users import User, get_user_db, UserDatabase
from db.schemas.users import UserUpdate, UserCreate
from dependecies.moysklad import get_customer_order_manager
from dependecies.organizations import get_organization_manager
from dependecies.privoz_orders import get_privoz_manager
from manager.moysklad import CustomerOrderManager
from manager.organizations import OrganizationManager
from manager.privoz_order import PrivozManager
from manager.users import UserManager, get_user_manager
from routes.users import current_user_dependency

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("/")
async def create_organization(user: User = Depends(current_user_dependency),
                              organization_manager: OrganizationManager = Depends(get_organization_manager),
                              user_manager: UserManager = Depends(get_user_manager)):
    organization_id = await organization_manager.create_organization(user)
    user_update_data = UserUpdate(organization_id=organization_id)
    await user_manager.update(user_update_data, user)
    return organization_id


@router.get("/")
async def get_user_organization(user: User = Depends(current_user_dependency),
                                organization_manager: OrganizationManager = Depends(get_organization_manager)):
    return await organization_manager.get_organization_by_owner(user)


@router.post("/users/")
async def create_organization_user(user_create: UserCreate, user: User = Depends(current_user_dependency),
                                   user_manager: UserManager = Depends(get_user_manager)):
    user_create.is_organization_user = True
    user_create.organization_id = user.organization_id
    return await user_manager.create(user_create)


@router.get("/users/")
async def get_organization_users(user: User = Depends(current_user_dependency), user_db: UserDatabase = Depends(get_user_db)):
    return await user_db.get_users_by_organization(user.organization_id)


@router.get("/orders/")
async def get_organization_orders(user: User = Depends(current_user_dependency),
                                  order_manager: CustomerOrderManager = Depends(get_customer_order_manager),
                                  privoz_manager: PrivozManager = Depends(get_privoz_manager),
                                  user_db: UserDatabase = Depends(get_user_db)):
    users = await user_db.get_users_by_organization(user.organization_id)
    items = []

    for user in users:
        customer_orders = await order_manager.get_orders_by_user(user)
        orders = []

        for order in customer_orders.get("rows"):
            if order.get("shipmentAddressFull", {}).get("comment") and order.get("shipmentAddressFull", {}).get(
                    "comment").startswith("#"):
                privoz_order = await privoz_manager.get_order_by_id(order.get("shipmentAddressFull").get("comment"))
                if privoz_order:
                    order.update({"state": {"name": privoz_order.state}})
            orders.append(order)

        items.append({"user": user, "orders": orders})

    return items

