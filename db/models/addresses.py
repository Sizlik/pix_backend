import uuid

from sqlalchemy import (
    UUID,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)

from db.postgres import Base


class Address(Base):
    __tablename__ = "address"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "normalized_name",
            name="uq_address_user_normalized_name",
        ),
        Index("ix_address_user_last_used", "user_id", "last_used_at"),
    )

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False)
    normalized_name = Column(String(100), nullable=False)
    city = Column(String(100), nullable=False)
    street = Column(String(200), nullable=False)
    house = Column(String(30), nullable=False)
    postal_code = Column(String(6))
    building = Column(String(30))
    apartment = Column(String(30))
    delivery_comment = Column(String(500))
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
