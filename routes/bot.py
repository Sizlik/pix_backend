from fastapi import APIRouter, Depends

from bot.sender import telegram_sender
from db.models.users import User
from db.schemas.transactions import AcceptTransaction
from routes.users import current_user_dependency

router = APIRouter(tags=["bot"], prefix="/bot")


@router.post("/accept_transaction")
async def accept_transaction(transaction: AcceptTransaction, user: User = Depends(current_user_dependency)):
    await telegram_sender.accept_transaction_message(user, transaction)
