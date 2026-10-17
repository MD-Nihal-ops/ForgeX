$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Install and start Docker Desktop, then retry."
}

if (-not (Test-Path ".env")) {
    throw "Missing .env file. Copy .env.example to .env and set a unique POSTGRES_PASSWORD."
}

$passwordLine = Get-Content ".env" | Where-Object { $_ -match '^\s*POSTGRES_PASSWORD\s*=' } | Select-Object -First 1
if (-not $passwordLine -or $passwordLine -match '=\s*$|=\s*change-me\s*$') {
    throw "Set a non-empty, private POSTGRES_PASSWORD in .env before starting ForgeX."
}

docker compose config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose configuration validation failed."
}

docker compose up --build
exit $LASTEXITCODE
