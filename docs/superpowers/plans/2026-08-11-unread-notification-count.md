# Unread Notification Count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display an authoritative, real-time unread-notification count in the dashboard navigation and notifications-page heading, with user-scoped read operations and cross-tab synchronization.

**Architecture:** PostgreSQL remains the source of truth. A focused notification repository performs count and user-scoped bulk mutations, `NotificationManager` publishes absolute count events, and a Redis-backed per-user WebSocket channel fans those events out across backend workers. A dashboard-level React provider owns initial REST synchronization, WebSocket reconnects, and optimistic local count transitions for the Navbar and notifications page.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, PostgreSQL, Redis pub/sub, Pydantic, pytest; Next.js 14, React 18, TypeScript, Axios, Tailwind CSS, Vitest, Playwright.

## Global Constraints

- Keep the public API prefix `/api_v1` and authenticate every count/read/WebSocket operation as the current user.
- Add `GET /api_v1/notifications/unread-count` and `WS /api_v1/notifications/ws?auth=<token>`.
- WebSocket events use `{"type":"notification_count","unread_count":number}` and carry an absolute non-negative count.
- Do not add an Alembic migration; the existing `notifications.is_readed` column remains the source of truth.
- A single-notification read must require both notification ID and current user ID; a bulk read must use one SQL `UPDATE`.
- Preserve reading on both hover and click, plus the existing “Прочитать всё” action.
- Hide the Navbar badge at zero and display an explicit zero beside the notifications-page heading.
- Close an unauthenticated notification WebSocket with code `4401` and do not expose another user's channel.
- Publish the order-chat notification event only after its message/notification transaction commits.
- Background count synchronization must not show toast notifications or contact production services during import/tests.
- Run backend `powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1` and frontend `npm.cmd run check` after the final edit.

## File Structure

### Backend

- Create `db/notification_repository.py` — notification-specific SQL persistence and user-scoped count/read operations.
- Create `manager/notification_realtime.py` — Redis channel specialization for per-user count events.
- Create `tests/test_notifications.py` — manager behavior and publication tests.
- Create `tests/test_notification_repository.py` — SQL boundary tests for count and user ownership predicates.
- Create `tests/test_notifications_api.py` — REST and WebSocket contracts.
- Modify `db/schemas/notifications.py` — typed REST and WebSocket count payloads.
- Modify `manager/notifications.py` — count orchestration, idempotent reads, and best-effort publication.
- Modify `dependecies/notifications.py` — cached realtime hub and manager construction.
- Modify `routes/notifications.py` — count/read REST contracts and authenticated WebSocket.
- Modify `main.py` — notification realtime lifecycle.
- Modify `manager/moysklad_order_chat.py` and `dependecies/order_chat.py` — post-commit order-chat count publication.
- Modify `utils/celery_worker.py` — construct the scheduler manager with the shared realtime publisher.
- Modify `scripts/check.ps1` — lint all newly active notification modules.
- Modify `docs/ARCHITECTURE.md` — document the count channel and data flow.

### Frontend

- Create `src/features/notifications/notificationCount.ts` — pure count validation/retry helpers.
- Create `src/features/notifications/notificationCount.test.ts` — Vitest behavior tests.
- Create `src/features/notifications/NotificationCountProvider.tsx` — dashboard count context, REST sync, and WebSocket lifecycle.
- Create `tests/notifications.spec.ts` — browser coverage for both badges, reading, realtime, rollback, and reconnect.
- Modify `src/routes/routes.tsx` — typed count/read API functions without background toast.
- Modify `src/app/dashboard/layout.tsx` — mount one count provider above all dashboard branches.
- Modify `src/components/navbar/navbar.tsx` — render the responsive unread badge.
- Modify `src/app/dashboard/notifications/page.tsx` — heading count and safe optimistic read behavior.
- Modify `tests/mock-backend.mjs` — deterministic notification fixtures and read/count test endpoints.

---

### Task 1: Notification Persistence and Manager Semantics

**Files:**
- Create: `db/notification_repository.py`
- Create: `tests/test_notification_repository.py`
- Create: `tests/test_notifications.py`
- Modify: `db/schemas/notifications.py`
- Modify: `manager/notifications.py`
- Modify: `dependecies/notifications.py`
- Modify: `utils/celery_worker.py`

**Interfaces:**
- Produces: `NotificationRepository.create`, `list_for_user`, `count_unread`, `mark_read`, and `mark_all_read`.
- Produces: `NotificationManager.unread_count(user_id) -> int`, `read_notification(user_id, notification_id) -> int`, `read_all_notifications(user_id) -> int`, and `notify_count_changed(user_id) -> None`.
- Produces: `NotificationCountResponse(unread_count: int)` and `NotificationCountEvent(type="notification_count", unread_count: int)`.
- Consumes: an optional realtime object exposing `publish(user_id: str, payload: dict) -> Awaitable[None]`.

- [ ] **Step 1: Write manager tests that name the ownership, idempotency, and publication failures**

Create `tests/test_notifications.py` with a stateful in-memory repository and recording realtime boundary:

```python
from types import SimpleNamespace
from uuid import UUID

from db.schemas.notifications import NotificationCreate, NotificationTypes
from manager.notifications import NotificationManager

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000002")
NOTIFICATION_ID = UUID("00000000-0000-0000-0000-000000000010")


class MemoryNotificationRepository:
    def __init__(self):
        self.rows = {
            NOTIFICATION_ID: SimpleNamespace(
                id=NOTIFICATION_ID, user_id=USER_ID, is_readed=False
            )
        }

    async def create(self, **values):
        values["user_id"] = UUID(str(values["user_id"]))
        self.rows[NOTIFICATION_ID] = SimpleNamespace(
            id=NOTIFICATION_ID, is_readed=False, **values
        )
        return NOTIFICATION_ID

    async def list_for_user(self, user_id):
        return [row for row in self.rows.values() if row.user_id == user_id]

    async def count_unread(self, user_id):
        return sum(
            row.user_id == user_id and not row.is_readed
            for row in self.rows.values()
        )

    async def mark_read(self, notification_id, user_id):
        row = self.rows.get(notification_id)
        if row is None or row.user_id != user_id or row.is_readed:
            return False
        row.is_readed = True
        return True

    async def mark_all_read(self, user_id):
        changed = 0
        for row in self.rows.values():
            if row.user_id == user_id and not row.is_readed:
                row.is_readed = True
                changed += 1
        return changed


class RecordingRealtime:
    def __init__(self, error=None):
        self.events = []
        self.error = error

    async def publish(self, user_id, payload):
        if self.error:
            raise self.error
        self.events.append((str(user_id), payload))


async def test_read_one_cannot_change_another_users_notification():
    repository = MemoryNotificationRepository()
    realtime = RecordingRealtime()
    manager = NotificationManager(repository, realtime)

    count = await manager.read_notification(OTHER_ID, NOTIFICATION_ID)

    assert count == 0
    assert repository.rows[NOTIFICATION_ID].is_readed is False
    assert realtime.events[-1][1] == {
        "type": "notification_count",
        "unread_count": 0,
    }


async def test_read_and_read_all_publish_absolute_counts_idempotently():
    repository = MemoryNotificationRepository()
    realtime = RecordingRealtime()
    manager = NotificationManager(repository, realtime)

    assert await manager.read_notification(USER_ID, NOTIFICATION_ID) == 0
    assert await manager.read_notification(USER_ID, NOTIFICATION_ID) == 0
    assert await manager.read_all_notifications(USER_ID) == 0
    assert [event[1]["unread_count"] for event in realtime.events] == [0, 0, 0]


async def test_created_notification_survives_realtime_failure():
    repository = MemoryNotificationRepository()
    manager = NotificationManager(repository, RecordingRealtime(RuntimeError("redis")))

    created = await manager.create_notification(
        NotificationCreate(
            user_id=str(USER_ID),
            type=NotificationTypes.MESSAGE,
            object_id=str(NOTIFICATION_ID),
        )
    )

    assert created == NOTIFICATION_ID
    assert await repository.count_unread(USER_ID) == 1
```

- [ ] **Step 2: Run the manager tests and verify RED**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_notifications.py -q
```

Expected: collection or constructor/method failures because the new manager contract and count schemas do not exist.

- [ ] **Step 3: Write repository SQL boundary tests before the repository**

In `tests/test_notification_repository.py`, use a recording async session whose `execute()` stores the SQLAlchemy statement and returns fixed scalar values. Compile statements with `sqlalchemy.dialects.postgresql.dialect()` and assert these observable query boundaries:

```python
assert "notifications.user_id" in compiled_count
assert "notifications.is_readed IS false" in compiled_count
assert "notifications.id" in compiled_mark_one
assert "notifications.user_id" in compiled_mark_one
assert "notifications.is_readed IS false" in compiled_mark_all
assert session.commit_count == 2
```

The fixtures must return literal values `3`, `NOTIFICATION_ID`, and two returned IDs so the public results are exactly `3`, `True`, and `2`.

- [ ] **Step 4: Run the repository tests and verify RED**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_notification_repository.py -q
```

Expected: FAIL because `db.notification_repository.NotificationRepository` is missing.

- [ ] **Step 5: Implement the focused repository, schemas, and manager**

Create `db/notification_repository.py` around an injectable session factory:

```python
from sqlalchemy import func, insert, select, update

from db.models.notifications import Notifications
from db.postgres import async_session_maker


class NotificationRepository:
    def __init__(self, session_factory=async_session_maker):
        self._session_factory = session_factory

    async def create(self, **values):
        async with self._session_factory() as session:
            statement = insert(Notifications).values(**values).returning(Notifications.id)
            result = await session.execute(statement)
            await session.commit()
            return result.scalar_one()

    async def list_for_user(self, user_id):
        async with self._session_factory() as session:
            statement = (
                select(Notifications)
                .where(Notifications.user_id == user_id)
                .order_by(Notifications.time_created.desc())
            )
            result = await session.execute(statement)
            return list(result.scalars())

    async def count_unread(self, user_id) -> int:
        async with self._session_factory() as session:
            statement = select(func.count()).select_from(Notifications).where(
                Notifications.user_id == user_id,
                Notifications.is_readed.is_(False),
            )
            result = await session.execute(statement)
            return result.scalar_one()

    async def mark_read(self, notification_id, user_id) -> bool:
        async with self._session_factory() as session:
            statement = (
                update(Notifications)
                .where(
                    Notifications.id == notification_id,
                    Notifications.user_id == user_id,
                    Notifications.is_readed.is_(False),
                )
                .values(is_readed=True)
                .returning(Notifications.id)
            )
            result = await session.execute(statement)
            changed = result.scalar_one_or_none() is not None
            await session.commit()
            return changed

    async def mark_all_read(self, user_id) -> int:
        async with self._session_factory() as session:
            statement = (
                update(Notifications)
                .where(
                    Notifications.user_id == user_id,
                    Notifications.is_readed.is_(False),
                )
                .values(is_readed=True)
                .returning(Notifications.id)
            )
            result = await session.execute(statement)
            changed = len(result.scalars().all())
            await session.commit()
            return changed
```

Add to `db/schemas/notifications.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field


class NotificationCountResponse(BaseModel):
    unread_count: int = Field(ge=0)


class NotificationCountEvent(NotificationCountResponse):
    type: Literal["notification_count"] = "notification_count"
```

Implement the manager around repository methods rather than raw SQLAlchemy predicates:

```python
class NotificationManager:
    def __init__(self, repo, realtime=None):
        self._repo = repo
        self._realtime = realtime

    async def unread_count(self, user_id) -> int:
        return await self._repo.count_unread(user_id)

    async def _publish_value(self, user_id, count: int) -> None:
        if self._realtime is None:
            return
        try:
            payload = NotificationCountEvent(unread_count=count).model_dump()
            await self._realtime.publish(str(user_id), payload)
        except Exception:
            return

    async def notify_count_changed(self, user_id) -> None:
        try:
            count = await self.unread_count(user_id)
        except Exception:
            return
        await self._publish_value(user_id, count)

    async def read_notification(self, user_id, notification_id) -> int:
        await self._repo.mark_read(notification_id, user_id)
        count = await self.unread_count(user_id)
        await self._publish_value(user_id, count)
        return count

    async def read_all_notifications(self, user_id) -> int:
        await self._repo.mark_all_read(user_id)
        count = await self.unread_count(user_id)
        await self._publish_value(user_id, count)
        return count
```

`create_notification()` must call repository `create(**notification_data.model_dump())`, then `notify_count_changed(notification_data.user_id)`, and return the created ID even if publication fails. `get_notifications_by_user()` delegates to `list_for_user(user.id)`.

Update imports in `dependecies/notifications.py` and `utils/celery_worker.py` from `manager.notifications.NotificationRepository` to `db.notification_repository.NotificationRepository`. Do not wire Redis into the scheduler until Task 2 provides the shared builder.

- [ ] **Step 6: Run focused tests and refactor only after GREEN**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_notification_repository.py tests/test_notifications.py -q
& ".\.venv\Scripts\python.exe" -m ruff check db/notification_repository.py db/schemas/notifications.py manager/notifications.py dependecies/notifications.py utils/celery_worker.py tests/test_notification_repository.py tests/test_notifications.py
```

Expected: PASS with no lint output.

- [ ] **Step 7: Commit the backend domain slice**

```powershell
git add db/notification_repository.py db/schemas/notifications.py manager/notifications.py dependecies/notifications.py utils/celery_worker.py tests/test_notification_repository.py tests/test_notifications.py
git commit -m "feat: add unread notification count domain"
```

---

### Task 2: Authenticated REST and Redis WebSocket Count Channel

**Files:**
- Create: `manager/notification_realtime.py`
- Create: `tests/test_notifications_api.py`
- Modify: `dependecies/notifications.py`
- Modify: `routes/notifications.py`
- Modify: `main.py`
- Modify: `tests/test_chat_realtime.py`

**Interfaces:**
- Consumes: Task 1 `NotificationManager` count/read methods and count schemas.
- Produces: `get_notification_realtime() -> NotificationRealtime` and `build_notification_manager() -> NotificationManager`.
- Produces: authenticated REST responses `NotificationCountResponse` and WebSocket event `NotificationCountEvent`.

- [ ] **Step 1: Write failing API tests for user scoping and WebSocket authentication**

Create `tests/test_notifications_api.py`. Override `current_user_dependency`, `get_notification_manager`, `get_notification_realtime`, `get_redis_strategy`, and `get_user_manager` with focused fakes. The tests exercise real FastAPI routing:

```python
def test_count_and_read_routes_pass_only_current_user_id():
    manager = StubNotificationManager(count=4)
    with notification_client(manager) as client:
        count = client.get("/api_v1/notifications/unread-count")
        one = client.post(f"/api_v1/notifications/read/{NOTIFICATION_ID}")
        all_items = client.post("/api_v1/notifications/read")

    assert count.json() == {"unread_count": 4}
    assert one.json() == {"unread_count": 3}
    assert all_items.json() == {"unread_count": 0}
    assert manager.calls == [
        ("count", USER_ID),
        ("read-one", USER_ID, NOTIFICATION_ID),
        ("read-all", USER_ID),
    ]


def test_notification_websocket_sends_initial_authoritative_count():
    app, realtime = websocket_app(valid_user=True, count=7)
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api_v1/notifications/ws?auth=valid-token"
        ) as websocket:
            assert websocket.receive_json() == {
                "type": "notification_count",
                "unread_count": 7,
            }
    assert realtime.connected_user_ids == [str(USER_ID)]


def test_notification_websocket_rejects_missing_and_invalid_tokens():
    for path in (
        "/api_v1/notifications/ws",
        "/api_v1/notifications/ws?auth=invalid-token",
    ):
        app, _ = websocket_app(valid_user=False, count=0)
        with TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect) as closed:
                with client.websocket_connect(path):
                    pass
        assert closed.value.code == 4401
```

Also assert the three REST endpoints return `401` without `current_user_dependency` override.

- [ ] **Step 2: Write the Redis prefix test before the specialization**

Extend `tests/test_chat_realtime.py`:

```python
async def test_notification_bridge_uses_isolated_user_channel():
    redis = FakeRedis()
    hub = RecordingHub()
    bridge = NotificationRealtime(redis, hub)

    await bridge.publish("user-1", {"type": "notification_count", "unread_count": 5})
    channel, payload = redis.published[-1]
    await bridge.dispatch_for_test(channel, payload)

    assert channel == "notifications:user:user-1"
    assert hub.broadcasts == [
        ("user-1", {"type": "notification_count", "unread_count": 5})
    ]
```

- [ ] **Step 3: Run the API/realtime tests and verify RED**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_notifications_api.py tests/test_chat_realtime.py -q
```

Expected: FAIL because the endpoints, realtime specialization, and dependencies do not exist.

- [ ] **Step 4: Implement the isolated realtime dependency and lifecycle**

Create `manager/notification_realtime.py`:

```python
from manager.chat_realtime import RedisChatRealtime


class NotificationRealtime(RedisChatRealtime):
    channel_prefix = "notifications:user:"
```

In `dependecies/notifications.py`, construct one cached hub and one shared manager builder:

```python
from functools import lru_cache

from db.notification_repository import NotificationRepository
from db.redis import redis
from manager.chat_realtime import LocalChatHub
from manager.notification_realtime import NotificationRealtime
from manager.notifications import NotificationManager


@lru_cache
def get_notification_realtime():
    return NotificationRealtime(redis, LocalChatHub())


def build_notification_manager():
    return NotificationManager(NotificationRepository(), get_notification_realtime())


async def get_notification_manager():
    yield build_notification_manager()
```

In `main.py`, resolve both cached realtime objects. Outside `app_env="test"`, start chat realtime first and notification realtime second; stop in reverse order in `finally`. No Redis listener starts during test app lifespan.

- [ ] **Step 5: Implement REST and WebSocket routes**

Add response models to the count/read routes and replace the read-all loop:

```python
@router.get("/unread-count", response_model=NotificationCountResponse)
async def unread_count(user=Depends(current_user_dependency), manager=Depends(get_notification_manager)):
    return NotificationCountResponse(unread_count=await manager.unread_count(user.id))


@router.post("/read/{id}", response_model=NotificationCountResponse)
async def read_one_notification(id: UUID, user=Depends(current_user_dependency), manager=Depends(get_notification_manager)):
    count = await manager.read_notification(user.id, id)
    return NotificationCountResponse(unread_count=count)


@router.post("/read", response_model=NotificationCountResponse)
async def read_all_notifications(user=Depends(current_user_dependency), manager=Depends(get_notification_manager)):
    count = await manager.read_all_notifications(user.id)
    return NotificationCountResponse(unread_count=count)
```

Add `WS /ws`: read the `auth` query parameter, validate it through `RedisStrategy.read_token`, close with `4401` on failure, connect only to `str(user.id)`, send the initial `NotificationCountEvent`, wait for inbound frames solely to detect disconnect, and always disconnect in `finally`. Catch only `WebSocketDisconnect`; do not accept a caller-provided room ID.

- [ ] **Step 6: Run focused and app-level tests**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_notifications_api.py tests/test_notifications.py tests/test_chat_realtime.py tests/test_app.py -q
& ".\.venv\Scripts\python.exe" -m ruff check main.py routes/notifications.py dependecies/notifications.py manager/notification_realtime.py tests/test_notifications_api.py tests/test_chat_realtime.py
```

Expected: PASS. Confirm `GET /api_v1/health` remains offline in the test app.

- [ ] **Step 7: Commit the backend transport slice**

```powershell
git add main.py routes/notifications.py dependecies/notifications.py manager/notification_realtime.py tests/test_notifications_api.py tests/test_chat_realtime.py
git commit -m "feat: stream unread notification counts"
```

---

### Task 3: Publish Counts from Every Notification Creation Path

**Files:**
- Modify: `manager/moysklad_order_chat.py`
- Modify: `dependecies/order_chat.py`
- Modify: `utils/celery_worker.py`
- Modify: `tests/test_moysklad_order_chat.py`

**Interfaces:**
- Consumes: Task 1 `NotificationManager.notify_count_changed(user_id)`.
- Consumes: Task 2 `build_notification_manager()` sharing the started notification realtime hub.
- Produces: post-commit publication for the direct `OrderChatRepository` notification insertion.

- [ ] **Step 1: Write the failing post-commit publication tests**

Extend `tests/test_moysklad_order_chat.py` with:

```python
class RecordingNotificationManager:
    def __init__(self):
        self.user_ids = []

    async def notify_count_changed(self, user_id):
        self.user_ids.append(user_id)


async def test_manager_reply_publishes_notification_count_after_transaction():
    notification_manager = RecordingNotificationManager()
    synchronizer, repository, moysklad, storage, canonical = inbound_fixture(
        notification_manager=notification_manager
    )
    moysklad.description = canonical + "\nПринято"

    await synchronizer.process_moysklad_update(inbound_event("count"))

    assert repository.notifications
    assert notification_manager.user_ids == [CLIENT_ID]


async def test_failed_manager_message_transaction_does_not_publish_count():
    notification_manager = RecordingNotificationManager()
    synchronizer, repository, moysklad, storage, canonical = inbound_fixture(
        notification_manager=notification_manager
    )
    moysklad.description = canonical + "\nПринято"

    async def fail(**values):
        raise RuntimeError("transaction failed")

    repository.create_manager_message_with_notification = fail
    with pytest.raises(RuntimeError, match="transaction failed"):
        await synchronizer.process_moysklad_update(inbound_event("failure"))

    assert notification_manager.user_ids == []
