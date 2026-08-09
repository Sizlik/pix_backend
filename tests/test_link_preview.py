import asyncio
import socket

import pytest
from aiohttp.abc import AbstractResolver
from yarl import URL

from db.link_preview_repository import (
    MAX_HTML_BYTES,
    LinkPreviewRepository,
    PublicOnlyResolver,
    validate_url_target,
)
from errors import LinkPreviewValidationError
from manager.link_preview import MAX_TITLE_LENGTH, LinkPreviewManager, extract_title


class StubLinkPreviewSource:
    def __init__(self, html: bytes | None):
        self.html = html
        self.urls: list[str] = []

    async def fetch_html(self, url: str) -> bytes | None:
        self.urls.append(url)
        return self.html


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
    resolver = PublicOnlyResolver(StubResolver({"example.com": ["93.184.216.34", "10.0.0.4"]}))

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


@pytest.mark.asyncio
async def test_repository_revalidates_redirect_before_second_request():
    requested: list[str] = []
    upstream = StubResolver({"example.com": ["93.184.216.34"]})
    responses = [FakeResponse(302, "https://example.com/start", {"Location": "http://127.0.0.1/private"})]
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
