param(
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = if ($PythonPath) { $PythonPath } else { Join-Path $projectRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
}

& $python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $python -m PyInstaller --noconfirm --clean --windowed --paths . --name "ZFZS-Anime-Tracker" scripts\desktop_app.py
if ($LASTEXITCODE -ne 0) { throw "Desktop build failed." }

Write-Host "Windows desktop build created in dist\ZFZS-Anime-Tracker" -ForegroundColor Green