```

Change the fixture without affecting existing callers:

```python
def inbound_fixture(notification_manager=None):
    repository = InboundRepository()
    canonical = f"{CHAT_HEADER}\n\n[10.08.2026 12:00] Клиент: Где заказ?\n\n{REPLY_PROMPT}"
    repository.state.rendered_description_hash = description_hash(canonical)
    moysklad = InboundMoySklad(canonical)
    storage = InboundStorage()
    notification_options = {}
    if notification_manager is not None:
        notification_options["notification_manager"] = notification_manager
    synchronizer = MoySkladOrderChatSynchronizer(
        repository=repository,
        moysklad=moysklad,
        storage=storage,
        attachment_max_count=10,
        attachment_max_bytes=20 * 1024 * 1024,
        **notification_options,
    )
    return synchronizer, repository, moysklad, storage, canonical
```

This keeps existing tests green while the two new tests fail specifically on the missing constructor contract.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_order_chat.py -q
```

Expected: the publication assertion fails because the synchronizer has no notification manager.

- [ ] **Step 3: Inject and call the shared notification manager**

Add `notification_manager=None` to `MoySkladOrderChatSynchronizer.__init__` and store it. Immediately after `create_manager_message_with_notification()` returns successfully:

```python
if self._notification_manager is not None:
    await self._notification_manager.notify_count_changed(client.id)
```

Keep this call after the repository context has committed and outside its exception block. `notify_count_changed` is best effort, so Redis failure must not undo the stored message.

In `get_order_chat_runtime()`, pass `notification_manager=build_notification_manager()` to the synchronizer. In `utils/celery_worker.py`, replace direct construction with `notification_manager = build_notification_manager()` so scheduler-created notifications use the same cached realtime hub started by `main.py`.

- [ ] **Step 4: Run order-chat and notification regressions**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_order_chat.py tests/test_notifications.py tests/test_order_chat_webhook.py -q
& ".\.venv\Scripts\python.exe" -m ruff check manager/moysklad_order_chat.py dependecies/order_chat.py utils/celery_worker.py tests/test_moysklad_order_chat.py
```

Expected: PASS; replay still creates one notification, and failed storage/transaction flows publish none.

- [ ] **Step 5: Commit complete backend publication coverage**

```powershell
git add manager/moysklad_order_chat.py dependecies/order_chat.py utils/celery_worker.py tests/test_moysklad_order_chat.py
git commit -m "feat: publish order chat notification counts"
```

---

### Task 4: Frontend Count Provider, UI, and Read Reconciliation

**Files:**
- Create: `../pix_frontend_v2/src/features/notifications/notificationCount.ts`
- Create: `../pix_frontend_v2/src/features/notifications/notificationCount.test.ts`
- Create: `../pix_frontend_v2/src/features/notifications/NotificationCountProvider.tsx`
- Create: `../pix_frontend_v2/tests/notifications.spec.ts`
- Modify: `../pix_frontend_v2/src/routes/routes.tsx`
- Modify: `../pix_frontend_v2/src/app/dashboard/layout.tsx`
- Modify: `../pix_frontend_v2/src/components/navbar/navbar.tsx`
- Modify: `../pix_frontend_v2/src/app/dashboard/notifications/page.tsx`
- Modify: `../pix_frontend_v2/tests/mock-backend.mjs`

**Interfaces:**
- Consumes: backend count/read REST contracts and notification WebSocket event from Tasks 1–2.
- Produces: `useNotificationCount()` with `unreadCount`, `setAuthoritativeCount`, `decrementUnreadCount`, `clearUnreadCount`, and `refreshUnreadCount`.
- Produces: pure `parseNotificationCountMessage`, `decrementCount`, and `notificationRetryDelay` helpers.

- [ ] **Step 1: Write failing pure count tests**

Create `src/features/notifications/notificationCount.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import {
  decrementCount,
  notificationRetryDelay,
  parseNotificationCountMessage,
} from "./notificationCount";

