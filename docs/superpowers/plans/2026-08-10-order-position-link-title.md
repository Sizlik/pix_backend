# Order Position Link Title Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display the HTML `<title>` of public links in the `Позиция` column on both order screens while preserving a safe, clickable raw-URL fallback.

**Architecture:** Add an authenticated FastAPI link-preview endpoint whose repository fetches HTML through an address-pinning resolver that rejects non-public destinations and revalidates redirects. Add one shared React position renderer that tokenizes text, deduplicates title requests, and is used by both existing AG Grid cell renderers.

**Tech Stack:** Python 3.11, FastAPI 0.104, Pydantic 2, aiohttp 3.9, BeautifulSoup 4, pytest; Next.js 14, React 18, TypeScript, Axios, AG Grid 31, Vitest 3, Playwright.

## Global Constraints

- Support the new-order table and the existing-order table.
- Support arbitrary public absolute HTTP and HTTPS URLs; never connect to loopback, private, link-local, multicast, reserved, unspecified, or otherwise non-global addresses.
- Reject credential-bearing URLs and revalidate every redirect target through the same public-address policy.
- Pin connections to the DNS answers that passed validation so DNS rebinding cannot create a validation/connection gap.
- Do not execute remote JavaScript or persist titles in PostgreSQL, MoySklad, order payloads, or browser storage.
- Open links with `target="_blank"` and `rel="noopener noreferrer"`.
- Keep the raw URL visible and clickable when lookup fails; do not show a toast for title lookup.
- Limit redirects to 3, total request time to 5 seconds, HTML to 1,048,576 bytes, and the normalized title to 300 characters.
- Tests and project checks must use fakes/local services and must not contact arbitrary third-party or production services.
- Keep backend logic in the route → dependency → manager → repository layers and frontend HTTP calls in `src/routes/routes.tsx`.
- Use npm and the committed `package-lock.json` only in the frontend.

## File Structure

Backend repository (`pix_backend`):

- Create `db/schemas/link_preview.py` for request/response models.
- Create `manager/link_preview.py` for title extraction and the manager/source interface.
- Create `db/link_preview_repository.py` for SSRF-safe HTTP retrieval.
- Create `dependecies/link_preview.py` for manager construction.
- Create `routes/link_preview.py` for the authenticated transport contract.
- Modify `errors.py` to add a sanitized link validation exception.
- Modify `main.py` to mount the route.
- Modify `scripts/check.ps1` to lint every new Python module.
- Create `tests/test_link_preview.py` for domain, network-safety, and endpoint tests.

Frontend repository (`../pix_frontend_v2`):

- Create `vitest.config.ts` and modify `package.json`/`package-lock.json` for focused unit tests.
- Create `src/components/positionLink/positionText.ts` and `positionText.test.ts` for pure URL tokenization.
- Create `src/components/positionLink/PositionText.tsx` for asynchronous title rendering and request deduplication.
- Modify `src/routes/routes.tsx` to add the typed, toast-free title request.
- Modify `src/app/dashboard/neworder/page.tsx` and `src/app/dashboard/orders/[id]/page.tsx` to use the shared renderer.
- Create `tests/mock-backend.mjs` and `tests/position-link-title.spec.ts` for deterministic browser coverage.
- Modify `playwright.config.ts` to run the browser suite against the local mock backend.

---

### Task 1: Backend title extraction and manager contract

**Files:**
- Create: `db/schemas/link_preview.py`
- Create: `manager/link_preview.py`
- Create: `tests/test_link_preview.py`

**Interfaces:**
- Produces: `LinkTitleRequest(url: AnyHttpUrl)` and `LinkTitleResponse(title: str | None)`.
- Produces: `extract_title(html: bytes) -> str | None` and `LinkPreviewManager.get_title(url: str) -> str | None`.
- Consumes: an injected `LinkPreviewSource.fetch_html(url: str) -> bytes | None` implementation supplied in Task 2.

- [ ] **Step 1: Write the failing extraction and manager tests**

Create `tests/test_link_preview.py` with the first behavior tests:

```python
import pytest

from manager.link_preview import MAX_TITLE_LENGTH, LinkPreviewManager, extract_title


class StubLinkPreviewSource:
    def __init__(self, html: bytes | None):
        self.html = html
        self.urls: list[str] = []

    async def fetch_html(self, url: str) -> bytes | None:
        self.urls.append(url)
        return self.html


def test_extract_title_decodes_entities_and_collapses_whitespace():
    html = b"<html><head><title>  Example &amp;\n  Product  </title></head></html>"

    assert extract_title(html) == "Example & Product"


def test_extract_title_honors_html_character_encoding():
    html = '<meta charset="windows-1251"><title>Товар</title>'.encode("windows-1251")

    assert extract_title(html) == "Товар"


def test_extract_title_returns_none_when_title_is_missing_or_blank():
    assert extract_title(b"<html><body>Product</body></html>") is None
    assert extract_title(b"<title>   </title>") is None


def test_extract_title_limits_remote_text():
    assert extract_title(f"<title>{'x' * 400}</title>".encode()) == "x" * MAX_TITLE_LENGTH


@pytest.mark.asyncio
async def test_manager_returns_extracted_title_from_source():
    source = StubLinkPreviewSource(b"<title>Example product</title>")
    manager = LinkPreviewManager(source)

    assert await manager.get_title("https://example.com/item") == "Example product"
    assert source.urls == ["https://example.com/item"]


@pytest.mark.asyncio
async def test_manager_keeps_null_fallback_for_unavailable_html():
    manager = LinkPreviewManager(StubLinkPreviewSource(None))

    assert await manager.get_title("https://example.com/item") is None
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run from `pix_backend`:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_link_preview.py -v
```

