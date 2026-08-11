from dataclasses import dataclass
from uuid import UUID, uuid5

ORDER_CREATE_NAMESPACE = UUID("fa8f8d8b-d6ec-4ca2-8c08-b5ba76f1c676")


@dataclass(frozen=True)
class OrderCreateIdentity:
    order_sync_id: UUID
    product_sync_ids: tuple[UUID, ...]


def build_order_create_identity(
    user_id: UUID,
    idempotency_key: UUID,
    item_count: int,
) -> OrderCreateIdentity:
    attempt_namespace = uuid5(
        ORDER_CREATE_NAMESPACE,
        f"{user_id}:{idempotency_key}",
    )
    return OrderCreateIdentity(
        order_sync_id=uuid5(attempt_namespace, "customer-order"),
        product_sync_ids=tuple(
            uuid5(attempt_namespace, f"product:{index}")
            for index in range(item_count)
        ),
    )
