import uuid

from sqlalchemy import (
    JSON,
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from db.postgres import Base


class OrderChatMessage(Base):
    __tablename__ = "order_chat_message"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID, nullable=False, index=True)
    client_id = Column(ForeignKey("user.id"), nullable=False, index=True)
    sender_kind = Column(String(16), nullable=False)
    source = Column(String(16), nullable=False)
    body = Column(Text, nullable=False, default="")
    external_key = Column(String(255), nullable=True, unique=True)
    legacy_message_id = Column(UUID, nullable=True, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "sender_kind IN ('client', 'manager')",
            name="ck_order_chat_sender_kind",
        ),
        CheckConstraint(
            "source IN ('site', 'moysklad', 'legacy')",
            name="ck_order_chat_source",
        ),
        Index(
            "ix_order_chat_message_order_created",
            "order_id",
            "created_at",
            "id",
        ),
    )


class OrderChatAttachment(Base):
    __tablename__ = "order_chat_attachment"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    message_id = Column(ForeignKey("order_chat_message.id"), nullable=False, index=True)
    object_key = Column(String(512), nullable=False, unique=True)
    original_filename = Column(String(255), nullable=False)
    mime_type = Column(String(255), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    origin = Column(String(16), nullable=False)
    origin_external_file_id = Column(UUID, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_order_chat_attachment_size"),
        CheckConstraint(
            "origin IN ('site', 'moysklad')",
            name="ck_order_chat_attachment_origin",
        ),
    )


class OrderChatState(Base):
    __tablename__ = "order_chat_state"

    order_id = Column(UUID, primary_key=True)
    client_id = Column(ForeignKey("user.id"), nullable=False, index=True)
    initialized = Column(Boolean, nullable=False, default=False, server_default="false")
    rendered_description_hash = Column(String(64), nullable=True)
    prior_comment_file_id = Column(UUID, nullable=True)
    history_file_id = Column(UUID, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class MoySkladOrderFile(Base):
    __tablename__ = "moysklad_order_file"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID, nullable=False, index=True)
    moysklad_file_id = Column(UUID, nullable=False)
    filename = Column(String(255), nullable=False)
    disposition = Column(String(32), nullable=False)
    message_id = Column(ForeignKey("order_chat_message.id"), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("order_id", "moysklad_file_id", name="uq_moysklad_order_file"),
        CheckConstraint(
            "disposition IN ('baseline', 'client_mirror', 'manager_public', 'internal', 'system')",
            name="ck_moysklad_order_file_disposition",
        ),
    )


class ChatOutboxEvent(Base):
    __tablename__ = "chat_outbox_event"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    event_type = Column(String(64), nullable=False)
    order_id = Column(UUID, nullable=False, index=True)
    dedup_key = Column(String(255), nullable=False, unique=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'dead')",
            name="ck_chat_outbox_status",
        ),
        Index("ix_chat_outbox_due", "status", "available_at"),
    )