Expected: collection fails because `manager.link_preview` does not exist. Confirm the failure is the missing production module, not test syntax.

- [ ] **Step 3: Add the typed request/response models**

Create `db/schemas/link_preview.py`:

```python
from pydantic import AnyHttpUrl, BaseModel, field_validator


class LinkTitleRequest(BaseModel):
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def reject_embedded_credentials(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username is not None or value.password is not None:
            raise ValueError("URL credentials are not allowed")
        return value


class LinkTitleResponse(BaseModel):
    title: str | None
```

- [ ] **Step 4: Implement title normalization and manager delegation**

Create `manager/link_preview.py`:

```python
from typing import Protocol

from bs4 import BeautifulSoup

MAX_TITLE_LENGTH = 300


class LinkPreviewSource(Protocol):
    async def fetch_html(self, url: str) -> bytes | None: ...


def extract_title(html: bytes) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title is None:
        return None

    normalized = " ".join(soup.title.get_text(" ", strip=True).split())
    if not normalized:
        return None
    return normalized[:MAX_TITLE_LENGTH]


class LinkPreviewManager:
    def __init__(self, source: LinkPreviewSource):
        self._source = source

    async def get_title(self, url: str) -> str | None:
        html = await self._source.fetch_html(url)
        return extract_title(html) if html is not None else None
```

- [ ] **Step 5: Run the focused tests and verify GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_link_preview.py -v
```

Expected: 6 tests PASS with no warnings caused by the new code.

- [ ] **Step 6: Commit the extraction boundary**

```powershell
git add db/schemas/link_preview.py manager/link_preview.py tests/test_link_preview.py
git commit -m "feat: extract link preview titles"
```

---

### Task 2: SSRF-safe HTML repository

**Files:**
- Create: `db/link_preview_repository.py`
- Modify: `errors.py`
- Modify: `tests/test_link_preview.py`

**Interfaces:**
- Produces: `LinkPreviewRepository.fetch_html(url: str) -> bytes | None` implementing Task 1's `LinkPreviewSource`.
- Produces: `PublicOnlyResolver.resolve(host, port, family)`, which caches validated DNS records and returns those same records to aiohttp's connector.
- Produces: `LinkPreviewValidationError`, always safe to map to a generic 422 response.

- [ ] **Step 1: Add failing URL and resolver safety tests**

Append to `tests/test_link_preview.py`:

```python
import asyncio
import socket

from aiohttp.abc import AbstractResolver

from db.link_preview_repository import PublicOnlyResolver, validate_url_target
from errors import LinkPreviewValidationError


class StubResolver(AbstractResolver):
    def __init__(self, addresses: dict[str, list[str]]):
        self.addresses = addresses
        self.calls: list[str] = []

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        self.calls.append(host)
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
            for address in self.addresses[host]
        ]

    async def close(self) -> None:
        return None


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "https://user:password@example.com/item",
        "http://0.0.0.0/",
        "http://10.0.0.4/",
        "http://127.0.0.1/admin",
        "http://169.254.1.1/",
        "http://[::1]/admin",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://224.0.0.1/",
        "http://[ff02::1]/",
        "http://192.0.2.1/",
        "http://[2001:db8::1]/",
    ],
)
def test_validate_url_target_rejects_non_web_credentials_and_private_literals(url):
    with pytest.raises(LinkPreviewValidationError, match="URL is not allowed"):
        validate_url_target(url)


@pytest.mark.asyncio
async def test_public_only_resolver_rejects_when_any_dns_answer_is_not_global():
    resolver = PublicOnlyResolver(
        StubResolver({"example.com": ["93.184.216.34", "10.0.0.4"]})
    )

    with pytest.raises(LinkPreviewValidationError, match="URL is not allowed"):
        await resolver.resolve("example.com", 443, socket.AF_UNSPEC)


@pytest.mark.asyncio
async def test_public_only_resolver_pins_validated_dns_answers():
    upstream = StubResolver({"example.com": ["93.184.216.34"]})
    resolver = PublicOnlyResolver(upstream)

    first = await resolver.resolve("example.com", 443, socket.AF_UNSPEC)
    second = await resolver.resolve("example.com", 443, socket.AF_UNSPEC)

    assert first == second
    assert upstream.calls == ["example.com"]
```

- [ ] **Step 2: Run the safety tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_link_preview.py -v
```

