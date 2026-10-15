param(
    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$localPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$localPythonw = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$legacyRoot = Split-Path -Parent $projectRoot
$legacyPython = Join-Path $legacyRoot ".venv\Scripts\python.exe"
$legacyPythonw = Join-Path $legacyRoot ".venv\Scripts\pythonw.exe"
$requirements = Join-Path $projectRoot "requirements.txt"

if (-not (Test-Path -LiteralPath $localPython -PathType Leaf)) {
    Write-Host "Creating desktop virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}

function Test-DesktopDependencies {
    param([string]$PythonPath)
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { return $false }
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $PythonPath -B -c "import tkinter, fastapi, sqlalchemy, pydantic_settings, requests, playwright" 2>$null
    $available = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $previousErrorPreference
    return $available
}

$python = $localPython
$pythonw = $localPythonw
if (-not (Test-DesktopDependencies $localPython) -and (Test-DesktopDependencies $legacyPython)) {
    $python = $legacyPython
    $pythonw = $legacyPythonw
    Write-Host "Using the existing repository Python environment." -ForegroundColor DarkGray
}
elseif (-not (Test-DesktopDependencies $localPython)) {
    Write-Host "Installing desktop dependencies..." -ForegroundColor Cyan
    & $localPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    $python = $localPython
    $pythonw = $localPythonw
}

if ($PrepareOnly) {
    Write-Host "Desktop environment is ready." -ForegroundColor Green
    return
}

Start-Process -FilePath $pythonw `
    -ArgumentList ('"' + (Join-Path $PSScriptRoot "desktop_app.py") + '"') `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden
