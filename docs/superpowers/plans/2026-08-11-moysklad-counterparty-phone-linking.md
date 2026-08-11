# MoySklad Counterparty Phone Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse exactly one pre-created MoySklad counterparty with the same supported normalized phone number after email verification, and create a new counterparty when there are zero or multiple matches.

**Architecture:** A pure phone helper generates a canonical comparison key and common exact search representations. `CounterpartyRepository` performs one encoded MoySklad collection request, `CounterpartyManager` validates candidates and owns the match-or-create decision, and `UserManager.on_after_verify()` persists the resolution before attempting its Telegram side notification.

**Tech Stack:** Python 3.11, FastAPI Users 12, Pydantic 2, `requests`, pytest/pytest-asyncio, Ruff, PowerShell verification scripts.

## Global Constraints

- Linking remains in `UserManager.on_after_verify()`; registration itself must not contact MoySklad.
- An already linked local user is not searched or created again.
- Treat the documented common `+7`, `7`, and `8` representations as equivalent, then normalize every returned candidate before accepting it.
- Reuse a counterparty only when exactly one normalized match exists; create a new counterparty for zero or multiple matches.
- Never update the name, email, description, phone, or other fields of a matched counterparty.
- A lookup failure or malformed response must raise and must not fall back to creation.
- Persist the local `moysklad_counterparty_id` and `meta` before Telegram; Telegram failure must not undo or fail a persisted link.
- All tests use fakes or patched HTTP and must not contact production MoySklad, Telegram, email, or other services.
- Do not add a migration, change public API schemas, or modify the frontend.
- Run `scripts/check.ps1` after the final edit; no frontend check is required because the API contract is unchanged.

## File Structure

- Create `manager/phone_numbers.py` — pure normalization and exact search-variant generation.
- Modify `manager/moysklad.py` — encoded counterparty lookup, resolution result type, and match-or-create policy.
- Modify `manager/users.py` — consume the resolution, persist first, and isolate the Telegram side effect.
- Create `tests/test_moysklad_user_linking.py` — helper, repository, manager, and verification-hook coverage.
- Modify `scripts/check.ps1` — include the new manager module in the explicit Ruff target list.
- Modify `docs/ARCHITECTURE.md` — document the post-verification counterparty resolution flow.

---

### Task 1: Normalize phones and generate supported search representations

**Files:**
- Create: `manager/phone_numbers.py`
- Create: `tests/test_moysklad_user_linking.py`

**Interfaces:**
- Consumes: a registration or MoySklad phone string.
- Produces: `normalize_phone(phone: str) -> str` and `phone_search_variants(phone: str) -> tuple[str, ...]`.

- [ ] **Step 1: Write the failing helper tests**

Create `tests/test_moysklad_user_linking.py` with:

```python
import pytest

from manager.phone_numbers import normalize_phone, phone_search_variants


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("+7 (999) 123-45-67", "79991234567"),
        ("79991234567", "79991234567"),
        ("8 999 123 45 67", "79991234567"),
        ("9991234567", "79991234567"),
        ("+48 123 456 789", "48123456789"),
        ("extension-only", ""),
    ],
)
def test_normalize_phone(value, expected):
    assert normalize_phone(value) == expected


def test_phone_search_variants_cover_common_russian_formats_without_duplicates():
    assert phone_search_variants("+7 (999) 123-45-67") == (
        "+7 (999) 123-45-67",
        "+7 999 123-45-67",
        "+7 999 123 45 67",
        "+79991234567",
        "79991234567",
        "8 (999) 123-45-67",
        "8 999 123-45-67",
        "89991234567",
    )


def test_phone_search_variants_keep_original_and_digits_for_other_numbers():
    assert phone_search_variants("+48 123 456 789") == (
        "+48 123 456 789",
        "48123456789",
    )
    assert phone_search_variants("not-a-phone") == ("not-a-phone",)
    assert phone_search_variants("   ") == ()
```

