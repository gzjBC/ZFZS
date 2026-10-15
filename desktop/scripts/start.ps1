param(
    [int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $projectRoot "requirements.txt"

function Find-FreePort {
    param([int]$StartPort)
    $candidate = $StartPort
    while ($candidate -lt ($StartPort + 50)) {
        $connection = Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue
        if (-not $connection) {
            return $candidate
        }
        $candidate += 1
    }
    throw "No free port found from $StartPort to $($StartPort + 49)."
}

function Find-RunningAppPort {
    param([int]$StartPort)
    $endPort = $StartPort + 49
    $ports = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -ge $StartPort -and $_.LocalPort -le $endPort } |
        Select-Object -ExpandProperty LocalPort -Unique |
        Sort-Object

    foreach ($candidate in $ports) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$candidate/api/health" -TimeoutSec 1
            if ($health.ok -and $health.app -eq "ZFZS Anime Assistant") {
                return $candidate
            }
        }
        catch {
            # The port belongs to another application.
        }
    }
    return $null
}

function Wait-ForHealth {
    param(
        [string]$Url,
        [System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds = 20
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) {
            throw "ZFZS server exited during startup (code $($Process.ExitCode))."
        }
        try {
            $health = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 1
            if ($health.ok) { return }
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }
    throw "ZFZS server did not become ready within $TimeoutSeconds seconds."
}

function Test-PythonModule {
    param([string]$Module)
    & $python -B -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$Module') else 1)" | Out-Null
    return $LASTEXITCODE -eq 0
}

$runningPort = Find-RunningAppPort -StartPort $Port
if ($null -ne $runningPort) {
    $runningUrl = "http://127.0.0.1:$runningPort/"
    Write-Host "ZFZS Anime Assistant is already running: $runningUrl" -ForegroundColor Green
    if (-not $NoBrowser) {
        Start-Process $runningUrl
    }
    return
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

if (-not (Test-PythonModule "fastapi") -or -not (Test-PythonModule "playwright")) {
    Write-Host "Installing Python dependencies..." -ForegroundColor Cyan
    & $python -m pip install -r $requirements
}

Write-Host "Initializing database..." -ForegroundColor Cyan
& $python scripts\init_db.py

$actualPort = Find-FreePort -StartPort $Port
$url = "http://127.0.0.1:$actualPort/"

$server = Start-Process -FilePath $python `
    -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", $actualPort) `
    -WorkingDirectory $projectRoot `
    -NoNewWindow `
    -PassThru

try {
    Wait-ForHealth -Url $url.TrimEnd("/") -Process $server

    Write-Host ""
    Write-Host "ZFZS Anime Assistant is ready" -ForegroundColor Green
    Write-Host "URL: $url"
    Write-Host "API docs: http://127.0.0.1:$actualPort/docs"
    Write-Host "Close this window or press Ctrl+C to stop."
    Write-Host ""

    if (-not $NoBrowser) {
        Start-Process $url
    }

    Wait-Process -Id $server.Id
}
finally {
    if (-not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
}
