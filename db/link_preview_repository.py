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
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global and not any(
        (
            address.is_loopback,
            address.is_private,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


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
    if not _is_global_address(str(literal)):
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


def _create_session(*, resolver: PublicOnlyResolver) -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    return aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=False)


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
                        headers={
                            "User-Agent": USER_AGENT,
                            "Accept": "text/html,application/xhtml+xml",
                        },
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
