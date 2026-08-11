from urllib.parse import parse_qs, urlparse

import pytest
import requests

from config import Settings
from db.schemas.moysklad import CounterpartyCreate
from manager.moysklad import CounterpartyManager, CounterpartyRepository
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