Expected: FAIL because `db.link_preview_repository` and `LinkPreviewValidationError` do not exist.

- [ ] **Step 3: Add the sanitized validation exception**

Append to `errors.py`:

```python
class LinkPreviewValidationError(ValueError):
    def __init__(self):
        super().__init__("URL is not allowed")
```

- [ ] **Step 4: Implement syntax validation and the pinning resolver**

Create `db/link_preview_repository.py` with these constants and resolver behavior:

```python
import asyncio
import ipaddress
import socket
from collections.abc import Callable

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver
from yarl import URL

from errors import LinkPreviewValidationError

MAX_HTML_BYTES = 1_048_576
MAX_REDIRECTS = 3
REQUEST_TIMEOUT_SECONDS = 5
HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
USER_AGENT = "PixLogistic-LinkPreview/1.0"


def _is_global_address(value: str) -> bool:
    try:
        return ipaddress.ip_address(value.split("%", 1)[0]).is_global
    except ValueError:
        return False


def validate_url_target(value: str | URL) -> URL:
    try:
        url = value if isinstance(value, URL) else URL(value)
    except (TypeError, ValueError):
        raise LinkPreviewValidationError() from None

    if url.scheme not in {"http", "https"} or not url.host or url.user or url.password:
        raise LinkPreviewValidationError()

    try:
        literal = ipaddress.ip_address(url.host.split("%", 1)[0])
    except ValueError:
        return url
    if not literal.is_global:
        raise LinkPreviewValidationError()
    return url


class PublicOnlyResolver(AbstractResolver):
    def __init__(self, upstream: AbstractResolver | None = None):
        self._upstream = upstream or DefaultResolver()
        self._cache: dict[tuple[str, int, int], list[dict[str, object]]] = {}
        self._closed = False

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        key = (host, port, family)
        if key not in self._cache:
            records = await self._upstream.resolve(host, port, family)
            if not records or any(not _is_global_address(str(record["host"])) for record in records):
                raise LinkPreviewValidationError()
            self._cache[key] = list(records)
        return list(self._cache[key])

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._upstream.close()
```

The cache is part of the security boundary: the repository pre-resolves each hop through this resolver, and aiohttp's connector receives the same resolver and therefore the same validated records.

- [ ] **Step 5: Run the resolver tests and verify GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_link_preview.py -v
```

Expected: extraction tests and all URL-policy/resolver cases PASS.

- [ ] **Step 6: Add failing repository redirect and limit tests**

Append fake response/session helpers and behavior tests to `tests/test_link_preview.py`. The fake session must expose `get()` as an async context manager, record requested URLs, and provide response bodies through an async `iter_chunked()` method.

```python
from db.link_preview_repository import LinkPreviewRepository, MAX_HTML_BYTES
from yarl import URL


class FakeContent:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks

    async def iter_chunked(self, size: int):
        for chunk in self.chunks:
            yield chunk


class FakeResponse:
    def __init__(self, status: int, url: str, headers=None, chunks=None):
        self.status = status
        self.url = URL(url)
        self.headers = headers or {}
        self.content = FakeContent(chunks or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception], requested: list[str]):
        self.responses = responses
        self.requested = requested

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def get(self, url, **kwargs):
        self.requested.append(str(url))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_repository_revalidates_redirect_before_second_request():
    requested: list[str] = []
    upstream = StubResolver({"example.com": ["93.184.216.34"]})
    responses = [
        FakeResponse(302, "https://example.com/start", {"Location": "http://127.0.0.1/private"})
    ]
    repository = LinkPreviewRepository(
        resolver=PublicOnlyResolver(upstream),
        session_factory=lambda **kwargs: FakeSession(responses, requested),
    )

    with pytest.raises(LinkPreviewValidationError):
        await repository.fetch_html("https://example.com/start")
    assert requested == ["https://example.com/start"]


@pytest.mark.asyncio
async def test_repository_returns_none_for_non_html_and_oversized_responses():
    requested: list[str] = []
    upstream = StubResolver({"example.com": ["93.184.216.34"]})
    responses = [
        FakeResponse(200, "https://example.com/file", {"Content-Type": "application/pdf"}),
        FakeResponse(
            200,
            "https://example.com/huge",
            {"Content-Type": "text/html; charset=utf-8"},
            [b"x" * (MAX_HTML_BYTES + 1)],
        ),
    ]
    repository = LinkPreviewRepository(
        resolver=PublicOnlyResolver(upstream),
        session_factory=lambda **kwargs: FakeSession(responses, requested),
    )

    assert await repository.fetch_html("https://example.com/file") is None
    assert await repository.fetch_html("https://example.com/huge") is None


@pytest.mark.asyncio
async def test_repository_returns_html_within_limits():
    upstream = StubResolver({"example.com": ["93.184.216.34"]})
    responses = [
        FakeResponse(
            200,
            "https://example.com/item",
            {"Content-Type": "text/html"},
            [b"<title>Example</title>"],
        )
    ]
    repository = LinkPreviewRepository(
        resolver=PublicOnlyResolver(upstream),
        session_factory=lambda **kwargs: FakeSession(responses, []),
    )

    assert await repository.fetch_html("https://example.com/item") == b"<title>Example</title>"


