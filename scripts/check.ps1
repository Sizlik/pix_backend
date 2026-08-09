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
    "bot/sender.py",
    "manager/moysklad.py",
    "manager/bitrix.py",
    "manager/privoz_order.py",
    "manager/users.py",
    "moysklad_webhooks_creator.py",
    "tests"
)

& ".\.venv\Scripts\python.exe" -m ruff check @ruffTargets
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& ".\.venv\Scripts\python.exe" -m pytest tests -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
