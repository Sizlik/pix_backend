from pydantic import BaseModel


class CounterpartyCreate(BaseModel):
    name: str
    description: str
    email: str
    phone: str


class ProductFolderCreate(BaseModel):
    name: str
    description: str


class ProductCreate(BaseModel):
    name: str
    description: str
    productFolder: dict