@pytest.mark.asyncio
async def test_repository_stops_after_redirect_limit():
    requested: list[str] = []
    upstream = StubResolver({"example.com": ["93.184.216.34"]})
    responses = [
        FakeResponse(
            302,
            f"https://example.com/{index}",
            {"Location": f"https://example.com/{index + 1}"},
        )
        for index in range(4)
    ]
    repository = LinkPreviewRepository(
        resolver=PublicOnlyResolver(upstream),
        session_factory=lambda **kwargs: FakeSession(responses, requested),
    )

    assert await repository.fetch_html("https://example.com/0") is None
    assert requested == [f"https://example.com/{index}" for index in range(4)]


@pytest.mark.asyncio
async def test_repository_turns_timeout_into_null_fallback():
    upstream = StubResolver({"example.com": ["93.184.216.34"]})
    repository = LinkPreviewRepository(
        resolver=PublicOnlyResolver(upstream),
        session_factory=lambda **kwargs: FakeSession([asyncio.TimeoutError()], []),
    )

    assert await repository.fetch_html("https://example.com/item") is None


@pytest.mark.asyncio
async def test_repository_turns_dns_failure_into_null_fallback():
    class FailingResolver(AbstractResolver):
        async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
            raise socket.gaierror("unavailable")

        async def close(self) -> None:
            return None

    repository = LinkPreviewRepository(
        resolver=PublicOnlyResolver(FailingResolver()),
        session_factory=lambda **kwargs: FakeSession([], []),
    )

    assert await repository.fetch_html("https://example.com/item") is None
```

- [ ] **Step 7: Run the repository tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_link_preview.py -v
```

Expected: FAIL because `LinkPreviewRepository` is not implemented.

- [ ] **Step 8: Implement bounded manual redirect fetching**

Add the default session factory and `LinkPreviewRepository` to `db/link_preview_repository.py`:

```python
def _create_session(*, resolver: PublicOnlyResolver) -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    return aiohttp.ClientSession(connector=connector, timeout=timeout)


class LinkPreviewRepository:
    def __init__(
        self,
        resolver: PublicOnlyResolver | None = None,
        session_factory: Callable[..., aiohttp.ClientSession] = _create_session,
    ):
        self._resolver = resolver or PublicOnlyResolver()
        self._session_factory = session_factory

    async def fetch_html(self, url: str) -> bytes | None:
        try:
            async with self._session_factory(resolver=self._resolver) as session:
                current = validate_url_target(url)
                for redirect_count in range(MAX_REDIRECTS + 1):
                    current = validate_url_target(current)
                    await self._resolver.resolve(
                        current.host,
                        current.port or (443 if current.scheme == "https" else 80),
                        socket.AF_UNSPEC,
                    )
                    async with session.get(
                        current,
                        allow_redirects=False,
                        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                    ) as response:
                        if response.status in REDIRECT_STATUSES:
                            if redirect_count == MAX_REDIRECTS:
                                return None
                            location = response.headers.get("Location")
                            if not location:
                                return None
                            current = validate_url_target(response.url.join(URL(location)))
                            continue

                        if not 200 <= response.status < 300:
                            return None
                        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                        if content_type not in HTML_CONTENT_TYPES:
                            return None

                        body = bytearray()
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            if len(body) + len(chunk) > MAX_HTML_BYTES:
                                return None
                            body.extend(chunk)
                        return bytes(body)
        except LinkPreviewValidationError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, UnicodeError, ValueError):
            return None
        return None
```

`aiohttp.ClientSession` defaults to `trust_env=False`; retain that behavior so system proxy settings cannot bypass destination validation.

- [ ] **Step 9: Run the complete backend feature tests and verify GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_link_preview.py -v
```

Expected: all extraction, URL-policy, resolver, redirect, content-type, size-limit, and success tests PASS.

- [ ] **Step 10: Commit the safe fetcher**

```powershell
git add errors.py db/link_preview_repository.py tests/test_link_preview.py
git commit -m "feat: fetch link previews safely"
```

---

### Task 3: Authenticated link-title endpoint

**Files:**
- Create: `dependecies/link_preview.py`
- Create: `routes/link_preview.py`
- Modify: `main.py`
- Modify: `scripts/check.ps1`
- Modify: `tests/test_link_preview.py`

**Interfaces:**
- Consumes: `LinkPreviewManager`, `LinkPreviewRepository`, `LinkTitleRequest`, and `LinkTitleResponse` from Tasks 1–2.
- Produces: authenticated `POST /api_v1/link-preview/title` with `{ "url": string } -> { "title": string | null }`.

- [ ] **Step 1: Add failing endpoint contract tests**

Append to `tests/test_link_preview.py`:

```python
from fastapi.testclient import TestClient

from config import Settings
from dependecies.link_preview import get_link_preview_manager
from main import create_app
from routes.users import current_user_dependency