- [ ] **Step 2: Run the helper tests and verify RED**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_user_linking.py -q
```

Expected: test collection fails with `ModuleNotFoundError: No module named 'manager.phone_numbers'` because the helper does not exist yet.

- [ ] **Step 3: Implement the minimal pure helper**

Create `manager/phone_numbers.py`:

```python
def normalize_phone(phone: str) -> str:
    digits = "".join(character for character in phone if character.isdigit())
    if len(digits) == 10:
        return f"7{digits}"
    if len(digits) == 11 and digits[0] in {"7", "8"}:
        return f"7{digits[1:]}"
    return digits


def phone_search_variants(phone: str) -> tuple[str, ...]:
    original = phone.strip()
    normalized = normalize_phone(original)
    if not original:
        return ()

    values = [original]
    if len(normalized) == 11 and normalized.startswith("7"):
        area = normalized[1:4]
        prefix = normalized[4:7]
        first_pair = normalized[7:9]
        second_pair = normalized[9:11]
        values.extend(
            [
                f"+7 ({area}) {prefix}-{first_pair}-{second_pair}",
                f"+7 {area} {prefix}-{first_pair}-{second_pair}",
                f"+7 {area} {prefix} {first_pair} {second_pair}",
                f"+7{normalized[1:]}",
                normalized,
                f"8 ({area}) {prefix}-{first_pair}-{second_pair}",
                f"8 {area} {prefix}-{first_pair}-{second_pair}",
                f"8{normalized[1:]}",
            ]
        )
    elif normalized:
        values.append(normalized)

    return tuple(dict.fromkeys(values))
```

- [ ] **Step 4: Run the helper tests and verify GREEN**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_user_linking.py -q
& ".\.venv\Scripts\python.exe" -m ruff check manager/phone_numbers.py tests/test_moysklad_user_linking.py
```

Expected: helper tests pass and Ruff exits with code 0.

- [ ] **Step 5: Commit the helper cycle**

```powershell
git add manager/phone_numbers.py tests/test_moysklad_user_linking.py
git commit -m "feat: normalize MoySklad counterparty phones"
```

---

### Task 2: Search MoySklad and resolve one match versus creation

**Files:**
- Modify: `manager/moysklad.py:1-79`
- Modify: `tests/test_moysklad_user_linking.py`

**Interfaces:**
- Consumes: Task 1's `normalize_phone(phone: str) -> str` and `phone_search_variants(phone: str) -> tuple[str, ...]`.
- Produces: `CounterpartyRepository.find_by_phone_candidates(phones: tuple[str, ...]) -> list[dict]`, immutable `CounterpartyResolution(counterparty: dict, created: bool)`, and `CounterpartyManager.resolve_user_counterparty(counterparty_data: CounterpartyCreate) -> CounterpartyResolution`.

- [ ] **Step 1: Add failing repository and manager tests**

Replace the import block in `tests/test_moysklad_user_linking.py` with:

```python
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from config import Settings
from db.schemas.moysklad import CounterpartyCreate
from manager.moysklad import CounterpartyManager, CounterpartyRepository
from manager.phone_numbers import normalize_phone, phone_search_variants
```

Append these fakes and tests:

```python
class FakeMoySkladResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


def moysklad_settings():
    return Settings(
        _env_file=None,
        app_env="test",
        moysklad_login="login",
        moysklad_password="password",
    )


def counterparty(index, phone):
    counterparty_id = f"00000000-0000-0000-0000-{index:012d}"
    return {
        "id": counterparty_id,
        "phone": phone,
        "meta": {
            "uuidHref": (
                "https://online.moysklad.ru/app/#counterparty/edit?id="
                f"{counterparty_id}"
            )
        },
    }


def counterparty_payload():
    return CounterpartyCreate(
        name="Иван Клиент #7",
        description="Информация с сайта pixlogistics:\nid = local-user",
        email="ivan@example.com",
        phone="+7 (999) 123-45-67",
    )


@pytest.mark.asyncio
async def test_counterparty_repository_encodes_phone_filter_as_query_params(
    monkeypatch,
):
    captured = {}

    def get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeMoySkladResponse({"rows": []})

    monkeypatch.setattr(requests, "get", get)
    repository = CounterpartyRepository(moysklad_settings())

    rows = await repository.find_by_phone_candidates(
        ("+7 (999) 123-45-67", "79991234567")
    )

    assert rows == []
    assert captured["url"].endswith("/entity/counterparty")
    assert captured["params"] == {
        "filter": "phone=+7 (999) 123-45-67;phone=79991234567",
        "limit": 1000,
    }
    prepared = requests.Request(
        "GET", captured["url"], params=captured["params"]
    ).prepare()
    assert "%2B7+%28999%29+123-45-67" in prepared.url
    assert parse_qs(urlparse(prepared.url).query)["filter"] == [
        "phone=+7 (999) 123-45-67;phone=79991234567"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"rows": "invalid"}, {"rows": [None]}],
)
async def test_counterparty_repository_rejects_malformed_collections(
    monkeypatch,
    payload,
):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: FakeMoySkladResponse(payload),
    )
    repository = CounterpartyRepository(moysklad_settings())

    with pytest.raises(ValueError, match="counterparty collection"):
        await repository.find_by_phone_candidates(("79991234567",))


@pytest.mark.asyncio
async def test_counterparty_repository_propagates_http_errors(monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: FakeMoySkladResponse(
            {"rows": []}, status_code=503
        ),
    )
    repository = CounterpartyRepository(moysklad_settings())

    with pytest.raises(requests.HTTPError):
        await repository.find_by_phone_candidates(("79991234567",))


class StubCounterpartyRepository:
    def __init__(self, rows=None, lookup_error=None):
        self.rows = rows or []
        self.lookup_error = lookup_error
        self.lookup_calls = []
        self.created = []
        self.created_result = counterparty(99, "+7 (999) 123-45-67")

    async def find_by_phone_candidates(self, phones):
        self.lookup_calls.append(phones)
        if self.lookup_error:
            raise self.lookup_error
        return self.rows

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return self.created_result


@pytest.mark.asyncio
async def test_counterparty_manager_reuses_one_normalized_match():
    expected = counterparty(1, "8 999 123 45 67")
    repository = StubCounterpartyRepository(
        rows=[expected, counterparty(2, "+7 (921) 000-00-00")]
    )
    manager = CounterpartyManager(repository)

    resolution = await manager.resolve_user_counterparty(counterparty_payload())

    assert resolution.counterparty == expected
    assert resolution.created is False
    assert repository.created == []
    assert "+7 (999) 123-45-67" in repository.lookup_calls[0]
    assert "89991234567" in repository.lookup_calls[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        [],
        [
            counterparty(1, "+7 (999) 123-45-67"),
            counterparty(2, "89991234567"),
        ],
    ],
)
async def test_counterparty_manager_creates_for_zero_or_multiple_matches(rows):
    repository = StubCounterpartyRepository(rows=rows)
    manager = CounterpartyManager(repository)

    resolution = await manager.resolve_user_counterparty(counterparty_payload())

    assert resolution.counterparty == repository.created_result
    assert resolution.created is True
    assert repository.created == [counterparty_payload().model_dump()]


@pytest.mark.asyncio
async def test_counterparty_manager_rejects_malformed_single_match():
    repository = StubCounterpartyRepository(
        rows=[{"id": "", "phone": "89991234567", "meta": {}}]
    )
    manager = CounterpartyManager(repository)

    with pytest.raises(ValueError, match="counterparty match"):
        await manager.resolve_user_counterparty(counterparty_payload())

    assert repository.created == []


@pytest.mark.asyncio
async def test_counterparty_manager_does_not_create_after_lookup_failure():
    repository = StubCounterpartyRepository(
        lookup_error=requests.Timeout("lookup timed out")
    )
    manager = CounterpartyManager(repository)

    with pytest.raises(requests.Timeout, match="lookup timed out"):
        await manager.resolve_user_counterparty(counterparty_payload())

    assert repository.created == []
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_user_linking.py -q
```

