<#
.SYNOPSIS
  Run Tracebrain locally on Windows: FalkorDB (Docker), seed data, API and UI.

.DESCRIPTION
  Reads FALKOR_PORT from .env (docker-compose.yml publishes FalkorDB on that port too), waits for the
  graph server, seeds the demo tenants if they are missing (or always with -Reset), then opens the
  API and the UI in their own PowerShell windows and the app in your browser.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1
  powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 -Reset            # fresh data, empty memory
  powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 -ApiPort 8000 -UiPort 5173
#>
param(
    [switch]$Reset,
    [int]$ApiPort = 8010,
    [int]$UiPort = 5180
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Host 'Created .env from .env.example. Add GROQ_API_KEY to it for live agent runs.' -ForegroundColor Yellow
}

# FALKOR_PORT from .env (default 6379)
$falkorPort = 6379
foreach ($line in Get-Content '.env') {
    if ($line -match '^\s*FALKOR_PORT\s*=\s*(\d+)') { $falkorPort = [int]$Matches[1] }
}

function Test-PortBusy([int]$port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
foreach ($p in $ApiPort, $UiPort) {
    if (Test-PortBusy $p) { throw "Port $p is already in use. Stop whatever uses it or pass -ApiPort / -UiPort." }
}

Write-Host "Starting FalkorDB on port $falkorPort ..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw 'docker compose failed. Is Docker Desktop running?' }

# Wait until the graph module answers (GRAPH.LIST), not just the Redis port.
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    $out = docker exec falkordb redis-cli GRAPH.LIST 2>$null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'FalkorDB did not become ready in 30s (docker logs falkordb).' }

$seeded = ($out -join ' ') -match 'tenant_payments'
if ($Reset -or -not $seeded) {
    Write-Host 'Seeding demo tenants (payments, platform) ...' -ForegroundColor Cyan
    uv run python -m tracebrain.seed --reset
    if ($LASTEXITCODE -ne 0) { throw 'Seeding failed (see the message above).' }
} else {
    Write-Host 'Demo data already present (use -Reset for fresh data and empty memory).'
}

if (-not (Test-Path 'ui\node_modules')) {
    Write-Host 'Installing UI dependencies ...' -ForegroundColor Cyan
    Push-Location ui; npm install; Pop-Location
}

Write-Host "Starting API on http://localhost:$ApiPort and UI on http://localhost:$UiPort ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit', '-Command',
    "Set-Location '$root'; uv run uvicorn tracebrain.api.main:app --port $ApiPort"
Start-Process powershell -ArgumentList '-NoExit', '-Command',
    "Set-Location '$root\ui'; `$env:TRACEBRAIN_API_URL='http://localhost:$ApiPort'; npx vite --port $UiPort --strictPort"

# Open the browser once the UI answers.
for ($i = 0; $i -lt 40; $i++) {
    try { Invoke-WebRequest "http://localhost:$UiPort" -UseBasicParsing -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Seconds 1 }
}
Start-Process "http://localhost:$UiPort"
Write-Host "Ready. API docs: http://localhost:$ApiPort/docs . Close the two new windows to stop." -ForegroundColor Green