describe("notification count helpers", () => {
  it("accepts only absolute non-negative integer count events", () => {
    expect(
      parseNotificationCountMessage(
        JSON.stringify({ type: "notification_count", unread_count: 5 }),
      ),
    ).toBe(5);
    expect(parseNotificationCountMessage("not-json")).toBeNull();
    expect(
      parseNotificationCountMessage(
        JSON.stringify({ type: "notification_count", unread_count: -1 }),
      ),
    ).toBeNull();
    expect(
      parseNotificationCountMessage(
        JSON.stringify({ type: "chat_message", unread_count: 5 }),
      ),
    ).toBeNull();
  });

  it("never decrements a known count below zero and preserves unknown", () => {
    expect(decrementCount(2)).toBe(1);
    expect(decrementCount(0)).toBe(0);
    expect(decrementCount(null)).toBeNull();
  });

  it("caps reconnect delay at thirty seconds", () => {
    expect(notificationRetryDelay(0)).toBe(1000);
    expect(notificationRetryDelay(5)).toBe(30000);
    expect(notificationRetryDelay(20)).toBe(30000);
  });
});
```

- [ ] **Step 2: Add deterministic browser fixtures and failing behavior tests**

In `tests/mock-backend.mjs`, add two unread MESSAGE notifications, reset them before each test, and implement:

- `GET /api_v1/notifications/` returning all fixture rows;
- `GET /api_v1/notifications/unread-count` returning the unread row count;
- `POST /api_v1/notifications/read/:id` marking only that row and returning the count;
- `POST /api_v1/notifications/read` marking all rows and returning zero;
- `POST /api_v1/test/reset-notifications` restoring fixtures;
- `POST /api_v1/test/fail-next-notification-read` making exactly the next read return HTTP 503 without changing fixtures.

Create `tests/notifications.spec.ts`. In `page.addInitScript`, replace `window.WebSocket` with a small fake that records instances, calls `onopen`, exposes `emit(payload)` and `closeFromServer(code)`, and never opens a network socket. Then assert real rendered behavior:

```typescript
test("shows and synchronizes unread counts in both locations", async ({ page }) => {
  await page.goto("/dashboard/notifications");
  await expect(page.getByLabel("Счётчик уведомлений в меню")).toHaveText("2");
  await expect(page.getByLabel("Счётчик уведомлений в заголовке")).toHaveText("2");

  await page.evaluate(() =>
    (window as any).__notificationSockets[0].emit({
      type: "notification_count",
      unread_count: 5,
    }),
  );

  await expect(page.getByLabel("Счётчик уведомлений в меню")).toHaveText("5");
  await expect(page.getByLabel("Счётчик уведомлений в заголовке")).toHaveText("5");
});
```

Add separate tests for hover followed by click sending only one read, “Прочитать всё” hiding the menu badge while the heading shows zero, read failure restoring the unread row/count, network close reconnecting after one second, and code `4401` creating no replacement socket.

- [ ] **Step 3: Run unit and browser tests and verify RED**

From `../pix_frontend_v2`, run:

```powershell
npm.cmd run test:unit -- src/features/notifications/notificationCount.test.ts
npm.cmd run test:e2e -- tests/notifications.spec.ts
```

Expected: unit import failure and browser 404/missing-label failures because the provider, API clients, fixtures, and UI do not exist.

- [ ] **Step 4: Implement typed API clients and pure helpers**

In `src/routes/routes.tsx`, add:

```typescript
export type NotificationCountResponse = { unread_count: number };

export function GetUnreadNotificationCountEndpoint() {
  return axios.get<NotificationCountResponse>(
    backendUrl("notifications/unread-count"),
    { headers: { Authorization: getCookie("token") } },
  );
}
```

Type both read endpoints and keep them free of toast wrappers:

```typescript
export function ReadOneNotificationEndpoint(id: string) {
  return axios.post<NotificationCountResponse>(
    backendUrl(`notifications/read/${id}`),
    {},
    { headers: { Authorization: getCookie("token") } },
  );
}

