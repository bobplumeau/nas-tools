# Installs or refreshes nas_t on Windows: pulls the latest code, (re)creates the venv if
# needed, reinstalls, runs the tests, and puts a `nas_t` shim on your PATH.
#   pwsh -File setup.ps1            # install / update
#   pwsh -File setup.ps1 -NoPull    # reinstall local changes without git pull
#   pwsh -File setup.ps1 -Clean     # rebuild the venv from scratch
param([switch]$NoPull, [switch]$Clean, [switch]$SkipTests)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not $NoPull -and (Test-Path .git)) {
    Write-Host "== git pull" -ForegroundColor Cyan
    git pull --ff-only
    if ($LASTEXITCODE) { throw "git pull failed - commit or stash local changes, or use -NoPull" }
}

if ($Clean -and (Test-Path venv)) { Remove-Item venv -Recurse -Force }
if (-not (Test-Path venv\Scripts\python.exe)) {
    Write-Host "== creating venv" -ForegroundColor Cyan
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv venv } else { python -m venv venv }
    if ($LASTEXITCODE) { throw "could not create venv - install Python 3.10+" }
}

Write-Host "== installing" -ForegroundColor Cyan
venv\Scripts\python.exe -m pip install --quiet --upgrade pip
venv\Scripts\python.exe -m pip install --quiet -e ".[dev]"

if (-not $SkipTests) {
    Write-Host "== tests" -ForegroundColor Cyan
    venv\Scripts\python.exe -m pytest tests -q
    if ($LASTEXITCODE) { throw "tests failed" }
}

$bin = Join-Path $HOME '.local\bin'
New-Item -ItemType Directory $bin -Force | Out-Null
Set-Content (Join-Path $bin 'nas_t.cmd') "@`"$PSScriptRoot\venv\Scripts\nas_t.exe`" %*"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $bin) {
    [Environment]::SetEnvironmentVariable('Path', "$userPath;$bin", 'User')
    Write-Host "Added $bin to your PATH (open a new terminal to use it)" -ForegroundColor Yellow
}

$cfg = Join-Path $HOME '.config\nas_t\devices.yaml'
$existing = @($cfg, (Join-Path $HOME '.config\nas-t\devices.yaml'), 'devices.yaml') | Where-Object { Test-Path $_ }
if (-not $existing) {
    New-Item -ItemType Directory (Split-Path $cfg) -Force | Out-Null
    Copy-Item devices.example.yaml $cfg
    Write-Host "Created $cfg - edit it with your NAS address and user" -ForegroundColor Yellow
}

Write-Host "== done: nas_t ready (run 'nas_t' for the shell, 'nas_t --help' for commands)" -ForegroundColor Green
