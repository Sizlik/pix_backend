import argparse
from collections.abc import Sequence

from pydantic import ValidationError

from config import Settings
from manager.production_config import validate_production_settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate production configuration without network calls.",
    )
    parser.add_argument(
        "--require-order-chat",
        action="store_true",
        help="require every order-chat integration setting",
    )
    args = parser.parse_args(argv)

    try:
        settings = Settings()
    except ValidationError:
        print("Production configuration could not be parsed.")
        return 1

    issues = validate_production_settings(
        settings,
        require_order_chat=args.require_order_chat,
    )
    if issues:
        for issue in sorted(issues, key=lambda item: (item.variable, item.reason)):
            print(f"{issue.variable}: {issue.reason}")
        return 1

    print("Production configuration is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