export function ReadAllNotificationsEndpoint() {
  return axios.post<NotificationCountResponse>(
    backendUrl("notifications/read"),
    {},
    { headers: { Authorization: getCookie("token") } },
  );
}
```

Implement the three pure helpers exactly as exercised by the Vitest literals.

- [ ] **Step 5: Implement one dashboard provider with bounded reconnects**

`NotificationCountProvider.tsx` must:

- initialize `unreadCount` to `null`;
- expose stable `useCallback` actions for authoritative set, decrement, clear, and REST refresh;
- derive the raw auth token by stripping one leading `Bearer ` from the cookie;
- call `GetUnreadNotificationCountEndpoint()` on mount and on window `focus`;
- connect to `backendWebSocketUrl("notifications/ws", { auth })`;
- apply only `parseNotificationCountMessage(event.data)` results;
- reset the attempt counter on `open`;
- reconnect with `notificationRetryDelay(attempt)` after ordinary close;
- never reconnect after close code `4401`;
- clear timers, listeners, and the socket on unmount;
- catch background failures without toast or an incorrect zero.

Export a hook that throws a clear error when called outside the provider. Refactor `dashboard/layout.tsx` so one root `NotificationCountProvider` wraps whichever existing dashboard shell branch is selected; do not create a separate provider inside each conditional return.

- [ ] **Step 6: Render both counts and make reads optimistic but recoverable**

In `navbar.tsx`, read the context once in `Navbar`, pass the value only to the notifications `NavItem`, and render an exact-number badge with `aria-label="Счётчик уведомлений в меню"`. Make the link/icon wrapper `relative`; preserve the existing selected styles. Do not render the badge when the value is `null` or zero.

In the notifications page:

- remove unused Navbar imports;
- show `unreadCount ?? "—"` in a heading badge with `aria-label="Счётчик уведомлений в заголовке"`;
- keep `pendingReadIds` in a ref so hover followed by click cannot duplicate a request before rerender;
- mark the local row read and decrement the provider before the request;
- on success call `setAuthoritativeCount(response.data.unread_count)`;
- on failure restore only rows that were unread before the operation and await `refreshUnreadCount()`;
- for “Прочитать всё”, snapshot unread IDs, mark them read, clear the count, then reconcile or restore;
- attach the same one-read function to `onMouseEnter` and `onClick` for every notification;
- preserve existing order navigation after starting the read request.

- [ ] **Step 7: Run focused frontend tests until GREEN**

Run:

```powershell
npm.cmd run test:unit -- src/features/notifications/notificationCount.test.ts
npm.cmd run test:e2e -- tests/notifications.spec.ts
npm.cmd run lint
```

Expected: PASS. The Playwright assertions exercise real Navbar/page output; only HTTP and WebSocket transport boundaries are faked.

- [ ] **Step 8: Commit the complete frontend slice**

From `../pix_frontend_v2`:

```powershell
git add src/features/notifications/notificationCount.ts src/features/notifications/notificationCount.test.ts src/features/notifications/NotificationCountProvider.tsx src/routes/routes.tsx src/app/dashboard/layout.tsx src/components/navbar/navbar.tsx src/app/dashboard/notifications/page.tsx tests/mock-backend.mjs tests/notifications.spec.ts
git commit -m "feat: show live unread notification counts"
```

---

### Task 5: Documentation, Static Coverage, and Cross-Repository Verification

**Files:**
- Modify: `scripts/check.ps1`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes: all backend/frontend deliverables from Tasks 1–4.
- Produces: repository checks that lint every active notification module and architecture docs matching the shipped contract.

- [ ] **Step 1: Extend the backend verification target list**

Add these paths to `$ruffTargets` in `scripts/check.ps1`:

```powershell
"db/notification_repository.py",
"db/schemas/notifications.py",
"dependecies/notifications.py",
"manager/notification_realtime.py",
"manager/notifications.py",
```

The existing `"tests"` target already covers all new tests.

- [ ] **Step 2: Update architecture documentation**

In `docs/ARCHITECTURE.md`, document:

- `GET /notifications/unread-count` and `/notifications/ws` in the Notifications row;
- PostgreSQL as the count source of truth;
- Redis per-user fan-out across workers/tabs;
- absolute count delivery after create/read operations;
- the dashboard provider and the order-chat post-commit publication boundary.

- [ ] **Step 3: Run final backend verification after the final backend edit**

From `pix_backend`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
& ".\.venv\Scripts\python.exe" -c "import main; print(main.app.title)"
```

Expected: Ruff and all pytest tests pass; the fresh import prints `Pix Logistic API` without external HTTP.

- [ ] **Step 4: Run final frontend verification after the final frontend edit**

From `../pix_frontend_v2`:

```powershell
npm.cmd run check
```

Expected: lint, API URL check, Vitest, production build, and all Playwright tests pass.

- [ ] **Step 5: Review the complete diffs and migration boundary**

Run:

```powershell
git diff --check HEAD~3..HEAD
git status --short
git -c safe.directory=C:/Users/zenja/IdeaProjects/pix_frontend_v2 -C ..\pix_frontend_v2 diff --check HEAD~1..HEAD
git -c safe.directory=C:/Users/zenja/IdeaProjects/pix_frontend_v2 -C ..\pix_frontend_v2 status --short
```

Expected: no whitespace errors, no Alembic revision, no secret/config file, and only pre-existing unrelated generated-file changes remain unstaged.

- [ ] **Step 6: Commit backend docs/check coverage**

```powershell
git add scripts/check.ps1 docs/ARCHITECTURE.md docs/superpowers/plans/2026-08-11-unread-notification-count.md
git commit -m "docs: document unread notification realtime flow"
```
