import uuid

from sqlalchemy import Column, ForeignKey, UUID, String, Integer, Boolean, JSON, Float

from db.postgres import Base


class Order(Base):
    __tablename__ = "order"

    id = Column(Integer, primary_key=True, autoincrement=True)

    is_bitrix_deal = Column(Boolean)

    payedSum = Column(Float)
    shippedSum = Column(Float)
    state = Column(String)
    sum = Column(Integer)

    moysklad_invoice_out_id = Column(UUID)
    moysklad_product_folder_id = Column(UUID)
    moysklad_product_folder_meta = Column(JSON)
    moysklad_customer_order_id = Column(UUID)
    moysklad_customer_order_meta = Column(JSON)

    user_id = Column(ForeignKey("user.id"), nullable=False)


class OrderItems(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    comment = Column(String)
    count = Column(Integer, nullable=False)
    link = Column(String, nullable=False)
    price = Column(Float)
    quantity = Column(Float)

    moysklad_invoice_item_id = Column(UUID)
    moysklad_product_id = Column(UUID)
    moysklad_product_meta = Column(JSON)

    order_id = Column(ForeignKey("order.id"), nullable=False)
