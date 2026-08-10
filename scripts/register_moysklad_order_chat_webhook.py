import argparse
import asyncio
from urllib.parse import urlparse

from config import get_settings
from db.moysklad_order_chat_repository import MoySkladOrderChatRepository


def build_webhook_url(base_url: str, secret: str) -> str:
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base URL must be an https origin without path, query, or fragment")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{origin}/api_v1/integration/webhooks/order-chat/{secret}"


def redact_webhook_url(url: str) -> str:
    return url.rsplit("/", 1)[0] + "/***"


async def run(base_url: str, apply: bool) -> int:
    settings = get_settings()
    chat = settings.require_order_chat()
    target = build_webhook_url(base_url, chat.webhook_secret)
    repository = MoySkladOrderChatRepository(settings)
    existing = await repository.list_webhooks()
    found = any(
        item.get("entityType") == "customerorder"
        and item.get("action") == "UPDATE"
        and item.get("url") == target
        for item in existing
    )
    if found:
        print(f"Webhook already exists: {redact_webhook_url(target)}")
        return 0
    if not apply:
        print(
            "Dry run: would create UPDATE/customerorder/FIELDS at "
            f"{redact_webhook_url(target)}"
        )
        return 0
    await repository.create_webhook(target)
    print(f"Webhook created: {redact_webhook_url(target)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args.base_url, args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
