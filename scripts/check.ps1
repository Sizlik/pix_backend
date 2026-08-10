$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$ruffTargets = @(
    "config.py",
    "errors.py",
    "main.py",
    "db/postgres.py",
    "db/redis.py",
    "db/repository.py",
    "db/link_preview_repository.py",
    "db/schemas/link_preview.py",
    "db/schemas/orders.py",
    "dependecies/link_preview.py",
    "dependecies/orders.py",
    "bot/sender.py",
    "manager/link_preview.py",
    "manager/moysklad.py",
    "manager/order_changes.py",
    "manager/bitrix.py",
    "manager/privoz_order.py",
    "manager/users.py",
    "routes/link_preview.py",
    "routes/orders.py",
    "moysklad_webhooks_creator.py",
    "tests"
)

& ".\.venv\Scripts\python.exe" -m ruff check @ruffTargets
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& ".\.venv\Scripts\python.exe" -m pytest tests -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
