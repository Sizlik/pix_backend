import uuid

from sqlalchemy import Column, String

from db.postgres import Base


class PrivozOrder(Base):
    __tablename__ = "privoz_order"

    privoz_order = Column(String, unique=True, primary_key=True)
    state = Column(String)
