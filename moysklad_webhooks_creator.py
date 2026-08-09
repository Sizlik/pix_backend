import base64

from config import Settings, get_settings, require_secret, require_value

MOYSKLAD_API_URL = "https://api.moysklad.ru/api/remap/1.2/"


def get_headers(settings: Settings | None = None) -> dict[str, str]:
    settings = settings or get_settings()
    login = require_value(settings.moysklad_login, "moysklad")
    password = require_secret(settings.moysklad_password, "moysklad")
    credentials = base64.b64encode(f"{login}:{password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {credentials}"}