class StubLinkPreviewManager:
    def __init__(self, title: str | None = "Example product", error: Exception | None = None):
        self.title = title
        self.error = error
        self.urls: list[str] = []

    async def get_title(self, url: str) -> str | None:
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.title


def link_preview_client(manager: StubLinkPreviewManager):
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[current_user_dependency] = lambda: object()
    app.dependency_overrides[get_link_preview_manager] = lambda: manager
    return TestClient(app)


def test_link_title_endpoint_returns_typed_title_without_live_http():
    manager = StubLinkPreviewManager()

    with link_preview_client(manager) as client:
        response = client.post(
            "/api_v1/link-preview/title",
            json={"url": "https://example.com/item"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"title": "Example product"}
    assert manager.urls == ["https://example.com/item"]


def test_link_title_endpoint_maps_disallowed_destination_to_sanitized_422():
    manager = StubLinkPreviewManager(error=LinkPreviewValidationError())

    with link_preview_client(manager) as client:
        response = client.post(
            "/api_v1/link-preview/title",
            json={"url": "https://example.com/redirect"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "URL is not allowed"}


def test_link_title_endpoint_rejects_credentials_before_manager_call():
    manager = StubLinkPreviewManager()

    with link_preview_client(manager) as client:
        response = client.post(
            "/api_v1/link-preview/title",
            json={"url": "https://user:password@example.com/item"},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 422
    assert manager.urls == []


def test_link_title_endpoint_requires_authentication():
    app = create_app(Settings(_env_file=None, app_env="test"))

    with TestClient(app) as client:
        response = client.post(
            "/api_v1/link-preview/title",
            json={"url": "https://example.com/item"},
        )

    assert response.status_code == 401
```

- [ ] **Step 2: Run endpoint tests and verify RED**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_link_preview.py -v
```

Expected: FAIL because the dependency and route modules do not exist.

- [ ] **Step 3: Wire the dependency and route**

Create `dependecies/link_preview.py`:

```python
from db.link_preview_repository import LinkPreviewRepository
from manager.link_preview import LinkPreviewManager


async def get_link_preview_manager():
    yield LinkPreviewManager(LinkPreviewRepository())
```

Create `routes/link_preview.py`:

```python
from fastapi import APIRouter, Depends, HTTPException

from db.models.users import User
from db.schemas.link_preview import LinkTitleRequest, LinkTitleResponse
from dependecies.link_preview import get_link_preview_manager
from errors import LinkPreviewValidationError
from manager.link_preview import LinkPreviewManager
from routes.users import current_user_dependency

router = APIRouter(prefix="/link-preview", tags=["Link preview"])


@router.post("/title", response_model=LinkTitleResponse)
async def get_link_title(
    request: LinkTitleRequest,
    _user: User = Depends(current_user_dependency),
    manager: LinkPreviewManager = Depends(get_link_preview_manager),
):
    try:
        title = await manager.get_title(str(request.url))
    except LinkPreviewValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return LinkTitleResponse(title=title)
```

- [ ] **Step 4: Mount the route and extend backend lint coverage**

In `main.py`, import `router as router_link_preview` from `routes.link_preview` and call:

```python
api_router.include_router(router_link_preview)
```

Add these exact paths to `$ruffTargets` in `scripts/check.ps1`:

```powershell
"db/link_preview_repository.py",
"db/schemas/link_preview.py",
"dependecies/link_preview.py",
"manager/link_preview.py",
"routes/link_preview.py",
```

- [ ] **Step 5: Run focused and complete backend checks and verify GREEN**

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_link_preview.py -v
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Expected: endpoint tests PASS; Ruff and all backend pytest tests PASS. The run must not make live outbound HTTP requests.

- [ ] **Step 6: Commit the backend API**

```powershell
git add dependecies/link_preview.py routes/link_preview.py main.py scripts/check.ps1 tests/test_link_preview.py
git commit -m "feat: expose link title previews"
```

---

### Task 4: Frontend position URL tokenizer

**Files:**
- Create: `../pix_frontend_v2/vitest.config.ts`
- Create: `../pix_frontend_v2/src/components/positionLink/positionText.test.ts`
- Create: `../pix_frontend_v2/src/components/positionLink/positionText.ts`
- Modify: `../pix_frontend_v2/package.json`
- Modify: `../pix_frontend_v2/package-lock.json`

**Interfaces:**
- Produces: `PositionSegment = { type: "text" | "link"; value: string }`.
- Produces: `tokenizePositionText(value: string) -> PositionSegment[]`, preserving all non-link characters.

- [ ] **Step 1: Install the existing-plan-compatible unit runner**

Run from `../pix_frontend_v2`:

```powershell
npm.cmd install --save-dev vitest@3.2.4
```

Expected: only `package.json` and `package-lock.json` dependency metadata changes; no production dependency is added.

- [ ] **Step 2: Add the unit script and Vitest configuration**

Add `test:unit` to `package.json` and run it inside `check` before build:

```json
"test:unit": "vitest run",
"check": "npm run lint && npm run check:api-url && npm run test:unit && npm run build && npm run test:e2e"
```

Create `vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
```

- [ ] **Step 3: Write failing tokenizer tests**

Create `src/components/positionLink/positionText.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { tokenizePositionText } from "./positionText";

describe("tokenizePositionText", () => {
  it("preserves ordinary position text", () => {
    expect(tokenizePositionText("iPhone 15 128 GB")).toEqual([
      { type: "text", value: "iPhone 15 128 GB" },
    ]);
  });

  it("extracts multiple web links and preserves punctuation", () => {
    expect(
      tokenizePositionText(
        "Compare https://shop.example/item, then http://other.example/a?x=1.",
      ),
    ).toEqual([
      { type: "text", value: "Compare " },
      { type: "link", value: "https://shop.example/item" },
      { type: "text", value: ", then " },
      { type: "link", value: "http://other.example/a?x=1" },
      { type: "text", value: "." },
    ]);
  });

  it("keeps balanced URL parentheses and removes unmatched closing punctuation", () => {
    expect(tokenizePositionText("See https://example.com/item_(blue)).")).toEqual([
      { type: "text", value: "See " },
      { type: "link", value: "https://example.com/item_(blue)" },
      { type: "text", value: ")." },
    ]);
  });
});
```

- [ ] **Step 4: Run tokenizer tests and verify RED**

```powershell
npm.cmd run test:unit -- src/components/positionLink/positionText.test.ts
```

Expected: FAIL because `positionText.ts` does not exist.

- [ ] **Step 5: Implement deterministic URL tokenization**

Create `src/components/positionLink/positionText.ts`:

```ts
export type PositionSegment = {
  type: "text" | "link";
  value: string;
};

const urlPattern = /https?:\/\/[^\s<>"']+/giu;
const simpleTrailingPunctuation = new Set([".", ",", "!", "?", ";", ":"]);

function splitTrailingPunctuation(candidate: string): [string, string] {
  let end = candidate.length;
  while (end > 0 && simpleTrailingPunctuation.has(candidate[end - 1])) end -= 1;

  for (const [opening, closing] of [["(", ")"], ["[", "]"], ["{", "}"]]) {
    const current = candidate.slice(0, end);
    const openings = [...current].filter((character) => character === opening).length;
    let closings = [...current].filter((character) => character === closing).length;
    while (end > 0 && candidate[end - 1] === closing && closings > openings) {
      end -= 1;
      closings -= 1;
    }
  }

  return [candidate.slice(0, end), candidate.slice(end)];
}

export function tokenizePositionText(value: string): PositionSegment[] {
  const segments: PositionSegment[] = [];
  let cursor = 0;

  for (const match of value.matchAll(urlPattern)) {
    const start = match.index ?? 0;
    if (start > cursor) segments.push({ type: "text", value: value.slice(cursor, start) });

    const candidate = match[0];
    const [url, trailing] = splitTrailingPunctuation(candidate);
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error();
      segments.push({ type: "link", value: url });
      if (trailing) segments.push({ type: "text", value: trailing });
    } catch {
      segments.push({ type: "text", value: candidate });
    }
    cursor = start + candidate.length;
  }

  if (cursor < value.length) segments.push({ type: "text", value: value.slice(cursor) });
  return segments.length > 0 ? segments : [{ type: "text", value }];
}
```

- [ ] **Step 6: Run focused and complete unit tests and verify GREEN**

```powershell
npm.cmd run test:unit -- src/components/positionLink/positionText.test.ts
npm.cmd run test:unit
```

Expected: all 3 tokenizer tests PASS.

- [ ] **Step 7: Commit the tokenizer and test harness**

```powershell
git add package.json package-lock.json vitest.config.ts src/components/positionLink/positionText.ts src/components/positionLink/positionText.test.ts
git commit -m "test: cover position link parsing"
```

---

### Task 5: Shared title renderer and both order screens

**Files:**
- Create: `../pix_frontend_v2/src/components/positionLink/PositionText.tsx`
- Create: `../pix_frontend_v2/tests/mock-backend.mjs`
- Create: `../pix_frontend_v2/tests/position-link-title.spec.ts`
- Modify: `../pix_frontend_v2/src/routes/routes.tsx`
- Modify: `../pix_frontend_v2/src/app/dashboard/neworder/page.tsx`
- Modify: `../pix_frontend_v2/src/app/dashboard/orders/[id]/page.tsx`
- Modify: `../pix_frontend_v2/playwright.config.ts`

**Interfaces:**
- Consumes: backend `POST /api_v1/link-preview/title` and `tokenizePositionText()` from Task 4.
- Produces: `GetLinkTitle(url: string) -> Promise<string | null>` with no toast.
- Produces: `PositionText({ value: string })`, which uses the title when available and the URL otherwise.

- [ ] **Step 1: Create the deterministic browser-test backend**

Create `tests/mock-backend.mjs` using Node's `http` module. It must listen on `127.0.0.1:8100`, answer CORS preflight, and implement these exact responses:

```js
import { createServer } from "node:http";

const port = 8100;
const titleByUrl = new Map([
  ["https://shop.example/item", "Example item"],
  ["https://shop.example/missing", null],
]);

function sendJson(response, value, statusCode = 200) {
  response.writeHead(statusCode, {
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json; charset=utf-8",
  });
  response.end(JSON.stringify(value));
}

async function readJson(request) {
  let body = "";
  for await (const chunk of request) body += chunk;
  return JSON.parse(body || "{}");
}

const server = createServer(async (request, response) => {
  if (request.method === "OPTIONS") return sendJson(response, null, 204);
  const pathname = new URL(request.url ?? "/", "http://127.0.0.1").pathname;

  if (pathname === "/api_v1/health") return sendJson(response, { status: "ok" });
  if (pathname === "/api_v1/users/updatedMe") {
    return sendJson(response, {
      id: "test-user",
      email: "test@example.com",
      first_name: "Test",
      last_name: "User",
      balance: 0,
      is_verified: true,
      is_organization_user: false,
    });
  }
  if (request.method === "POST" && pathname === "/api_v1/link-preview/title") {
    const { url } = await readJson(request);
    return sendJson(response, { title: titleByUrl.get(url) ?? null });
  }
  if (pathname === "/api_v1/orders/existing-order") {
    return sendJson(response, {
      positions: {
        rows: [{
          id: "position-1",
          assortment: { name: "https://shop.example/item", description: "" },
          quantity: 1,
          shipped: 0,
          price: 10000,
        }],
      },
      state: { name: "Новый" },
      name: "101",
      purchaseOrders: [],
      invoicesOut: [],
    });
  }
  if (pathname === "/api_v1/orders/actions/existing-order") return sendJson(response, []);
  if (pathname === "/api_v1/chat/messages/existing-order") return sendJson(response, []);
  if (pathname === "/api_v1/payment/vault_courses") {
    return sendJson(response, { rates: { USD: 4, EUR: 4.25 } });
  }
  return sendJson(response, { detail: "Not Found" }, 404);
});

server.listen(port, "127.0.0.1");
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
```

- [ ] **Step 2: Isolate Playwright from real backend services**

Replace the single `webServer` in `playwright.config.ts` with the following two local servers and change `baseURL` to port 3100:

```ts
const frontendUrl = "http://127.0.0.1:3100";
const backendUrl = "http://127.0.0.1:8100/api_v1";

// inside defineConfig
use: { baseURL: frontendUrl, trace: "retain-on-failure" },
webServer: [
  {
    command: "node tests/mock-backend.mjs",
    url: `${backendUrl}/health`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
  {
    command: "powershell -NoProfile -Command \"$env:NEXT_PUBLIC_BACKEND_URL='http://127.0.0.1:8100/api_v1'; npm.cmd run dev -- -p 3100\"",
    url: frontendUrl,
    reuseExistingServer: false,
    timeout: 120_000,
  },
],
```

Run the existing smoke test before adding the feature test:

```powershell
npx.cmd playwright test tests/public-page.spec.ts
```

Expected: PASS using only ports 3100 and 8100.

- [ ] **Step 3: Write failing new-order and existing-order browser tests**

Create `tests/position-link-title.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ context }) => {
  await context.addCookies([{
    name: "token",
    value: "Bearer test-token",
    url: "http://127.0.0.1:3100",
  }]);
});

test("shows titles, fallback URLs, safe anchors, and deduplicates new-order lookups", async ({ page }) => {
  const titleRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api_v1/link-preview/title")) titleRequests.push(request.url());
  });
  await page.addInitScript(() => {
    localStorage.setItem("cart", JSON.stringify([{
      position: "Compare https://shop.example/item and https://shop.example/item; fallback https://shop.example/missing.",
      count: 1,
      comment: "",
    }]));
  });

  await page.goto("/dashboard/neworder");

  const titledLinks = page.getByRole("link", { name: "Example item" });
  await expect(titledLinks).toHaveCount(2);
  await expect(titledLinks.first()).toHaveAttribute("href", "https://shop.example/item");
  await expect(titledLinks.first()).toHaveAttribute("target", "_blank");
  await expect(titledLinks.first()).toHaveAttribute("rel", "noopener noreferrer");
  await expect(page.getByRole("link", { name: "https://shop.example/missing" })).toBeVisible();
  await expect.poll(() => titleRequests.length).toBe(2);
});

test("uses the same title renderer in an existing order", async ({ page }) => {
  await page.routeWebSocket("wss://pixlogistic.com/**", (webSocket) => webSocket.close());

  await page.goto("/dashboard/orders/existing-order");

  const link = page.getByRole("link", { name: "Example item" });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", "https://shop.example/item");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer");
});
```

The first test expects 2 title requests, not 3: the duplicate exact item URL shares one promise, while the distinct fallback URL has its own request.

- [ ] **Step 4: Run the browser test and verify RED**

```powershell
npx.cmd playwright test tests/position-link-title.spec.ts
```

Expected: FAIL because links still display raw URLs and do not have `_blank`/`noopener noreferrer`. Confirm both authenticated pages and their mock data load before implementation.

- [ ] **Step 5: Add the typed toast-free API call**

In `src/routes/routes.tsx`, add:

```ts
type LinkTitleResponse = {
  title: string | null;
};

export async function GetLinkTitle(url: string): Promise<string | null> {
  try {
    const response = await axios.post<LinkTitleResponse>(
      backendUrl("link-preview/title"),
      { url },
      { headers: { Authorization: getCookie("token") } },
    );
    return response.data.title;
  } catch {
    return null;
  }
}
```

Do not wrap this request in `toast.promise`.

- [ ] **Step 6: Implement the shared cached renderer**

Create `src/components/positionLink/PositionText.tsx`:

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";

import { GetLinkTitle } from "@/routes/routes";
import { tokenizePositionText } from "./positionText";

const titleRequests = new Map<string, Promise<string | null>>();

function getCachedTitle(url: string): Promise<string | null> {
  const cached = titleRequests.get(url);
  if (cached) return cached;

  const request = GetLinkTitle(url).catch(() => null);
  titleRequests.set(url, request);
  return request;
}

export default function PositionText({ value }: { value: string }) {
  const segments = useMemo(() => tokenizePositionText(value), [value]);
  const [titles, setTitles] = useState<Record<string, string | null>>({});

  useEffect(() => {
    let active = true;
    const urls = [...new Set(
      segments.filter((segment) => segment.type === "link").map((segment) => segment.value),
    )];

    Promise.all(urls.map(async (url) => [url, await getCachedTitle(url)] as const)).then((entries) => {
      if (active) setTitles((current) => ({ ...current, ...Object.fromEntries(entries) }));
    });
    return () => { active = false; };
  }, [segments]);

  return (
    <span>
      {segments.map((segment, index) =>
        segment.type === "link" ? (
          <a
            key={`${segment.value}-${index}`}
            href={segment.value}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:underline"
          >
            {titles[segment.value] || segment.value}
          </a>
        ) : (
          <span key={`text-${index}`}>{segment.value}</span>
        ),
      )}
    </span>
  );
}
```

- [ ] **Step 7: Replace both duplicated cell renderers**

In both `src/app/dashboard/neworder/page.tsx` and `src/app/dashboard/orders/[id]/page.tsx`, import:

```tsx
import PositionText from "@/components/positionLink/PositionText";
```

Replace the regex-based renderer in `src/app/dashboard/neworder/page.tsx` with:

```tsx
function positionCell({ data }: CustomCellRendererProps<CartGrid>) {
  return <PositionText value={data?.position ?? ""} />;
}
```

Replace the regex-based renderer in `src/app/dashboard/orders/[id]/page.tsx` with:

```tsx
function positionCell({ data }: CustomCellRendererProps<OrderGrid>) {
  return <PositionText value={data?.position ?? ""} />;
}
```

Remove both old regex and split/map implementations completely.

- [ ] **Step 8: Run focused frontend tests and verify GREEN**

```powershell
npm.cmd run test:unit -- src/components/positionLink/positionText.test.ts
npx.cmd playwright test tests/position-link-title.spec.ts
```

Expected: tokenizer tests and both browser scenarios PASS. Playwright requests only the local mock backend; the production WebSocket is intercepted before connection.

- [ ] **Step 9: Run the full cross-repository verification matrix**

From `pix_backend` after the final edit:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

From `../pix_frontend_v2` after the final edit:

```powershell
npm.cmd run lint
npm.cmd run test:unit
npm.cmd run test:e2e
npm.cmd run check
```

Expected: backend Ruff/pytest and frontend lint, API URL guard, unit tests, build, and Playwright tests PASS. Existing documented hook warnings may remain, but this change adds no warnings. If the production build cannot download Google Fonts because network access is restricted, record that exact external blocker while retaining the successful lint, unit, and Playwright results.

- [ ] **Step 10: Review both diffs and commit the frontend feature**

Run:

```powershell
git -C ..\pix_frontend_v2 diff --check
git -C ..\pix_frontend_v2 status --short
git -C ..\pix_frontend_v2 diff -- src/routes/routes.tsx src/components/positionLink src/app/dashboard/neworder/page.tsx "src/app/dashboard/orders/[id]/page.tsx" tests playwright.config.ts
```

Confirm no order payload, cookie, WebSocket production code, or unrelated UI behavior changed. Then commit from `../pix_frontend_v2`:

```powershell
git add src/routes/routes.tsx src/components/positionLink src/app/dashboard/neworder/page.tsx "src/app/dashboard/orders/[id]/page.tsx" tests/mock-backend.mjs tests/position-link-title.spec.ts playwright.config.ts
git commit -m "feat: show titles for order position links"
```

Finally, from `pix_backend`, verify that only the already-committed backend feature and plan/spec history differ from the pre-feature baseline:

```powershell
git status --short
git log --oneline -5
```
