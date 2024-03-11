import uuid

from sqlalchemy import Column, ForeignKey, UUID, String, Integer, Boolean, JSON, Float, func, DateTime

from db.postgres import Base


class Order(Base):
    __tablename__ = "order"

    id = Column(Integer, primary_key=True, autoincrement=True)

    is_bitrix_deal = Column(Boolean)

    payedSum = Column(Float)
    shippedSum = Column(Float)
    sum = Column(Integer)

    moysklad_invoice_out_id = Column(UUID)
    moysklad_product_folder_id = Column(UUID)
    moysklad_product_folder_meta = Column(JSON)
    moysklad_customer_order_id = Column(UUID)
    moysklad_customer_order_meta = Column(JSON)
    moysklad_customer_order_state = Column(String, default="Новый")

    user_id = Column(ForeignKey("user.id"), nullable=False)


class OrderActions(Base):
    __tablename__ = "order_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    new_state = Column(String)
    order_id = Column(UUID)
    date = Column(DateTime(timezone=True), server_default=func.now())


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
