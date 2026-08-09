$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

docker compose -f local-docker-compose.yml up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
