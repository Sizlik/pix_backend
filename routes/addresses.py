from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from db.models.users import User
from db.schemas.addresses import (
    AddressCreate,
    AddressListResponse,
    AddressRead,
    AddressUpdate,
)
from dependecies.addresses import get_address_manager
from manager.addresses import AddressManager
from routes.users import current_user_dependency

router = APIRouter(prefix="/addresses", tags=["Addresses"])


@router.get("", response_model=AddressListResponse)
async def list_addresses(
    search: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user_dependency),
    manager: AddressManager = Depends(get_address_manager),
):
    return await manager.list(user.id, search, limit, offset)


@router.post("", response_model=AddressRead, status_code=201)
async def create_address(
    request: AddressCreate,
    user: User = Depends(current_user_dependency),
    manager: AddressManager = Depends(get_address_manager),
):
    return await manager.create(user.id, request)


@router.patch("/{address_id}", response_model=AddressRead)
async def update_address(
    address_id: UUID,
    request: AddressUpdate,
    user: User = Depends(current_user_dependency),
    manager: AddressManager = Depends(get_address_manager),
):
    return await manager.update(user.id, address_id, request)


@router.delete("/{address_id}", status_code=204)
async def delete_address(
    address_id: UUID,
    user: User = Depends(current_user_dependency),
    manager: AddressManager = Depends(get_address_manager),
):
    await manager.delete(user.id, address_id)
    return Response(status_code=204)
