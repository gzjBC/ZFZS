[CmdletBinding()]
param(
    [switch]$Live,
    [switch]$BrowserE2E,
    [switch]$NativeSmoke,
    [switch]$NoInstall,
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$projectRoot = Split-Path -Parent $PSScriptRoot
# Use exactly the same environment selection as source launch/build.
$python = & (Join-Path $PSScriptRoot 'run_desktop.ps1') -PrintPython -NoInstall:$NoInstall -PythonPath $PythonPath
$previousEncoding = $env:PYTHONIOENCODING
$previousDatabase = $env:DATABASE_URL
$env:PYTHONIOENCODING = 'utf-8'
$env:DATABASE_URL = 'sqlite:///:memory:'
Push-Location $projectRoot
try {
    Write-Host "Running unit tests with $python" -ForegroundColor Cyan
    & $python -B -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed.' }
    if ($NativeSmoke) {
        Write-Host 'Running native UI smoke test (requires a graphical session; uses temporary storage)...' -ForegroundColor Cyan
        & $python -B tests\smoke_desktop.py
        if ($LASTEXITCODE -ne 0) { throw 'Native UI smoke test failed.' }
    }
    if ($BrowserE2E) {
        Write-Host 'Running optional legacy browser E2E (writes reports and data/test_e2e.db)...' -ForegroundColor Cyan
        & $python -B scripts\high_intensity_test.py
        if ($LASTEXITCODE -ne 0) { throw 'Browser E2E tests failed.' }
    }
    if ($Live) {
        Write-Host 'Running live xifan smoke test (network/browser required)...' -ForegroundColor Cyan
        & $python -B scripts\xifan_search.py --smoke --limit 1
        if ($LASTEXITCODE -ne 0) { throw 'Live xifan smoke test failed.' }
    }
    Write-Host 'All requested checks passed.' -ForegroundColor Green
}
finally {
    Pop-Location
    $env:PYTHONIOENCODING = $previousEncoding
    $env:DATABASE_URL = $previousDatabase
}
