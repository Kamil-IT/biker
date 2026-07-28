<#
.SYNOPSIS
    Installs frontend dependencies and starts the Vite dev server.

.DESCRIPTION
    Runs npm install if node_modules is missing, then starts Vite. Safe to
    re-run: an existing node_modules (including a junction shared from a
    worktree) is reused unless -Install is passed.

    The dev server proxies /v1/* to the backend on port 8000, so run
    scripts\run-backend.ps1 in another terminal first.

.EXAMPLE
    .\scripts\run-frontend.ps1
    .\scripts\run-frontend.ps1 -Port 5174
    .\scripts\run-frontend.ps1 -Install
    .\scripts\run-frontend.ps1 -Build
#>
[CmdletBinding()]
param(
    [int]$Port = 5173,
    [switch]$Install,
    [switch]$Build
)

$ErrorActionPreference = 'Stop'

$frontend = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend'
if (-not (Test-Path $frontend)) { throw "Frontend directory not found: $frontend" }
Set-Location $frontend

# --- Resolve npm ------------------------------------------------------------
# npm ships as npm.cmd on Windows; Get-Command finds it only if Node is on
# PATH, so fall back to the standard install location.
function Resolve-Npm {
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $cmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $fallback = Join-Path $env:ProgramFiles 'nodejs\npm.cmd'
    if (Test-Path $fallback) { return $fallback }

    throw "npm not found. Install Node.js v24 from nodejs.org and reopen the terminal."
}

$npm = Resolve-Npm

$nodeModules = Join-Path $frontend 'node_modules'
if ($Install -or -not (Test-Path $nodeModules)) {
    Write-Host "Installing npm dependencies" -ForegroundColor Cyan
    & $npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit $LASTEXITCODE)" }
}

if ($Build) {
    Write-Host "Building production bundle into dist/" -ForegroundColor Cyan
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
    Write-Host "Build complete." -ForegroundColor Green
    exit 0
}

# Warn if nothing is listening on the backend port the Vite proxy targets.
$backendUp = $false
try {
    $probe = New-Object Net.Sockets.TcpClient
    $probe.Connect('127.0.0.1', 8000)
    $backendUp = $probe.Connected
    $probe.Close()
} catch { }
if (-not $backendUp) {
    Write-Warning "Nothing listening on port 8000 - /v1/* proxy calls will fail until the backend is running."
}

Write-Host "Starting Vite on http://localhost:$Port" -ForegroundColor Green
& $npm run dev -- --port $Port
exit $LASTEXITCODE
