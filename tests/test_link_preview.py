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
