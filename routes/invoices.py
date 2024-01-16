from fastapi import APIRouter

router = APIRouter(tags=["invoices"], prefix="/invoice")


@router.get("/")
async def get_user_invoices():
    pass


@router.post("/")
async def create_user_invoice():
    pass
