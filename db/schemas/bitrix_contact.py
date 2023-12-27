from typing import List, Optional

from pydantic import BaseModel


class EMAIL(BaseModel):
    VALUE: str


class PHONE(BaseModel):
    VALUE: str


class AddContactFields(BaseModel):
    EMAIL: List[EMAIL]
    LAST_NAME: str
    NAME: str
    PHONE: List[PHONE]


class AddDealFields(BaseModel):
    TITLE: str
    OPPORTUNITY: Optional[float]
    CONTACT_ID: str
    UF_CRM_1701183146524: float


class AddProductFields(BaseModel):
    NAME: str
    DESCRIPTION: str
