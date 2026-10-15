param(
    [switch]$Live
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found. Run .\scripts\run_desktop.ps1 -PrepareOnly first."
}

$env:PYTHONIOENCODING = "utf-8"

Write-Host "Running unit tests..." -ForegroundColor Cyan
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed." }

Write-Host "Running browser E2E tests..." -ForegroundColor Cyan
& $python scripts\high_intensity_test.py
if ($LASTEXITCODE -ne 0) { throw "E2E tests failed." }

if ($Live) {
    Write-Host "Running live xifan smoke test..." -ForegroundColor Cyan
    & $python scripts\xifan_search.py --smoke --limit 1
    if ($LASTEXITCODE -ne 0) { throw "Live xifan smoke test failed." }
}

Write-Host "All requested checks passed." -ForegroundColor Green
