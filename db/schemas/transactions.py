from pydantic import BaseModel


class AcceptTransaction(BaseModel):
    bank: str
    sum_rub: float
    sum_dol: float
    card: str

