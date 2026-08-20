# Telegram Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Remove Telegram and the Telegram-backed general support chat from the active backend, frontend, runtime configuration, and deployment topology while preserving email verification, MoySklad order workflows, website notifications, and the order-specific chat.

**Architecture:** FastAPI use cases stop accepting Telegram notifier dependencies. The retained order chat continues through PostgreSQL, MinIO, MoySklad, Redis, and authenticated room-scoped WebSockets. A reviewed Alembic migration eagerly imports eligible legacy order messages, rewrites their notification links, removes support-chat data and Telegram outbox events, and then drops only the obsolete schema.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Redis, pytest, Next.js 14, TypeScript, Vitest, Playwright, Docker Compose.

**Approved design:** docs/superpowers/specs/2026-08-20-remove-telegram-design.md

## Global Constraints

- Preserve GET and POST /api_v1/chat/orders/{order_id}/messages, GET /api_v1/chat/attachments/{attachment_id}, and the authenticated room-scoped /api_v1/chat/ws endpoint.
- Preserve website notification types ORDER_MESSAGE and ORDER_UPDATED.
- Do not introduce another messaging provider or a replacement general-support channel.
- Do not edit or delete historical Alembic revisions or archived specifications and plans.
- Do not run alembic upgrade, alembic downgrade, a data repair, or a production database command automatically.
- Do not make ordinary imports, tests, setup, or local startup contact Telegram, production MoySklad, production PostgreSQL, or another production service.
- Keep ENABLE_SCHEDULER=false for local checks.
- Preserve all pre-existing user changes in both repositories; stage only files named in the current task.
- Commit backend and frontend changes separately.
- Treat production backup, migration, bot-container removal, protected-environment edits, and obsolete-account deletion as separately authorized deployment work.
- Never print credentials, message bodies, attachment contents, webhook secrets, chat IDs, or protected environment values.

## Rolling Compatibility

- Deploying the Telegram-free backend before the schema migration is supported because the legacy tables and user.telegram_id may remain unused for a short window.
- Deploying the Telegram-free frontend before or after the backend is supported because an old backend may return the extra notification_sent field and the new frontend ignores it; an old frontend already treats an absent notification_sent value as no warning.
- The destructive migration is last. After it runs, restoring deleted support history or Telegram identity values requires the validated pre-migration backup.

---

### Task 1: Make verification and public routing Telegram-free

**Files:**
- Modify: manager/users.py
- Modify: routes/users.py
- Modify: main.py
- Delete: routes/bot.py
- Modify: tests/test_moysklad_user_linking.py
- Modify: tests/test_app.py

