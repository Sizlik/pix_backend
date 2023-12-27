import uuid

from sqlalchemy import Column, UUID, ForeignKey, TIMESTAMP, String, Float

from db.postgres import Base


class Transaction(Base):
    __tablename__ = "transaction"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    date = Column(TIMESTAMP, nullable=False)
    action = Column(String, nullable=False)
    edit_balance = Column(Float, nullable=False)

    user_id = Column(ForeignKey("user.id"), nullable=False)