Expected: helper tests stay green; new tests fail because `find_by_phone_candidates` and `resolve_user_counterparty` do not exist.

- [ ] **Step 3: Implement the encoded repository lookup**

At the top of `manager/moysklad.py`, add the standard-library and third-party imports before local imports:

```python
from dataclasses import dataclass

import requests
```

Extend `CounterpartyRepository`:

```python
class CounterpartyRepository(MoySkladRepository):
    model = "entity/counterparty"

    async def find_by_phone_candidates(
        self,
        phones: tuple[str, ...],
    ) -> list[dict]:
        if not phones:
            return []
        response = requests.get(
            f"{self.base_url}{self.model}",
            headers=self._headers(),
            params={
                "filter": ";".join(f"phone={phone}" for phone in phones),
                "limit": 1000,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("invalid MoySklad counterparty collection")
        rows = payload.get("rows")
        if not isinstance(rows, list) or not all(
            isinstance(row, dict) for row in rows
        ):
            raise ValueError("invalid MoySklad counterparty collection")
        return rows
```

- [ ] **Step 4: Implement the match-or-create policy**

Import Task 1's helper in `manager/moysklad.py`:

```python
from manager.phone_numbers import normalize_phone, phone_search_variants
```

Add the immutable result immediately above `CounterpartyManager` and extend the manager:

```python
@dataclass(frozen=True)
class CounterpartyResolution:
    counterparty: dict
    created: bool


class CounterpartyManager:
    def __init__(self, repo: CounterpartyRepository):
        self.__repo = repo

    async def create_user_counterparty(
        self,
        counterparty_data: moysklad.CounterpartyCreate,
    ):
        counterparty_dict = counterparty_data.model_dump()
        return await self.__repo.create(**counterparty_dict)

    async def resolve_user_counterparty(
        self,
        counterparty_data: moysklad.CounterpartyCreate,
    ) -> CounterpartyResolution:
        normalized_phone = normalize_phone(counterparty_data.phone)
        candidates = await self.__repo.find_by_phone_candidates(
            phone_search_variants(counterparty_data.phone)
        )

        matches = []
        for candidate in candidates:
            phone = candidate.get("phone")
            if not isinstance(phone, str):
                raise ValueError("invalid MoySklad counterparty candidate")
            if normalize_phone(phone) == normalized_phone:
                matches.append(candidate)

        if len(matches) == 1:
            match = matches[0]
            meta = match.get("meta")
            if (
                not isinstance(match.get("id"), str)
                or not match["id"]
                or not isinstance(meta, dict)
                or not isinstance(meta.get("uuidHref"), str)
                or not meta["uuidHref"]
            ):
                raise ValueError("invalid MoySklad counterparty match")
            return CounterpartyResolution(match, created=False)

        created = await self.create_user_counterparty(counterparty_data)
        return CounterpartyResolution(created, created=True)
```

Do not modify `MoySkladRepository.read_all()`; other managers currently pass pagination and expansion fragments through its legacy filter argument.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_user_linking.py -q
& ".\.venv\Scripts\python.exe" -m ruff check manager/moysklad.py manager/phone_numbers.py tests/test_moysklad_user_linking.py
```

Expected: repository and manager tests pass; Ruff exits with code 0.

- [ ] **Step 6: Commit the repository and policy cycle**

```powershell
git add manager/moysklad.py tests/test_moysklad_user_linking.py
git commit -m "feat: resolve MoySklad counterparties by phone"
```

---

### Task 3: Integrate resolution into email verification and isolate Telegram

**Files:**
- Modify: `manager/users.py:1-67`
- Modify: `tests/test_moysklad_user_linking.py`
- Modify: `scripts/check.ps1`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes: Task 2's `CounterpartyManager.resolve_user_counterparty(counterparty_data: CounterpartyCreate) -> CounterpartyResolution`.
- Produces: post-verification persistence of the resolved `id/meta`, created-versus-linked Telegram text, and logged non-fatal notification failures.

- [ ] **Step 1: Add failing verification-hook tests**

Replace the import block in `tests/test_moysklad_user_linking.py` with:

```python
import logging
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import requests