**Interfaces:**
- Preserves: FastAPI Users registration, verification, password reset, and GET /api_v1/users/updatedMe.
- Preserves: best-effort MoySklad counterparty linking after verification.
- Removes: PUT /api_v1/users/telegram/{telegram_id} and every /api_v1/bot/* route.
- Produces: UserManager.on_after_verify that returns after local verification and MoySklad linking, without constructing or awaiting a notification sender.

- [ ] **Step 1: Replace Telegram-oriented verification assertions with a notifier-free contract**

In tests/test_moysklad_user_linking.py, replace the test that expects update followed by Telegram with:

~~~python
@pytest.mark.asyncio
@pytest.mark.parametrize("created", [False, True])
async def test_after_verify_persists_resolution_without_notification(
    monkeypatch,
    created,
):
    external = counterparty(1, "89991234567")
    resolution_manager = StubResolutionManager(
        CounterpartyResolution(external, created=created)
    )
    manager = user_manager()
    user = verified_user()
    events = []

    async def get_counterparty_manager():
        return resolution_manager

    async def update(data, current_user, request=None):
        events.append(("update", data, current_user, request))
        return current_user

    monkeypatch.setattr(
        users_module.moysklad,
        "get_counterparty_manager",
        get_counterparty_manager,
    )
    monkeypatch.setattr(manager, "update", update)

    await manager.on_after_verify(user)

    assert [event[0] for event in events] == ["update"]
    assert str(events[0][1].moysklad_counterparty_id) == external["id"]
    assert events[0][1].moysklad_counterparty_meta == external["meta"]
    assert resolution_manager.payloads[0].phone == user.phone_number
~~~

Delete test_after_verify_logs_telegram_failure_after_persisting. Rewrite test_after_verify_keeps_existing_link_without_lookup_or_update so it only proves no lookup and no update; remove its sender stub and message assertions. Keep the existing linking-failure test, because MoySklad linking remains best effort.

Add a source-level assertion that prevents the original coupling from returning:

~~~python
def test_user_manager_has_no_notification_sender_dependency():
    source = Path("manager/users.py").read_text(encoding="utf-8")

    assert "bot.sender" not in source
    assert "telegram_sender" not in source
    assert "send_group_message" not in source
~~~

Add from pathlib import Path to the test imports.

- [ ] **Step 2: Add failing route-absence tests**

Append to tests/test_app.py:

~~~python
def test_telegram_and_bot_routes_are_not_mounted():
    from main import create_app

    app = create_app(Settings(_env_file=None, app_env="test"))
    paths = {route.path for route in app.routes}

    assert "/api_v1/users/telegram/{telegram_id}" not in paths
    assert not any(path.startswith("/api_v1/bot") for path in paths)
~~~

- [ ] **Step 3: Run the focused tests and verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_moysklad_user_linking.py tests/test_app.py -q
~~~

Expected: the source guard and route-absence test fail because the sender import and legacy routes still exist.

- [ ] **Step 4: Remove the verification side notification**

In manager/users.py, remove the bot.sender import and replace on_after_verify with:

~~~python
async def on_after_verify(
    self,
    user: User,
    request: Optional[Request] = None,
) -> None:
    try:
        await self.ensure_moysklad_counterparty(user, request)
    except Exception:
        logger.exception("Failed to link verified user to MoySklad")
~~~

Do not change verification code generation, Redis TTLs, email sending, or counterparty recovery.

- [ ] **Step 5: Remove the public Telegram and bot routes**

In routes/users.py, remove the bot.sender import and the set_telegram_id endpoint. Delete routes/bot.py. In main.py, remove the routes.bot import and router inclusion. Do not leave a compatibility stub: removed routes must return FastAPI 404.

- [ ] **Step 6: Run focused verification**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_moysklad_user_linking.py tests/test_app.py -q
.\.venv\Scripts\python.exe -c "import main; assert main.app is not None"
~~~

Expected: tests pass and importing main does not load bot.sender or call an external service.

- [ ] **Step 7: Commit the account and route boundary**

~~~powershell
git add manager/users.py routes/users.py routes/bot.py main.py tests/test_moysklad_user_linking.py tests/test_app.py
git commit -m "refactor: remove Telegram from user verification"
~~~

### Task 2: Remove notifier dependencies from order mutations

**Files:**
- Modify: manager/order_creation.py
- Modify: manager/order_changes.py
- Modify: dependecies/orders.py
- Modify: routes/orders.py
- Modify: db/schemas/orders.py
- Delete: manager/telegram_notifications.py
- Delete: tests/test_telegram_notifications.py
- Modify: tests/test_order_creation.py
- Modify: tests/test_order_creation_api.py
- Modify: tests/test_order_changes.py
- Modify: tests/test_order_changes_api.py

**Interfaces:**
- OrderCreationManager constructor becomes (addresses, products, customer_orders, idempotency, logger=None).
- OrderChangesManager constructor becomes (customer_orders, products).
- OrderChangesResponse becomes {order: dict, changed: bool}.
- PUT /api_v1/orders/state/{order_id} and DELETE /api_v1/orders/{order_id} depend only on the customer-order manager and authenticated user.

- [ ] **Step 1: Rewrite order creation tests around business side effects only**

Remove StubNotifier and notifier arguments from tests/test_order_creation.py. The happy-path assertion becomes:

~~~python
result = await OrderCreationManager(
    addresses,
    products,
    orders,
    StubIdempotency(),
).create(make_request(), make_user(), IDEMPOTENCY_KEY)

assert result["id"] == "moysklad-order"
assert events == [
    "address:get",
    "products:create",
    "order:create",
    "address:mark",
]
~~~

Keep tests proving idempotent cache hits do not create another order and address-mark failures do not fail an already-created order. Remove only notification assertions.

In tests/test_order_creation_api.py, replace test_completed_state_changes_ignore_unavailable_telegram with:

~~~python
@pytest.mark.parametrize(
    ("method", "path", "expected_state"),
    [
        ("put", "/api_v1/orders/state/order-id", "Подтвержден клиентом"),
        ("delete", "/api_v1/orders/order-id", "Отменен"),
    ],
)
def test_completed_state_changes_return_moysklad_result(
    method,
    path,
    expected_state,
):
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
        first_name="Иван",
        name_id=7,
    )
    app.dependency_overrides[
        dependency_moysklad.get_customer_order_manager
    ] = StubCustomerOrderManager

    with TestClient(app) as client:
        response = client.request(method, path)

    assert response.status_code == 200
    assert response.json()["state"]["name"] == expected_state
~~~

- [ ] **Step 2: Rewrite order-change tests for the two-field response**

Remove StubNotifier, notification formatting assertions, and the two Telegram failure tests from tests/test_order_changes.py. Instantiate OrderChangesManager(orders, products). Assert:

~~~python
result = await OrderChangesManager(orders, products).save_changes(
    make_user(),
    orders.order["id"],
    request,
)

assert result.changed is True
assert result.model_dump() == {
    "order": orders.replacements[0][2],
    "changed": True,
}
~~~

For a no-op, assert:

~~~python
assert result.model_dump() == {
    "order": orders.order,
    "changed": False,
}
assert orders.replacements == []
assert products.orders == []
~~~

Update tests/test_order_changes_api.py so the exact successful JSON contract is:

~~~python
assert set(response.json()) == {"order", "changed"}
assert response.json()["changed"] is True
~~~

- [ ] **Step 3: Run focused tests and verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation.py tests/test_order_creation_api.py tests/test_order_changes.py tests/test_order_changes_api.py -q
~~~

Expected: constructor signatures and the response schema still require notifier-related values.

- [ ] **Step 4: Simplify the order managers**

In manager/order_creation.py:

- remove html, build_new_order_message, self._notifier, and the notification try/except;
- keep the logger because address mark failures remain logged;
- leave the idempotency and MoySklad call order unchanged.

The constructor must be:

~~~python
def __init__(
    self,
    addresses,
    products,
    customer_orders,
    idempotency,
    logger=None,
):
    self._addresses = addresses
    self._products = products
    self._customer_orders = customer_orders
    self._idempotency = idempotency
    self._logger = logger or logging.getLogger(__name__)
~~~

In manager/order_changes.py, remove logging, html.escape, GroupNotifier, format_order_change_message, self._notifier, and notification_sent. The changed and no-op returns become:

~~~python
return OrderChangesResponse(order=order, changed=False)
~~~

and:

~~~python
return OrderChangesResponse(order=updated_order, changed=True)
~~~

- [ ] **Step 5: Simplify dependency wiring and state routes**

In dependecies/orders.py, remove the sender, settings, BestEffortGroupNotifier, and get_order_notifier. Construct:

~~~python
async def get_order_changes_manager():
    yield OrderChangesManager(
        CustomerOrderManager(CustomerOrderRepository()),
        ProductManager(ProductRepository()),
    )


async def get_order_creation_manager():
    yield OrderCreationManager(
        AddressManager(AddressRepository()),
        ProductManager(ProductRepository()),
        CustomerOrderManager(CustomerOrderRepository()),
        RedisOrderCreationIdempotency(redis),
    )
~~~

In routes/orders.py, remove BestEffortGroupNotifier and notifier dependencies. Each state route performs one MoySklad state change and directly returns the result:

~~~python
order = await customer_order_manager.change_state(
    order_id,
    "Подтвержден клиентом",
)
return order
~~~

Use "Отменен" in the cancellation route.

Delete manager/telegram_notifications.py and tests/test_telegram_notifications.py.

- [ ] **Step 6: Remove notification_sent from the backend schema**

In db/schemas/orders.py:

~~~python
class OrderChangesResponse(BaseModel):
    order: dict
    changed: bool
~~~

- [ ] **Step 7: Run focused and import checks**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_creation.py tests/test_order_creation_api.py tests/test_order_changes.py tests/test_order_changes_api.py -q
.\.venv\Scripts\python.exe -c "from dependecies.orders import get_order_creation_manager, get_order_changes_manager"
~~~

Expected: order tests pass and manager/dependency imports require no Telegram module or setting.

- [ ] **Step 8: Commit the notifier-free order contract**

~~~powershell
git add manager/order_creation.py manager/order_changes.py dependecies/orders.py routes/orders.py db/schemas/orders.py manager/telegram_notifications.py tests/test_telegram_notifications.py tests/test_order_creation.py tests/test_order_creation_api.py tests/test_order_changes.py tests/test_order_changes_api.py
git commit -m "refactor: remove Telegram order notifications"
~~~

### Task 3: Preserve website status notifications without Telegram sends

**Files:**
- Modify: utils/celery_worker.py
- Modify: routes/integration/webhooks.py
- Create: tests/test_status_notification_paths.py

**Interfaces:**
- Preserves: ORDER_UPDATED website notification creation.
- Removes: direct user Telegram messages from scheduled state synchronization and POST /api_v1/webhooks/order_wait.
- Requires: a missing user is handled without dereferencing user.id.

- [ ] **Step 1: Add focused status-notification tests**

Create tests/test_status_notification_paths.py with isolated fakes for the webhook and a static guard for the scheduler:

~~~python
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from db.schemas.notifications import NotificationTypes
from routes.integration.webhooks import state_changed_webhook


ORDER_ID = UUID("00000000-0000-0000-0000-000000000101")
USER_ID = UUID("00000000-0000-0000-0000-000000000102")


class Orders:
    async def get_order_by_id(self, order_id):
        assert order_id == ORDER_ID
        return {
            "id": str(order_id),
            "agent": {"meta": {"href": "/counterparty/client-id"}},
            "state": {"name": "Готов к выдаче"},
        }


class Users:
    async def get_by_moysklad(self, counterparty_id):
        assert counterparty_id == "client-id"
        return SimpleNamespace(id=USER_ID)


class Notifications:
    def __init__(self):
        self.created = []

    async def create_notification(self, data):
        self.created.append(data)


@pytest.mark.asyncio
async def test_order_wait_creates_only_the_website_notification():
    notifications = Notifications()

    await state_changed_webhook(
        id=ORDER_ID,
        moysklad_order_manager=Orders(),
        notification_manager=notifications,
        user_db=Users(),
    )

    assert len(notifications.created) == 1
    assert notifications.created[0].type == NotificationTypes.ORDER_UPDATED
    assert notifications.created[0].user_id == str(USER_ID)
    assert notifications.created[0].object_id == str(ORDER_ID)


def test_status_paths_do_not_import_or_call_telegram():
    for path in (
        Path("utils/celery_worker.py"),
        Path("routes/integration/webhooks.py"),
    ):
        source = path.read_text(encoding="utf-8").lower()
        assert "bot.sender" not in source
        assert "telegram" not in source
~~~

- [ ] **Step 2: Run the new tests and verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_status_notification_paths.py -q
~~~

Expected: the source guard fails because both status paths still import and invoke the sender.

- [ ] **Step 3: Remove Telegram sends and guard missing users**

In routes/integration/webhooks.py, remove the sender import and Telegram branch. After loading the user:

~~~python
if user is None:
    return None
notification_data = NotificationCreate(
    user_id=str(user.id),
    type=NotificationTypes.ORDER_UPDATED,
    object_id=str(moysklad_order["id"]),
)
await notification_manager.create_notification(notification_data)
~~~

In utils/celery_worker.py, remove the sender import and user.telegram_id branch. Create an ORDER_UPDATED notification only when user is not None. Do not broaden or redesign the scheduler exception handling in this task.

- [ ] **Step 4: Run focused verification**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_status_notification_paths.py tests/test_notifications.py tests/test_notifications_api.py -q
~~~

Expected: the webhook produces one website notification and neither active status path contains a Telegram reference.

- [ ] **Step 5: Commit the retained website notification behavior**

~~~powershell
git add utils/celery_worker.py routes/integration/webhooks.py tests/test_status_notification_paths.py
git commit -m "refactor: keep status notifications on site only"
~~~

### Task 4: Remove Telegram events while preserving order-chat delivery

**Files:**
- Modify: manager/order_chat.py
- Modify: manager/moysklad_order_chat.py
- Modify: manager/chat_outbox.py
- Modify: dependecies/order_chat.py
- Modify: db/order_chat_repository.py
- Modify: tests/test_order_chat_service.py
- Modify: tests/test_moysklad_order_chat.py
- Modify: tests/test_chat_outbox.py
- Modify: tests/test_order_chat_repository.py
- Create: tests/test_order_chat_runtime.py

**Interfaces:**
- Client messages emit exactly one sync_order outbox event.
- Manager replies create ORDER_MESSAGE website notifications and publish browser updates, but emit no Telegram event.
- Projection errors are logged with order_id and a bounded code; message and attachment contents are never logged.
- The outbox worker keeps sync_order and process_moysklad_update handlers.
- Lazy import_legacy_messages is removed only because Task 6 supplies the eager migration.

- [ ] **Step 1: Tighten order-chat service event assertions**

In tests/test_order_chat_service.py, change the file-only message assertion to:

~~~python
assert [event.event_type for event in repository.events] == ["sync_order"]
assert repository.events[0].dedup_key == f"sync_order:{result.id}"
~~~

Remove import_legacy_messages from FakeRepository and add:

~~~python
assert not hasattr(repository, "import_legacy_messages")
~~~

only after the production repository method is removed. Preserve storage cleanup tests and the HTTP-only send behavior.

- [ ] **Step 2: Rewrite MoySklad reply and projection-error assertions**

In tests/test_moysklad_order_chat.py, manager reply tests must assert:

~~~python
assert repository.notifications == [message.id]
assert repository.events == []
~~~

For malformed comments and invalid/too-many public files, use caplog:

~~~python
with caplog.at_level(logging.WARNING):
    await synchronizer.process_moysklad_update(inbound_event("bad-marker"))

assert repository.events == []
assert "order_chat_projection_rejected" in caplog.text
assert str(ORDER_ID) in caplog.text
assert "malformed_comment" in caplog.text
assert "случайно переписанный комментарий" not in caplog.text
~~~

Add analogous assertions for manager_file_count, manager_file_invalid, and moysklad_file_limit. The accepted code set is:

~~~python
{
    "malformed_comment",
    "manager_file_count",
    "manager_file_invalid",
    "moysklad_file_limit",
}
~~~

- [ ] **Step 3: Add a runtime handler-set test**

Create tests/test_order_chat_runtime.py. Construct settings with order chat enabled, monkeypatch storage/repository/MoySklad factories with existing fakes, call get_order_chat_runtime, and expose the worker handler names through a read-only property:

~~~python
def test_runtime_registers_only_durable_order_chat_handlers(monkeypatch):
    runtime = get_order_chat_runtime(order_chat_settings(), realtime=FakeRealtime())

    assert runtime.worker.handler_names == frozenset(
        {"sync_order", "process_moysklad_update"}
    )
~~~

In OrderChatOutboxWorker add:

~~~python
@property
def handler_names(self) -> frozenset[str]:
    return frozenset(self._handlers)
~~~

This property is diagnostic only and must not expose handler callables.

- [ ] **Step 4: Run focused tests and verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_chat_service.py tests/test_moysklad_order_chat.py tests/test_chat_outbox.py tests/test_order_chat_repository.py tests/test_order_chat_runtime.py -q
~~~

Expected: client/manager event assertions and runtime handler names fail while Telegram events remain registered.

- [ ] **Step 5: Emit only sync_order for client messages**

In manager/order_chat.py, replace the two-event tuple with:

~~~python
events = (
    NewOutboxEvent(
        event_type="sync_order",
        order_id=order_id,
        dedup_key=f"sync_order:{message_id}",
        payload={"message_id": str(message_id)},
    ),
)
~~~

Remove the lazy repository import call from _prepare_order:

~~~python
async def _prepare_order(self, user, order_id: UUID) -> dict:
    order = await self._access_policy.assert_client_access(user, order_id)
    try:
        await self._repository.ensure_state(order_id, user.id)
    except LookupError:
        raise OrderChatNotFound() from None
    return order
~~~

- [ ] **Step 6: Stop producing manager and projection Telegram events**

In manager/moysklad_order_chat.py, pass outbox_events=() to create_manager_message_with_notification. Add a module logger and replace _projection_error with:

~~~python
async def _projection_error(
    self,
    order_id,
    code: str,
    identity: str = "",
) -> None:
    logger.warning(
        "order_chat_projection_rejected",
        extra={
            "order_id": str(order_id),
            "code": code,
            "event_identity": identity[:128],
        },
    )
~~~

The caller-provided code is limited to the four constants asserted in tests. Do not log reply text, filenames, file bytes, customer metadata, or exception payloads.

- [ ] **Step 7: Remove Telegram handlers and lazy legacy import**

Delete OrderChatTelegramHandlers from manager/chat_outbox.py and remove the UUID import that existed only for it. In dependecies/order_chat.py:

- remove bot.sender and OrderChatTelegramHandlers imports;
- remove telegram_handlers construction;
- register exactly sync_order and process_moysklad_update.

In db/order_chat_repository.py, remove the legacy Message import and the entire import_legacy_messages method. Preserve legacy_message_id on the retained model as migration provenance.

- [ ] **Step 8: Run focused verification**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_chat_service.py tests/test_moysklad_order_chat.py tests/test_chat_outbox.py tests/test_order_chat_repository.py tests/test_order_chat_runtime.py -q
~~~

Expected: order chat still persists, syncs, publishes, notifies on site, retries durable events, and contains no Telegram event producer or handler.

- [ ] **Step 9: Commit the order-chat event cleanup**

~~~powershell
git add manager/order_chat.py manager/moysklad_order_chat.py manager/chat_outbox.py dependecies/order_chat.py db/order_chat_repository.py tests/test_order_chat_service.py tests/test_moysklad_order_chat.py tests/test_chat_outbox.py tests/test_order_chat_repository.py tests/test_order_chat_runtime.py
git commit -m "refactor: remove Telegram order chat events"
~~~

### Task 5: Remove legacy general support chat and MESSAGE notifications

**Files:**
- Modify: routes/chat.py
- Modify: routes/notifications.py
- Modify: dependecies/chat.py
- Delete: manager/chat.py
- Delete: db/models/chat.py
- Modify: db/schemas/notifications.py
- Modify: alembic/env.py
- Modify: tests/test_order_chat_api.py
- Modify: tests/test_notifications.py
- Modify: tests/test_notifications_api.py
- Modify: tests/test_chat_realtime.py
- Modify: tests/test_order_chat_models.py

**Interfaces:**
- Keeps: order message list/send, attachment download, and room-scoped WebSocket.
- Removes: /api_v1/chat/send_message, /api_v1/chat/messages, /api_v1/chat/messages/{chat_id}, legacy /api_v1/chat/{order_id}, and /api_v1/chat/.
- WebSocket query room is mandatory and must parse as UUID.
- WebSocket authentication failure closes with 4401; missing room closes with 4400; invalid/inaccessible order room closes with 4404.
- Client WebSocket writes continue to receive {type: error, code: order_chat_http_required}.

- [ ] **Step 1: Change API tests to demand route removal**

In tests/test_order_chat_api.py, replace the legacy reply-route test with:

~~~python
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api_v1/chat/send_message"),
        ("get", "/api_v1/chat/messages"),
        ("get", f"/api_v1/chat/messages/{ORDER_ID}"),
        ("post", f"/api_v1/chat/{ORDER_ID}"),
        ("get", f"/api_v1/chat/{ORDER_ID}"),
        ("get", "/api_v1/chat/"),
    ],
)
def test_legacy_support_chat_routes_are_removed(method, path):
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.request(method, path)

    assert response.status_code == 404
~~~

Add a missing-room WebSocket test:

~~~python
def test_order_websocket_requires_explicit_room(monkeypatch):
    app = create_app(Settings(_env_file=None, app_env="test"))
    monkeypatch.setattr(
        chat_routes,
        "authenticate_websocket_user",
        AsyncMock(return_value=SimpleNamespace(id=USER_ID)),
    )

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/api_v1/chat/ws?auth=token"):
                pass

    assert error.value.code == 4400
~~~

Update WebSocket dependency overrides from get_chat_manager to get_chat_realtime.

- [ ] **Step 2: Remove legacy notification fallbacks in tests**

In tests/test_notifications.py and tests/test_notifications_api.py:

- remove MESSAGE fixtures and MessageManager fakes;
- keep ORDER_MESSAGE enrichment from OrderChatRepository;
- assert a missing retained order-chat message is omitted instead of falling back to the dropped message table;
- keep ORDER_UPDATED and unread-count coverage.

The response assertion for a missing order message is:

~~~python
assert response == []
~~~

Add:

~~~python
def test_notification_types_exclude_legacy_support_message():
    assert {item.value for item in NotificationTypes} == {
        "ORDER_MESSAGE",
        "ORDER_UPDATED",
    }
~~~

In tests/test_order_chat_models.py add:

~~~python
def test_alembic_environment_does_not_import_legacy_chat_models():
    source = Path("alembic/env.py").read_text(encoding="utf-8")

    assert "chat as chat" not in source
~~~

- [ ] **Step 3: Run focused tests and verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_chat_api.py tests/test_notifications.py tests/test_notifications_api.py tests/test_chat_realtime.py -q
~~~

Expected: legacy routes remain mounted, missing room falls back to user.id, and MESSAGE remains in the enum.

- [ ] **Step 4: Reduce chat dependency wiring to realtime**

Replace dependecies/chat.py with the retained realtime factory:

~~~python
from functools import lru_cache

from db.redis import redis
from manager.chat_realtime import LocalChatHub, RedisChatRealtime


@lru_cache
def get_chat_realtime():
    return RedisChatRealtime(redis, LocalChatHub())
~~~

Delete manager/chat.py and db/models/chat.py. Remove db.models.chat from alembic/env.py; historical migrations remain discoverable without importing a deleted runtime model.

- [ ] **Step 5: Keep only order-chat routes and room-scoped WebSocket behavior**

In routes/chat.py, remove legacy imports, endpoints, commented legacy blocks, and support-room behavior. The WebSocket dependency and room checks become:

~~~python
@router.websocket("/ws")
async def websocket_connection(
    websocket: WebSocket,
    redis_strategy: RedisStrategy = Depends(get_redis_strategy),
    realtime=Depends(get_chat_realtime),
    order_access_policy: OrderChatAccessPolicy = Depends(
        get_order_chat_access_policy
    ),
):
    token = websocket.query_params.get("auth")
    if not token:
        await websocket.close(code=4401)
        return
    user = await authenticate_websocket_user(token, redis_strategy)
    if not user:
        await websocket.close(code=4401)
        return

    room_id = websocket.query_params.get("room")
    if not room_id:
        await websocket.close(code=4400)
        return
    try:
        order_id = UUID(room_id)
        await order_access_policy.assert_client_access(user, order_id)
    except (ValueError, OrderChatNotFound, IntegrationNotConfigured):
        await websocket.close(code=4404)
        return

    await realtime.connect(room_id, websocket)
    try:
        while True:
            await websocket.receive_json()
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "order_chat_http_required",
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        await realtime.disconnect(room_id, websocket)
~~~

- [ ] **Step 6: Remove MESSAGE notification enrichment**

In db/schemas/notifications.py:

~~~python
class NotificationTypes(str, Enum):
    ORDER_MESSAGE = "ORDER_MESSAGE"
    ORDER_UPDATED = "ORDER_UPDATED"
~~~

In routes/notifications.py, remove MessageManager/get_message_manager and the MESSAGE branch. The ORDER_MESSAGE branch must query only OrderChatRepository and append only when the retained message exists:

~~~python
case NotificationTypes.ORDER_MESSAGE.value:
    order_message = await order_chat_repository.get_message(
        notification.object_id
    )
    if order_message is not None:
        response.append(
            {
                **notification.__dict__,
                "id": notification.id,
                "object_id": str(order_message.id),
                "message": order_message.body,
                "first_name": "bot",
                "from_user_id": None,
                "to_chat_room_id": str(order_message.order_id),
                "time_created": order_message.created_at,
            }
        )
~~~

Do not rename first_name in this task; it is an existing frontend presentation field, not a Telegram account dependency.

- [ ] **Step 7: Run focused verification**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_order_chat_api.py tests/test_notifications.py tests/test_notifications_api.py tests/test_chat_realtime.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_order_chat_models.py -q
~~~

Expected: route, notification, realtime, and static Alembic import tests pass without requiring an active Alembic context.

- [ ] **Step 8: Commit the support-chat removal**

~~~powershell
git add routes/chat.py routes/notifications.py dependecies/chat.py manager/chat.py db/models/chat.py db/schemas/notifications.py alembic/env.py tests/test_order_chat_api.py tests/test_notifications.py tests/test_notifications_api.py tests/test_chat_realtime.py tests/test_order_chat_models.py
git commit -m "refactor: remove legacy support chat"
~~~

### Task 6: Backfill legacy order messages and remove obsolete database schema

**Files:**
- Create: alembic/versions/d4e5f6a7b8c9_remove_telegram.py
- Create: tests/test_remove_telegram_migration.py
- Modify: tests/conftest.py
- Modify: db/models/users.py
- Modify: db/schemas/users.py
- Modify: tests/test_order_chat_models.py
- Create: docs/operations/remove-telegram-production.md

**Interfaces:**
- New Alembic revision d4e5f6a7b8c9, down_revision b7e1d3a9f4c2.
- Upgrade preserves eligible order history in order_chat_message and rewrites ORDER_MESSAGE notification object IDs.
- Upgrade removes MESSAGE notifications, three Telegram outbox event types, message, chat_room, and user.telegram_id.
- Downgrade recreates empty legacy tables and a nullable telegram_id column; deleted values require backup restore.
- Dedicated bot@pixlogistic.com user is not deleted by this revision.

- [ ] **Step 1: Add a safe opt-in PostgreSQL test option**

In tests/conftest.py:

~~~python
from urllib.parse import urlsplit

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--migration-database-url",
        action="store",
        default=None,
        help="Loopback PostgreSQL URL for destructive migration tests",
    )


@pytest.fixture
def migration_database_url(request):
    value = request.config.getoption("--migration-database-url")
    if value is None:
        pytest.skip("requires --migration-database-url")
    host = urlsplit(value).hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("migration test database must use a loopback host")
    return value
~~~

Merge these definitions with the existing conftest imports and fixtures. The test must never accept a production hostname.

- [ ] **Step 2: Write static migration contract tests**

Create tests/test_remove_telegram_migration.py with:

~~~python
import runpy
from pathlib import Path


MIGRATION = Path(
    "alembic/versions/d4e5f6a7b8c9_remove_telegram.py"
)


def test_remove_telegram_revision_chain_and_destructive_order():
    module = runpy.run_path(str(MIGRATION))
    source = MIGRATION.read_text(encoding="utf-8")

    assert module["revision"] == "d4e5f6a7b8c9"
    assert module["down_revision"] == "b7e1d3a9f4c2"
    assert source.index("CREATE TEMP TABLE") < source.index(
        'op.drop_table("message")'
    )
    assert source.index("legacy_message_id") < source.index(
        'op.drop_table("message")'
    )
    assert source.index("ORDER_MESSAGE") < source.index(
        'op.drop_table("message")'
    )
    assert source.index("telegram_projection_error") < source.index(
        'op.drop_table("message")'
    )
    assert "bot@pixlogistic.com" in source
    assert 'op.delete("user")' not in source
~~~

Also assert downgrade recreates chat_room before message and adds user.telegram_id.

- [ ] **Step 3: Write opt-in PostgreSQL migration scenarios**

In the same test file, add async tests using create_async_engine, MigrationContext, and Operations. Each scenario:

1. creates a schema named remove_telegram_test_{uuid4().hex};
2. validates that prefix before any DROP SCHEMA;
3. creates minimal user, chat_room, message, notifications, order_chat_message, and chat_outbox_event tables in that schema;
4. seeds only synthetic UUIDs and non-customer strings;
5. commits the seed;
6. binds the migration module's op global to Operations(MigrationContext.configure(connection));
7. calls upgrade through connection.run_sync;
8. inspects results in a new transaction;
9. drops only the validated temporary schema in finally.

The successful seed includes:

- one message whose to_chat_room_id equals chat_room.id;
- one message whose to_chat_room_id equals chat_room.order_id;
- one pure support message with no order match;
- one already-imported order message with legacy_message_id populated;
- ORDER_MESSAGE notifications for the two order messages;
- one MESSAGE notification;
- all three Telegram outbox event types plus one sync_order event.

Assert after upgrade:

~~~python
assert await scalar("SELECT count(*) FROM order_chat_message") == 3
assert await scalar(
    "SELECT count(*) FROM order_chat_message "
    "WHERE source = 'legacy'"
) == 3
assert await scalar(
    "SELECT count(*) FROM notifications "
    "WHERE type = 'ORDER_MESSAGE'"
) == 2
assert await scalar(
    "SELECT count(*) FROM notifications WHERE type = 'MESSAGE'"
) == 0
assert await scalar(
    "SELECT count(*) FROM chat_outbox_event"
) == 1
assert await scalar(
    "SELECT count(*) FROM chat_outbox_event "
    "WHERE event_type = 'sync_order'"
) == 1
assert not await table_exists("message")
assert not await table_exists("chat_room")
assert not await column_exists("user", "telegram_id")
~~~

Assert each ORDER_MESSAGE object_id now joins order_chat_message.id and each source legacy row retains the original legacy_message_id and timestamp. Assert running upgrade logic against a pre-imported message does not duplicate it.

For the ambiguity scenario, create two chat rooms with the same order_id and one direct-order message. Assert the migration raises an error containing legacy order message mapping is ambiguous. In a fresh transaction, assert message, chat_room, user.telegram_id, notifications, and outbox rows remain because the failed migration transaction rolled back.

For the missing-client scenario, set chat_room.client_id to NULL and assert an error containing legacy order message has no client. Add a scenario where an ORDER_MESSAGE notification points to a legacy message that has no order mapping and assert preflight failure before destructive statements.

- [ ] **Step 4: Run static tests and verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_remove_telegram_migration.py -q
~~~

Expected: the migration file is absent. The PostgreSQL scenarios skip unless the explicit loopback option is supplied.

- [ ] **Step 5: Create the migration mapping and preflight**

Create alembic/versions/d4e5f6a7b8c9_remove_telegram.py with one op.execute call per SQL statement. First create the transaction-local mapping:

~~~sql
CREATE TEMP TABLE _legacy_order_message_map
ON COMMIT DROP
AS
SELECT
    m.id AS legacy_message_id,
    cr.id AS chat_room_id,
    cr.order_id,
    cr.client_id,
    CASE
        WHEN author.email = 'bot@pixlogistic.com' THEN 'manager'
        ELSE 'client'
    END AS sender_kind,
    m.message AS body,
    m.time_created AS created_at
FROM message AS m
JOIN chat_room AS cr
  ON m.to_chat_room_id = cr.id
  OR m.to_chat_room_id = cr.order_id
LEFT JOIN "user" AS author
  ON author.id = m.from_user_id
WHERE cr.order_id IS NOT NULL
~~~

Run separate DO blocks that raise before inserts or drops when:

~~~sql
EXISTS (
    SELECT 1
    FROM _legacy_order_message_map
    GROUP BY legacy_message_id
    HAVING count(*) > 1
)
~~~

or:

~~~sql
EXISTS (
    SELECT 1
    FROM _legacy_order_message_map
    WHERE client_id IS NULL
)
~~~

or an ORDER_MESSAGE notification points to a row in message but has no row in _legacy_order_message_map. Use these exact bounded exception messages:

- legacy order message mapping is ambiguous
- legacy order message has no client
- ORDER_MESSAGE notification has no order mapping

- [ ] **Step 6: Backfill and verify before destructive statements**

Insert retained history:

~~~sql
INSERT INTO order_chat_message (
    id,
    order_id,
    client_id,
    sender_kind,
    source,
    body,
    external_key,
    legacy_message_id,
    created_at
)
SELECT
    md5(map.legacy_message_id::text || ':order-chat')::uuid,
    map.order_id,
    map.client_id,
    map.sender_kind,
    'legacy',
    map.body,
    NULL,
    map.legacy_message_id,
    COALESCE(map.created_at, now())
FROM _legacy_order_message_map AS map
ON CONFLICT (legacy_message_id) DO NOTHING
~~~

Rewrite notification targets:

~~~sql
UPDATE notifications AS notification
SET object_id = retained.id
FROM order_chat_message AS retained
WHERE notification.type = 'ORDER_MESSAGE'
  AND notification.object_id = retained.legacy_message_id
~~~

Then use a DO block to raise legacy order message backfill incomplete if any distinct mapped legacy_message_id lacks a retained order_chat_message row. This verification must appear before every DELETE, DROP TABLE, and DROP COLUMN.

- [ ] **Step 7: Remove obsolete data and schema in dependency order**

After the backfill verification:

~~~sql
DELETE FROM notifications
WHERE type = 'MESSAGE'
~~~

~~~sql
DELETE FROM chat_outbox_event
WHERE event_type IN (
    'telegram_client_alert',
    'telegram_manager_alert',
    'telegram_projection_error'
)
~~~

Then call:

~~~python
op.drop_table("message")
op.drop_table("chat_room")
op.drop_column("user", "telegram_id")
~~~

Do not delete bot@pixlogistic.com and do not alter order_chat_message.legacy_message_id.

- [ ] **Step 8: Implement the data-loss-aware downgrade**

Downgrade in this order:

~~~python
op.add_column(
    "user",
    sa.Column("telegram_id", sa.Integer(), nullable=True),
)
op.create_table(
    "chat_room",
    sa.Column("id", sa.UUID(), nullable=False),
    sa.Column("members", sa.JSON(), nullable=True),
    sa.Column("client_id", sa.UUID(), nullable=True),
    sa.Column("order_id", sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(["client_id"], ["user.id"]),
    sa.PrimaryKeyConstraint("id"),
)
op.create_table(
    "message",
    sa.Column("id", sa.UUID(), nullable=False),
    sa.Column("message", sa.String(), nullable=False),
    sa.Column(
        "time_created",
        sa.DateTime(),
        server_default=sa.text("now()"),
        nullable=True,
    ),
    sa.Column("time_updated", sa.DateTime(), nullable=True),
    sa.Column("from_user_id", sa.UUID(), nullable=True),
    sa.Column("to_chat_room_id", sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(["from_user_id"], ["user.id"]),
    sa.PrimaryKeyConstraint("id"),
)
~~~

The current schema intentionally has no foreign key from message.to_chat_room_id after historical revision ad93a07ca785. Do not synthesize one.

- [ ] **Step 9: Remove the Telegram field from active models and schemas**

Delete telegram_id from db/models/users.py and db/schemas/users.py. Update tests/test_order_chat_models.py to import no legacy chat model and to assert:

~~~python
assert "telegram_id" not in User.__table__.c
assert "telegram_id" not in UserUpdate.model_fields
assert OrderChatMessage.__table__.c.legacy_message_id.unique is True
~~~

- [ ] **Step 10: Add the production migration runbook**

Create docs/operations/remove-telegram-production.md with:

- exact revision d4e5f6a7b8c9 and current predecessor b7e1d3a9f4c2;
- backup and restore owner, backup validation, and image-tag capture requirements;
- read-only count queries that return counts only, never message bodies;
- an ambiguity and NULL-client audit matching the migration mapping;
- an ORDER_MESSAGE mapping audit;
- an audit of references to the exact bot@pixlogistic.com account, with no delete command;
- manual review of the active database host and database name;
- the separately approved alembic upgrade d4e5f6a7b8c9 command;
- post-migration schema/count checks;
- rollback distinction before and after migration.

The runbook must state that downgrade restores empty compatibility structures and a backup is required for deleted values.

- [ ] **Step 11: Run static and opt-in local PostgreSQL tests**

Start only the repository's local PostgreSQL service, then run:

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_remove_telegram_migration.py tests/test_order_chat_models.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_remove_telegram_migration.py --migration-database-url postgresql+asyncpg://pix:pix_local@127.0.0.1:5431/pix -q
.\.venv\Scripts\alembic.exe history
.\.venv\Scripts\alembic.exe heads
~~~

Expected: semantic scenarios pass against loopback PostgreSQL, history has one head d4e5f6a7b8c9, and no upgrade or downgrade command has run against the repository database.

- [ ] **Step 12: Manually review migration safety**

Review the final migration diff and confirm:

- all preflight blocks precede inserts/deletes/drops;
- backfill verification precedes destructive statements;
- only MESSAGE notifications are deleted;
- only the three named Telegram outbox event types are deleted;
- sync_order and process_moysklad_update rows are retained;
- message is dropped before chat_room;
- user.telegram_id is the only user column dropped;
- the downgrade warning is present in the runbook;
- no user account is deleted.

- [ ] **Step 13: Commit the reviewed database boundary**

~~~powershell
git add alembic/versions/d4e5f6a7b8c9_remove_telegram.py tests/test_remove_telegram_migration.py tests/conftest.py db/models/users.py db/schemas/users.py tests/test_order_chat_models.py docs/operations/remove-telegram-production.md
git commit -m "feat: migrate away from Telegram support data"
~~~

### Task 7: Remove Telegram runtime configuration, dependencies, topology, and active backend docs

**Files:**
- Modify: config.py
- Modify: manager/production_config.py
- Modify: .env.example
- Modify: .env.production.example
- Modify: docker-compose.yml
- Modify: requirements.txt
- Delete: bot/sender.py
- Modify: scripts/check.ps1
- Modify: tests/test_config.py
- Modify: tests/test_integrations.py
- Modify: tests/test_production_config.py
- Create: tests/test_no_active_telegram.py
- Modify: README.md
- Modify: AGENTS.md
- Modify: docs/ARCHITECTURE.md
- Modify: docs/ENVIRONMENT.md
- Modify: docs/LOCAL_DEVELOPMENT.md
- Modify: docs/SECURITY_NOTES.md

**Interfaces:**
- Removes settings BOT_TOKEN, CHAT_ID, HELP_CHAT_ID, and TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS.
- Order-chat production preflight still requires MoySklad, webhook, MinIO, Redis, and database values, but no notification service.
- Removes the repository Compose bot service and aiogram/magic-filter dependencies.
- Keeps aiohttp because manager/link_preview.py uses it.

- [ ] **Step 1: Rewrite configuration and production-preflight tests**

In tests/test_config.py, remove blank chat-ID and Telegram timeout tests. Add:

~~~python
def test_settings_have_no_telegram_fields():
    fields = Settings.model_fields

    assert "bot_token" not in fields
    assert "chat_id" not in fields
    assert "help_chat_id" not in fields
    assert "telegram_notification_timeout_seconds" not in fields
~~~

In tests/test_production_config.py, remove the four keys and sensitive sample values from every exact inventory. The missing order-chat set must be:

~~~python
{
    "ENABLE_MOYSKLAD_ORDER_CHAT",
    "MOYSKLAD_LOGIN",
    "MOYSKLAD_PASSWORD",
    "MOYSKLAD_ORDER_CHAT_WEBHOOK_SECRET",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
}
~~~

The complete order-chat preflight fixture must pass without bot_token, chat_id, or help_chat_id.

In tests/test_integrations.py, remove the Sender import and test_telegram_requires_token_before_sending. Keep the missing-credential tests for MoySklad, Bitrix, Privoz, email, and other retained integrations.

- [ ] **Step 2: Add an active-source guard**

Create tests/test_no_active_telegram.py:

~~~python
from pathlib import Path


SOURCE_ROOTS = (
    Path("config.py"),
    Path("main.py"),
    Path("bot"),
    Path("db"),
    Path("dependecies"),
    Path("manager"),
    Path("routes"),
    Path("utils"),
)
CONFIG_FILES = (
    Path(".env.example"),
    Path(".env.production.example"),
    Path("docker-compose.yml"),
    Path("requirements.txt"),
)
FORBIDDEN = (
    "telegram",
    "aiogram",
    "bot_token",
    "help_chat_id",
    "telegram_notification_timeout_seconds",
    "telegram_client_alert",
    "telegram_manager_alert",
    "telegram_projection_error",
)


def active_files():
    for root in SOURCE_ROOTS:
        if root.is_file():
            yield root
        elif root.exists():
            yield from (
                path
                for path in root.rglob("*.py")
                if "__pycache__" not in path.parts
            )
    yield from CONFIG_FILES


def test_active_backend_has_no_telegram_runtime_reference():
    violations = {}
    for path in active_files():
        source = path.read_text(encoding="utf-8").lower()
        matched = [term for term in FORBIDDEN if term in source]
        if matched:
            violations[str(path)] = matched

    assert violations == {}
~~~

Historical Alembic revisions, the removal migration, approved specifications/plans, and the production removal runbook are intentionally outside this guard.

- [ ] **Step 3: Run configuration tests and verify RED**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_integrations.py tests/test_production_config.py tests/test_no_active_telegram.py -q
~~~

Expected: settings, preflight, source, environment, Compose, and dependency references still fail the new contract.

- [ ] **Step 4: Remove active settings and validation**

In config.py, remove:

- telegram_notification_timeout_seconds;
- bot_token;
- chat_id;
- help_chat_id;
- blank_optional_ids_are_none.

Remove field_validator from imports; the removed chat-ID normalizer is its only current use. Preserve SecretStr and require_secret for retained integrations.

In manager/production_config.py, remove the three Telegram checks from _validate_order_chat. Do not loosen webhook, MinIO, MoySklad, HTTPS/CORS, database, Redis, or authentication validation.

- [ ] **Step 5: Remove environment and Compose topology**

Delete the four Telegram variables from .env.example and .env.production.example. Delete only the bot service block from docker-compose.yml:

~~~yaml
  bot:
    image: logistic_bot:latest
    restart: always
    env_file:
      - .env
~~~

Do not remove backend, PostgreSQL, Redis, MinIO, pgAdmin, networks, or volumes.

- [ ] **Step 6: Remove the sender and dependency packages**

Delete bot/sender.py; it is the only tracked source in bot, so no active bot package remains. Remove aiogram and magic-filter from requirements.txt. Keep aiohttp and its retained transitive/runtime requirements required by link preview.

Do not run a broad dependency upgrade. The requirements change is deletion-only.

- [ ] **Step 7: Update scoped checks**

In scripts/check.ps1:

- remove bot/sender.py and manager/chat.py from the Ruff target list;
- keep dependecies/chat.py and manager/chat_realtime.py;
- add alembic/versions/d4e5f6a7b8c9_remove_telegram.py to the migration files already listed;
- keep the full pytest tests invocation.

- [ ] **Step 8: Rewrite active backend documentation**

Update README.md, AGENTS.md, docs/ARCHITECTURE.md, docs/ENVIRONMENT.md, docs/LOCAL_DEVELOPMENT.md, and docs/SECURITY_NOTES.md to describe:

- email verification plus MoySklad counterparty linking without side notifications;
- website ORDER_UPDATED and ORDER_MESSAGE notifications;
- order-only chat with PostgreSQL, MinIO, MoySklad, Redis, and WebSockets;
- no general support chat or /bot router;
- only the retained integrations and configuration, with every description of the retired bot, sender, service, and variables removed;
- scheduler integration requirements without Telegram;
- the manual removal migration/runbook and backup requirement.

Preserve MOYSKLAD_PASSWORD as canonical and MOYSKLAD_PASWORD as its legacy alias. Do not rewrite archived files under docs/superpowers.

- [ ] **Step 9: Run focused and full backend checks**

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_integrations.py tests/test_production_config.py tests/test_no_active_telegram.py -q
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
.\.venv\Scripts\alembic.exe history
.\.venv\Scripts\alembic.exe heads
git diff --check
~~~

Expected: tests pass, the backend check passes, Alembic has one head d4e5f6a7b8c9, and no migration is applied.

- [ ] **Step 10: Commit active backend cleanup**

~~~powershell
git add config.py manager/production_config.py .env.example .env.production.example docker-compose.yml requirements.txt bot/sender.py scripts/check.ps1 tests/test_config.py tests/test_integrations.py tests/test_production_config.py tests/test_no_active_telegram.py README.md AGENTS.md docs/ARCHITECTURE.md docs/ENVIRONMENT.md docs/LOCAL_DEVELOPMENT.md docs/SECURITY_NOTES.md
git commit -m "chore: remove Telegram runtime configuration"
~~~

### Task 8: Remove Telegram and general-support UI from the frontend

**Repository:** C:\Users\zenja\IdeaProjects\pix_frontend_v2

**Files:**
- Modify: src/app/page.tsx
- Modify: src/app/auth/page.tsx
- Modify: src/app/dashboard/page.tsx
- Modify: src/app/dashboard/layout.tsx
- Delete: src/app/telegram/[telegram_id]/page.jsx
- Delete: public/Telegram.tsx
- Delete: src/components/supportChat/supportChat.tsx
- Modify: src/routes/routes.tsx
- Modify: scripts/check-api-url.mjs
- Create: scripts/check-removed-integrations.mjs
- Modify: package.json
- Create: tests/removed-integrations.spec.ts
- Modify: README.md
- Modify: AGENTS.md

**Interfaces:**
- Removes every t.me link, Telegram account-link route, bot promotion, and floating general-support chat.
- Removes general-chat API helpers GetMessagesEndpoint and GetMessagesOrderEndpoint plus getMessagesType.
- Preserves GetOrderChatMessages, SendOrderChatMessage, order attachments, and the room query used by OrderChatPanel.

- [ ] **Step 1: Add a browser regression test for removed UI and route**

Create tests/removed-integrations.spec.ts:

~~~typescript
import { expect, test } from "@playwright/test";

test("public and dashboard pages expose no removed messaging UI", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator('a[href*="t.me"]')).toHaveCount(0);

  await page.goto("/auth");
  await expect(page.locator('a[href*="t.me"]')).toHaveCount(0);

  await page.context().addCookies([
    {
      name: "token",
      value: "Bearer test-token",
      domain: "127.0.0.1",
      path: "/",
    },
  ]);
  await page.goto("/dashboard/main");
  await expect(page.getByText("Бот в телеграм")).toHaveCount(0);
  await expect(page.getByText("Поддержка")).toHaveCount(0);
  await expect(page.locator('a[href*="t.me"]')).toHaveCount(0);
});

test("removed Telegram account-link page returns not found", async ({
  page,
}) => {
  const response = await page.goto("/telegram/123456");

  expect(response?.status()).toBe(404);
});
~~~

The cookie domain in this test matches the configured Playwright base URL http://127.0.0.1:3100 and the existing mock token contract.

- [ ] **Step 2: Add an active frontend source guard**

Create scripts/check-removed-integrations.mjs:

~~~javascript
import { readdir, readFile } from "node:fs/promises";
import { extname, join } from "node:path";

const roots = ["src", "public"];
const extensions = new Set([".js", ".jsx", ".ts", ".tsx"]);
const forbidden = [
  ["t.me link", /t\.me/i],
  ["account-link API", /users\/telegram/i],
  ["bot promotion", /Бот в телеграм/i],
  ["legacy chat/messages route", /chat\/messages/i],
  ["SupportChat component", /SupportChat/],
];

async function filesUnder(root) {
  const result = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) {
      result.push(...(await filesUnder(path)));
    } else if (extensions.has(extname(entry.name))) {
      result.push(path);
    }
  }
  return result;
}

const violations = [];
for (const root of roots) {
  for (const file of await filesUnder(root)) {
    const source = await readFile(file, "utf8");
    for (const [label, pattern] of forbidden) {
      if (pattern.test(source)) {
        violations.push(file + ": " + label);
      }
    }
  }
}

if (violations.length > 0) {
  throw new Error(violations.join("\n"));
}
~~~

The legacy route check matches chat/messages and does not match retained chat/orders/{orderId}/messages. Task 9 adds the broader source-wide retired-integration word guard after the order-warning branch is removed.

Add:

~~~json
"check:removed-integrations": "node scripts/check-removed-integrations.mjs"
~~~

and include it in check before the build.

- [ ] **Step 3: Run the new guards and verify RED**

~~~powershell
npm.cmd run check:removed-integrations
npx.cmd playwright test tests/removed-integrations.spec.ts
~~~

Expected: the source guard lists the current icon, route, support widget, and legacy API helpers; browser tests find the current links/UI.

- [ ] **Step 4: Remove social icon, bot promotion, and account-link page**

Remove Telegram imports and JSX from src/app/page.tsx and src/app/auth/page.tsx. Keep Mail and the current spacing responsive.

In src/app/dashboard/page.tsx:

- remove Link and Telegram imports;
- remove the entire bot promotion column;
- remove the Telegram icon;
- remove the instruction that tells users to click the general chat icon;
- keep new-user guidance, order workflow guidance, the order-specific manager chat instruction, and Mail.

Delete public/Telegram.tsx and src/app/telegram/[telegram_id]/page.jsx.

- [ ] **Step 5: Remove the floating support widget**

Delete src/components/supportChat/supportChat.tsx. In src/app/dashboard/layout.tsx:

- remove the SupportChat import;
- remove the supportChat prop and its default;
- remove conditional SupportChat rendering;
- simplify the order-detail DashboardShell call to selectedItem plus children.

Keep NotificationCountProvider, Balance, Navbar, pathname selection, and order-detail layout behavior.

- [ ] **Step 6: Remove legacy chat API helpers**

In src/routes/routes.tsx delete:

- getMessagesType;
- GetMessagesEndpoint;
- GetMessagesOrderEndpoint.

Keep getNotificationsType presentation fields until a separate notification UI contract cleanup; they are populated by retained ORDER_MESSAGE notifications.

- [ ] **Step 7: Update source inventory and active frontend docs**

Remove the deleted Telegram page from scripts/check-api-url.mjs. Update README.md and AGENTS.md to describe order-specific chat only, with no account-link page or support widget. Historical files under docs/superpowers remain unchanged.

- [ ] **Step 8: Run focused frontend verification**

~~~powershell
npm.cmd run check:removed-integrations
npm.cmd run check:api-url
npx.cmd playwright test tests/removed-integrations.spec.ts tests/order-chat.spec.ts
npm.cmd run lint
~~~

Expected: removed UI stays absent and retained order chat still loads, posts history requests, and connects with a room-scoped WebSocket.

- [ ] **Step 9: Commit the frontend UI removal**

~~~powershell
git add src/app/page.tsx src/app/auth/page.tsx src/app/dashboard/page.tsx src/app/dashboard/layout.tsx src/app/telegram/[telegram_id]/page.jsx public/Telegram.tsx src/components/supportChat/supportChat.tsx src/routes/routes.tsx scripts/check-api-url.mjs scripts/check-removed-integrations.mjs package.json tests/removed-integrations.spec.ts README.md AGENTS.md
git commit -m "refactor: remove Telegram and support chat UI"
~~~

### Task 9: Align frontend order-change contracts and mocks

**Repository:** C:\Users\zenja\IdeaProjects\pix_frontend_v2

**Files:**
- Modify: src/routes/routes.tsx
- Modify: src/app/dashboard/orders/[id]/page.tsx
- Modify: src/app/dashboard/orders/[id]/orderPresentation.ts
- Modify: tests/order-changes.spec.ts
- Modify: tests/mock-backend.mjs
- Create: src/routes/routes.test.ts
- Modify: scripts/check-removed-integrations.mjs

**Interfaces:**
- Frontend OrderChangesResponse becomes {order, changed}.
- A successful save always uses the normal success toast.
- OrderAlert supports version-conflict only.
- Mock backend no longer returns notification_sent or hosts telegram-warning-order fixtures.

- [ ] **Step 1: Rewrite unit and browser assertions**

Create src/routes/routes.test.ts:

~~~typescript
import { describe, expect, it } from "vitest";

import type { OrderChangesResponse } from "./routes";

describe("OrderChangesResponse", () => {
  it("contains only the order result and changed flag", () => {
    const response: OrderChangesResponse = {
      order: {} as OrderChangesResponse["order"],
      changed: true,
    };

    expect(Object.keys(response).sort()).toEqual(["changed", "order"]);
  });
});
~~~

This test fails to type-check while notification_sent remains required.

In tests/order-changes.spec.ts, delete the test named warns about Telegram without offering to resave an already saved order. In the main save test, assert one success toast and no warning:

~~~typescript
await expect(page.getByText("Заказ успешно сохранён")).toBeVisible();
await expect(
  page.getByText(/уведомление не отправлено/i),
).toHaveCount(0);
~~~

- [ ] **Step 2: Run focused tests and verify RED**

~~~powershell
npm.cmd run test:unit -- src/routes/routes.test.ts
npx.cmd playwright test tests/order-changes.spec.ts
~~~

Expected: the frontend type and page still inspect notification_sent and the mock still supplies the Telegram-warning scenario.

- [ ] **Step 3: Remove the response field and warning branch**

In src/routes/routes.tsx:

~~~typescript
export type OrderChangesResponse = {
  order: GetOrderType;
  changed: boolean;
};
~~~

In the order detail page, replace the conditional warning with the existing ordinary success path:

~~~typescript
setOrder(response.data.order);
setAlert(null);
toast.success("Заказ успешно сохранён");
~~~

Do not change version-conflict recovery.

In orderPresentation.ts:

~~~typescript
export type OrderAlert =
  | { kind: "version-conflict"; message: string }
  | null;
~~~

In scripts/check-removed-integrations.mjs, prepend the broad guard now that all active frontend Telegram behavior is gone:

~~~javascript
["telegram", /telegram/i],
~~~

- [ ] **Step 4: Simplify mock backend contracts**

In tests/mock-backend.mjs:

- delete telegramWarningOrder;
- delete its order, action, and legacy chat routes;
- remove notification_sent from every order-change response;
- keep the regular order, version-conflict, addresses, notifications, and retained chat/orders routes.

The successful response shape must be:

~~~javascript
return sendJson(response, {
  order: updatedOrder,
  changed: true,
});
~~~

- [ ] **Step 5: Run focused and full frontend checks**

~~~powershell
npm.cmd run test:unit -- src/routes/routes.test.ts
npx.cmd playwright test tests/order-changes.spec.ts tests/order-chat.spec.ts tests/removed-integrations.spec.ts
npm.cmd run check
git diff --check
~~~

Expected: unit, lint, source guards, production build, and all Playwright tests pass with the two-field contract.

- [ ] **Step 6: Commit the frontend contract change**

~~~powershell
git add src/routes/routes.tsx src/routes/routes.test.ts src/app/dashboard/orders/[id]/page.tsx src/app/dashboard/orders/[id]/orderPresentation.ts scripts/check-removed-integrations.mjs tests/order-changes.spec.ts tests/mock-backend.mjs
git commit -m "refactor: remove Telegram order warning contract"
~~~

### Task 10: Cross-repository acceptance and deployment handoff

**Files:**
- Verify: backend working tree and commit history
- Verify: frontend working tree and commit history
- Verify: docs/operations/remove-telegram-production.md
- No production mutation in this task

**Acceptance contracts:**
- Correct email verification completes without constructing or awaiting Telegram.
- Order create/edit/confirm/cancel performs no Telegram request and keeps MoySklad results.
- Website ORDER_UPDATED and ORDER_MESSAGE notifications remain.
- Order-chat HTTP, MinIO, PostgreSQL, MoySklad projection, Redis/WebSocket, and delivery-state behavior remain.
- General support UI/API and Telegram UI/API/config/topology are absent.
- Migration has one reviewed head but is not applied automatically.

- [ ] **Step 1: Run the final backend verification after the last edit**

~~~powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
.\.venv\Scripts\python.exe -c "import main; assert main.app is not None"
.\.venv\Scripts\alembic.exe history
.\.venv\Scripts\alembic.exe heads
.\.venv\Scripts\python.exe -m pytest tests/test_remove_telegram_migration.py --migration-database-url postgresql+asyncpg://pix:pix_local@127.0.0.1:5431/pix -q
git diff --check
~~~

Expected: backend checks pass, main imports offline, migration semantics pass on loopback PostgreSQL, and d4e5f6a7b8c9 is the only head. Do not run alembic upgrade.

- [ ] **Step 2: Run the final frontend verification after the last edit**

From C:\Users\zenja\IdeaProjects\pix_frontend_v2:

~~~powershell
npm.cmd run check
git diff --check
~~~

Expected: lint, both source guards, unit tests, production build, and Playwright pass.

- [ ] **Step 3: Audit active references with historical exclusions**

From the backend:

~~~powershell
rg -n -i "telegram|bot_token|help_chat_id|telegram_notification_timeout|aiogram|magic-filter|telegram_client_alert|telegram_manager_alert|telegram_projection_error" config.py main.py bot db dependecies manager routes utils .env.example .env.production.example docker-compose.yml requirements.txt README.md AGENTS.md docs/ARCHITECTURE.md docs/ENVIRONMENT.md docs/LOCAL_DEVELOPMENT.md docs/SECURITY_NOTES.md
~~~

Expected: no matches; a missing bot directory is acceptable.

From the frontend:

~~~powershell
rg -n -i "telegram|t\.me|SupportChat|chat/messages|notification_sent" src public README.md AGENTS.md
~~~

Expected: no matches. References in historical migrations, archived docs, the approved removal spec/plan, migration tests, and the production removal runbook are expected and must not be edited merely to satisfy this search.

- [ ] **Step 4: Review route and response contracts across repositories**

Confirm from generated FastAPI routes and frontend client source:

- /api_v1/users/telegram/{telegram_id} and /api_v1/bot/* are absent;
- legacy /api_v1/chat/messages* and /api_v1/chat/send_message are absent;
- GET/POST /api_v1/chat/orders/{order_id}/messages and attachments remain;
- /api_v1/chat/ws requires auth and room;
- backend and frontend OrderChangesResponse fields are exactly order and changed.

- [ ] **Step 5: Review git scope without disturbing user changes**

In each repository:

~~~powershell
git status --short
git log --oneline -12
~~~

Confirm each commit contains only named task files. Pre-existing modified bytecode, migration edits, tests, logs, images, and untracked documents remain untouched unless they were explicitly part of this plan.

- [ ] **Step 6: Prepare the release handoff, then stop**

Report:

- backend and frontend commit IDs;
- exact verification commands and fresh outcomes;
- migration revision d4e5f6a7b8c9 and confirmation that it was not applied;
- local migration test counts and scenarios;
- any residual references limited to approved historical/removal records;
- compatibility order: frontend/backend images first, manual migration last;
- required validated backup and captured image tags;
- explicit pending actions: production deployment, migration, protected environment cleanup, and bot-container removal.

Do not connect to production, delete the running bot container, edit protected environment values, migrate the database, or delete bot@pixlogistic.com until the user separately authorizes that deployment stage after reviewing the runbook and backup plan.

## Completion Definition

Implementation is complete only when all backend and frontend checks have been rerun after the final edits, migration semantics have passed against loopback PostgreSQL, the only active Telegram references are the reviewed removal migration/runbook or immutable historical records, and no production mutation has occurred.
