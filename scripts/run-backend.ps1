<#
.SYNOPSIS
    Sets up the backend virtualenv and starts the FastAPI dev server.

.DESCRIPTION
    Creates backend/.venv if missing, installs requirements.txt, then runs
    uvicorn with --reload. Safe to re-run: the venv and installed packages
    are reused. Does NOT create or modify .env - set ANTHROPIC_API_KEY there
    yourself before starting.

.EXAMPLE
    .\scripts\run-backend.ps1
    .\scripts\run-backend.ps1 -Port 8001
    .\scripts\run-backend.ps1 -SkipInstall
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'

$backend = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend'
if (-not (Test-Path $backend)) { throw "Backend directory not found: $backend" }
Set-Location $backend

# --- Resolve a real Python interpreter -------------------------------------
# The Microsoft Store alias stub in WindowsApps shadows real installs and
# fails with "cannot find the file ...\WindowsApps\python.exe", so probe the
# py launcher and known install locations rather than trusting `python`.
function Resolve-Python {
    $candidates = @()

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $target = (& py -3 -c "import sys; print(sys.executable)" 2>$null)
            if ($LASTEXITCODE -eq 0 -and $target) { $candidates += $target.Trim() }
        } catch { }
    }

    $candidates += Join-Path $env:LOCALAPPDATA 'Python\bin\python.exe'

    foreach ($c in Get-Command python -All -ErrorAction SilentlyContinue) {
        $candidates += $c.Source
    }

    foreach ($c in $candidates) {
        if ([string]::IsNullOrWhiteSpace($c)) { continue }
        if (-not (Test-Path $c)) { continue }
        # Store alias stubs are zero-byte reparse points.
        if ((Get-Item $c -Force).Length -eq 0) { continue }
        return $c
    }

    throw "No usable Python interpreter found. Install Python 3.14 from python.org and reopen the terminal."
}

$venvPython = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    $python = Resolve-Python
    Write-Host "Creating virtualenv with $python" -ForegroundColor Cyan
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed (exit $LASTEXITCODE)" }
}

# Activate so the prompt and any child tools see the venv. Running through
# $venvPython below works regardless, so a blocked Activate.ps1 is not fatal.
$activate = Join-Path $backend '.venv\Scripts\Activate.ps1'
try { . $activate } catch { Write-Warning "Could not dot-source Activate.ps1: $($_.Exception.Message)" }

if (-not $SkipInstall) {
    Write-Host "Installing requirements.txt" -ForegroundColor Cyan
    & $venvPython -m pip install --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }
}

if (-not (Test-Path (Join-Path $backend '.env'))) {
    Write-Warning ".env not found in $backend - the API needs ANTHROPIC_API_KEY to answer requests."
}

Write-Host "Starting uvicorn on http://localhost:$Port (docs at /docs)" -ForegroundColor Green
& $venvPython -m uvicorn app.main:app --reload --port $Port
exit $LASTEXITCODE
