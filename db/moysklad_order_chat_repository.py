import base64
from functools import partial
from uuid import UUID

import requests
from anyio import to_thread

from config import Settings, require_secret, require_value
from errors import MoySkladOrderLookupUnavailable


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

    async def get_order(self, order_id: UUID) -> dict | None:
        try:
            response = await self._request(
                "GET",
                f"entity/customerorder/{order_id}",
                params={"expand": "agent"},
            )
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                return None
            raise MoySkladOrderLookupUnavailable() from None
        except requests.RequestException:
            raise MoySkladOrderLookupUnavailable() from None

        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise MoySkladOrderLookupUnavailable() from None
        if not isinstance(payload, dict):
            raise MoySkladOrderLookupUnavailable()
        return payload
