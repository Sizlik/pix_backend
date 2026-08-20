from types import SimpleNamespace

import dependecies.order_chat as dependencies


class FakeSettings:
    def require_order_chat(self):
        return SimpleNamespace(
            endpoint="localhost:9000",
            access_key="access",
            secret_key="secret",
            bucket="order-chat",
            secure=False,
            webhook_secret="webhook-secret",
            attachment_max_count=10,
            attachment_max_bytes=20 * 1024 * 1024,
            outbox_max_attempts=8,
            outbox_base_delay_seconds=5,
        )


class FakeRepository:
    def order_lock(self, order_id):
        raise AssertionError("worker lock used during construction")


class FakeSynchronizer:
    async def sync_order(self, order_id):
        return None

    async def process_moysklad_update(self, event):
        return None


def test_runtime_registers_only_durable_order_chat_handlers(monkeypatch):
    repository = FakeRepository()
    monkeypatch.setattr(
        dependencies,
        "MinioObjectStorage",
        lambda **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        dependencies,
        "OrderChatRepository",
        lambda: repository,
    )
    monkeypatch.setattr(
        dependencies,
        "MoySkladOrderChatRepository",
        lambda settings: SimpleNamespace(),
    )
    monkeypatch.setattr(
        dependencies,
        "MoySkladOrderChatSynchronizer",
        lambda **kwargs: FakeSynchronizer(),
    )

    runtime = dependencies.get_order_chat_runtime(
        FakeSettings(),
        realtime=SimpleNamespace(),
    )

    assert runtime.worker.handler_names == frozenset(
        {"sync_order", "process_moysklad_update"}
    )
