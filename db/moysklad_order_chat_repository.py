import base64
from dataclasses import dataclass
from functools import partial
from urllib.parse import urlparse
from uuid import UUID

import requests
from anyio import to_thread

from config import Settings, require_secret, require_value


@dataclass(frozen=True, slots=True)
class MoySkladFile:
    id: UUID
    filename: str
    size: int
    download_href: str


@dataclass(frozen=True, slots=True)
class MoySkladUpload:
    filename: str
    content: bytes


class MoySkladOrderChatRepository:
    base_url = "https://api.moysklad.ru/api/remap/1.2/"

    def __init__(
        self,
        settings: Settings,
        *,
        session: requests.Session | None = None,
        timeout_seconds: int = 15,
    ):
        self._settings = settings
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        login = require_value(self._settings.moysklad_login, "moysklad")
        password = require_secret(self._settings.moysklad_password, "moysklad")
        encoded = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("ascii")
        return {
            "Accept-Encoding": "gzip",
            "Authorization": f"Basic {encoded}",
        }

    async def _request(self, method: str, path_or_url: str, **kwargs):
        url = path_or_url if path_or_url.startswith("https://") else self.base_url + path_or_url.lstrip("/")
        request = partial(
            self._session.request,
            method,
            url,
            headers=self._headers(),
            timeout=self._timeout_seconds,
            **kwargs,
        )
        response = await to_thread.run_sync(request)
        response.raise_for_status()
        return response

    async def get_order(self, order_id: UUID) -> dict:
        response = await self._request(
            "GET",
            f"entity/customerorder/{order_id}",
            params={"expand": "agent"},
        )
        return response.json()

    async def update_description(self, order_id: UUID, description: str) -> dict:
        response = await self._request(
            "PUT",
            f"entity/customerorder/{order_id}",
            json={"description": description},
        )
        return response.json()

    async def list_files(self, order_id: UUID) -> list[MoySkladFile]:
        response = await self._request("GET", f"entity/customerorder/{order_id}/files")
        return [self._map_file(item) for item in response.json()["rows"]]

    async def upload_files(self, order_id: UUID, files: list[MoySkladUpload]) -> list[MoySkladFile]:
        uploaded: list[MoySkladFile] = []
        for offset in range(0, len(files), 10):
            chunk = files[offset : offset + 10]
            response = await self._request(
                "POST",
                f"entity/customerorder/{order_id}/files",
                json=[
                    {
                        "filename": item.filename,
                        "content": base64.b64encode(item.content).decode("ascii"),
                    }
                    for item in chunk
                ],
            )
            uploaded.extend(self._map_file(item) for item in response.json())
        return uploaded

    async def delete_file(self, order_id: UUID, file_id: UUID) -> None:
        await self._request("DELETE", f"entity/customerorder/{order_id}/files/{file_id}")

    async def download_file(self, download_href: str) -> bytes:
        parsed = urlparse(download_href)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.moysklad.ru"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
        ):
            raise ValueError("invalid MoySklad download URL")
        response = await self._request("GET", download_href, allow_redirects=True, stream=True)
        maximum = self._settings.chat_attachment_max_bytes
        if not hasattr(response, "iter_content"):
            content = bytes(response.content)
            if len(content) > maximum:
                raise ValueError("MoySklad file is too large")
            return content
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > maximum:
                    raise ValueError("MoySklad file is too large")
                chunks.append(chunk)
        finally:
            response.close()
        return b"".join(chunks)

    async def list_webhooks(self) -> list[dict]:
        response = await self._request("GET", "entity/webhook")
        return list(response.json()["rows"])

    async def create_webhook(self, url: str) -> dict:
        response = await self._request(
            "POST",
            "entity/webhook",
            json={
                "url": url,
                "action": "UPDATE",
                "entityType": "customerorder",
                "diffType": "FIELDS",
            },
        )
        return response.json()

    @staticmethod
    def _map_file(item: dict) -> MoySkladFile:
        meta = item["meta"]
        return MoySkladFile(
            id=UUID(meta["href"].rstrip("/").rsplit("/", 1)[-1]),
            filename=item["filename"],
            size=int(item.get("size", 0)),
            download_href=meta.get("downloadHref", ""),
        )
