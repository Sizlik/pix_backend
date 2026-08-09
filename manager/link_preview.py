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
