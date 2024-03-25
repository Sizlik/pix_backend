import uuid

from sqlalchemy import Column, ForeignKey, UUID

from db.postgres import Base


class Organization(Base):
    __tablename__ = "organization"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    owner = Column(ForeignKey("user.id"))