import manager.users as users_module
from config import Settings
from db.schemas.moysklad import CounterpartyCreate
from manager.moysklad import (
    CounterpartyManager,
    CounterpartyRepository,
    CounterpartyResolution,
)
from manager.phone_numbers import normalize_phone, phone_search_variants
from manager.users import UserManager
```

Append:

```python
def verified_user(**overrides):
    values = {
        "id": "10000000-0000-0000-0000-000000000001",
        "email": "ivan@example.com",
        "first_name": "Иван",
        "phone_number": "+7 (999) 123-45-67",
        "name_id": 7,
        "moysklad_counterparty_id": None,
        "moysklad_counterparty_meta": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def user_manager():
    settings = Settings(
        _env_file=None,
        app_env="test",
        verification_token_secret="verification-secret",
        reset_password_token_secret="reset-secret",
    )
    return UserManager(object(), settings)


class StubResolutionManager:
    def __init__(self, resolution):
        self.resolution = resolution
        self.payloads = []

    async def resolve_user_counterparty(self, payload):
        self.payloads.append(payload)
        return self.resolution


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("created", "expected_text"),
    [
        (False, "связан с существующим контрагентом"),
        (True, "Новый пользователь на сайте"),
    ],
)
async def test_after_verify_persists_resolution_before_notification(
    monkeypatch,
    created,
    expected_text,
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

    async def send_group_message(message):
        events.append(("telegram", message))

    monkeypatch.setattr(
        users_module.moysklad,
        "get_counterparty_manager",
        get_counterparty_manager,
    )
    monkeypatch.setattr(manager, "update", update)
    monkeypatch.setattr(
        users_module.telegram_sender,
        "send_group_message",
        send_group_message,
    )

    await manager.on_after_verify(user)

    assert [event[0] for event in events] == ["update", "telegram"]
    update_data = events[0][1]
    assert str(update_data.moysklad_counterparty_id) == external["id"]
    assert update_data.moysklad_counterparty_meta == external["meta"]
    assert events[1][1].startswith(
        f'<a href="{external["meta"]["uuidHref"]}">'
    )
    assert expected_text in events[1][1]
    assert resolution_manager.payloads[0].phone == user.phone_number


@pytest.mark.asyncio
async def test_after_verify_logs_telegram_failure_after_persisting(
    monkeypatch,
    caplog,
):
    external = counterparty(1, "89991234567")
    resolution_manager = StubResolutionManager(
        CounterpartyResolution(external, created=False)
    )
    manager = user_manager()
    events = []

    async def get_counterparty_manager():
        return resolution_manager

    async def update(data, current_user, request=None):
        events.append("update")
        return current_user

    async def fail_notification(message):
        events.append("telegram")
        raise RuntimeError("telegram unavailable")

    monkeypatch.setattr(
        users_module.moysklad,
        "get_counterparty_manager",
        get_counterparty_manager,
    )
    monkeypatch.setattr(manager, "update", update)
    monkeypatch.setattr(
        users_module.telegram_sender,
        "send_group_message",
        fail_notification,
    )

    with caplog.at_level(logging.ERROR):
        await manager.on_after_verify(verified_user())

    assert events == ["update", "telegram"]
    assert "MoySklad user verification notification" in caplog.text


@pytest.mark.asyncio
async def test_after_verify_keeps_existing_link_without_lookup_or_update(
    monkeypatch,
):
    manager = user_manager()
    messages = []

    async def fail_lookup():
        raise AssertionError("linked user triggered MoySklad lookup")

    async def fail_update(*args, **kwargs):
        raise AssertionError("linked user was updated")

    async def send_group_message(message):
        messages.append(message)

    monkeypatch.setattr(
        users_module.moysklad,
        "get_counterparty_manager",
        fail_lookup,
    )
    monkeypatch.setattr(manager, "update", fail_update)
    monkeypatch.setattr(
        users_module.telegram_sender,
        "send_group_message",
        send_group_message,
    )

    await manager.on_after_verify(
        verified_user(
            moysklad_counterparty_id="00000000-0000-0000-0000-000000000001",
            moysklad_counterparty_meta={
                "uuidHref": "https://online.moysklad.ru/existing"
            },
        )
    )

    assert len(messages) == 1
    assert "Пользователь подтвердил почту" in messages[0]
```

- [ ] **Step 2: Run the hook tests and verify RED**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_user_linking.py -q
```

Expected: the new unlinked-user tests fail because the hook still calls `create_user_counterparty()`, sends Telegram before persistence, and lets Telegram errors propagate. The existing-link test passes.

- [ ] **Step 3: Implement persistence-first resolution and notification isolation**

Add `import logging` before the existing standard-library imports in
`manager/users.py`:

```python
import logging
```

After the final local import, add the module logger:

```python
logger = logging.getLogger(__name__)
```

Replace the unlinked-user portion of `UserManager.on_after_verify()` after construction of `counterparty_data`:

```python
        resolution = await counterparty_manager.resolve_user_counterparty(
            counterparty_data
        )
        counterparty = resolution.counterparty
        user_update_data = UserUpdate(
            moysklad_counterparty_id=counterparty["id"],
            moysklad_counterparty_meta=counterparty["meta"],
        )
        await self.update(user_update_data, user, request=request)

        notification_title = (
            "Новый пользователь на сайте!"
            if resolution.created
            else "Пользователь связан с существующим контрагентом!"
        )
        try:
            await telegram_sender.send_group_message(
                f'<a href="{counterparty["meta"]["uuidHref"]}">'
                f"{notification_title}</a>\n"
                f"{user.first_name} Клиент #{user.name_id}"
            )
        except Exception:
            logger.exception(
                "Failed to send MoySklad user verification notification"
            )
```

Keep the existing early-return branch for `user.moysklad_counterparty_id` unchanged. Do not catch lookup, creation, or local update errors.

- [ ] **Step 4: Run hook and manager tests and verify GREEN**

Run:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_moysklad_user_linking.py -q
& ".\.venv\Scripts\python.exe" -m ruff check manager/users.py manager/moysklad.py manager/phone_numbers.py tests/test_moysklad_user_linking.py
```

Expected: all focused tests pass and Ruff exits with code 0.

- [ ] **Step 5: Register the new module in backend checks**

Add the new module next to the other manager targets in `scripts/check.ps1`:

```powershell
    "manager/moysklad.py",
    "manager/phone_numbers.py",
    "manager/moysklad_order_chat.py",
```

- [ ] **Step 6: Document the user-linking flow**

In `docs/ARCHITECTURE.md`, immediately after the paragraph about verification/reset code mappings, add:

```markdown
After email verification, an unlinked user searches MoySklad counterparties by
common exact representations of the normalized phone number. The backend
normalizes returned candidates again: one match is linked without modifying the
counterparty, while zero or multiple matches create a new counterparty. Lookup
errors never fall back to creation. The local `id` and `meta` are persisted
before the Telegram side notification is attempted.
```

- [ ] **Step 7: Run the complete required verification**

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
git diff --check
```

Expected: Ruff exits with code 0, the complete backend pytest suite reports zero failures, and `git diff --check` prints no errors. Do not run Alembic or contact live MoySklad/Telegram services.

- [ ] **Step 8: Review scope and commit the completed feature**

Inspect only the intended source diff while leaving existing `.pyc` worktree changes untouched:

```powershell
git diff -- manager/phone_numbers.py manager/moysklad.py manager/users.py scripts/check.ps1 tests/test_moysklad_user_linking.py docs/ARCHITECTURE.md
git status --short
```

Then stage only the feature files and commit:

```powershell
git add manager/phone_numbers.py manager/moysklad.py manager/users.py scripts/check.ps1 tests/test_moysklad_user_linking.py docs/ARCHITECTURE.md
git commit -m "feat: link MoySklad counterparties by phone"
```
