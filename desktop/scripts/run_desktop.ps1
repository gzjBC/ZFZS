[CmdletBinding()]
param(
    [switch]$PrepareOnly,
    [switch]$PrintPython,
    [switch]$NoInstall,
    [switch]$BuildDependencies,
    [string]$PythonPath,
    [ValidateSet('Source', 'Packaged', 'Auto')]
    [string]$Mode = 'Source',
    [switch]$Console
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$projectRoot = Split-Path -Parent $PSScriptRoot
$localEnvironment = Join-Path $projectRoot '.venv'
$localPython = Join-Path $localEnvironment 'Scripts\python.exe'
$legacyPython = Join-Path (Split-Path -Parent $projectRoot) '.venv\Scripts\python.exe'
$packagedApp = Join-Path $projectRoot 'dist\ZFZS-Anime-Tracker\ZFZS-Anime-Tracker.exe'

# Do not create Tk() here: preparation must also work without a GUI session.
$probe = @'
import importlib.metadata as metadata
from pathlib import Path
import sys
assert sys.version_info[:2] == (3, 13), 'Python 3.13 is required'
import tkinter
tkinter.Tcl().eval('info patchlevel')
if sys.argv[1] != 'Base':
    import fastapi, uvicorn, sqlalchemy, pydantic, pydantic_settings, requests, playwright
    def check(path):
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('-r '):
                check(path.parent / line[3:].strip())
            else:
                name, expected = line.split('==', 1)
                assert metadata.version(name) == expected, f'{name} must be {expected}'
    check(Path(sys.argv[2]))
    if sys.argv[1] == 'Build':
        import PyInstaller
'@

function Test-DesktopPython {
    param([string]$Path, [string]$Scope = 'Runtime', [string[]]$Prefix = @())
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $requirements = Join-Path $projectRoot 'requirements.txt'
    if ($Scope -eq 'Build') { $requirements = Join-Path $projectRoot 'requirements-dev.txt' }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Path @Prefix -I -B -c $probe $Scope $requirements 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    }
    catch { return $false }
    finally { $ErrorActionPreference = $previousPreference }
}

if ($PrintPython) { $PrepareOnly = $true }
if ($PrepareOnly -and $Mode -ne 'Source') {
    throw 'Preparation checks source Python only. Use -Mode Source (the default).'
}

if ($Mode -eq 'Packaged' -or ($Mode -eq 'Auto' -and (Test-Path -LiteralPath $packagedApp -PathType Leaf))) {
    if (-not (Test-Path -LiteralPath $packagedApp -PathType Leaf)) {
        throw "Packaged app not found: $packagedApp. Build it first, or use -Mode Source."
    }
    Start-Process -FilePath $packagedApp -WorkingDirectory (Split-Path -Parent $packagedApp) -WindowStyle Hidden
    return
}

# Resolve caller-relative explicit paths before changing the working directory.
if ($PythonPath) {
    $python = (Resolve-Path -LiteralPath $PythonPath -ErrorAction Stop).Path
    if (-not (Test-DesktopPython $python 'Base')) {
        throw "Invalid Python: $python. Python 3.13 with working tkinter/Tcl is required."
    }
}
elseif (Test-DesktopPython $localPython) { $python = $localPython }
elseif (Test-DesktopPython $legacyPython) {
    $python = $legacyPython
    Write-Host 'Using the migration-compatible repository .venv.' -ForegroundColor DarkGray
}
else {
    if ($NoInstall) {
        throw 'No ready Python 3.13/Tk environment. Run run_desktop.ps1 -PrepareOnly without -NoInstall to prepare desktop/.venv.'
    }
    if (-not (Test-DesktopPython $localPython 'Base')) {
        $basePython = $null
        $baseArguments = @()
        foreach ($candidate in @('py', 'python3.13', 'python')) {
            $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $command) { continue }
            $prefix = @()
            if ($candidate -eq 'py') { $prefix = @('-3.13') }
            if (Test-DesktopPython $command.Source 'Base' $prefix) {
                $basePython = $command.Source
                $baseArguments = $prefix
                break
            }
        }
        if (-not $basePython) { throw 'Install Python 3.13 with Tcl/Tk support, then rerun. pip cannot install tkinter.' }
        if (Test-Path -LiteralPath $localEnvironment) {
            # Preserve a broken/incompatible environment; never clear user files.
            $resolved = (Resolve-Path -LiteralPath $localEnvironment).Path
            if ($resolved -ne [IO.Path]::GetFullPath($localEnvironment)) { throw 'Unexpected virtual environment path.' }
            $backup = Join-Path $projectRoot ('.venv.backup-' + [guid]::NewGuid().ToString('N'))
            Write-Host "Preserving the old environment at $backup"
            Move-Item -LiteralPath $resolved -Destination $backup
        }
        & $basePython @baseArguments -m venv $localEnvironment | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Could not create desktop/.venv.' }
        if (-not (Test-DesktopPython $localPython 'Base')) { throw 'The new environment cannot load Python 3.13/Tk.' }
    }
    $python = $localPython
}

$scope = 'Runtime'
$requirements = Join-Path $projectRoot 'requirements.txt'
if ($BuildDependencies) {
    $scope = 'Build'
    $requirements = Join-Path $projectRoot 'requirements-dev.txt'
}
if (-not (Test-DesktopPython $python $scope)) {
    if ($NoInstall) { throw "Missing or mismatched $scope dependencies in $python. Omit -NoInstall to repair them." }
    & $python -m ensurepip --upgrade | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare pip.' }
    & $python -m pip install -r $requirements | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    if (-not (Test-DesktopPython $python $scope)) { throw 'Python/Tk/dependency verification failed after installation.' }
}

if ($PrintPython) { Write-Output $python; return }
Write-Host "Python: $python" -ForegroundColor DarkGray
if ($PrepareOnly) {
    Write-Host 'Desktop environment is ready (no GUI was opened).' -ForegroundColor Green
    return
}

if ($Console) {
    Push-Location $projectRoot
    try {
        & $python (Join-Path $PSScriptRoot 'desktop_app.py')
        if ($LASTEXITCODE -ne 0) { throw "Desktop application failed with exit code $LASTEXITCODE." }
    }
    finally { Pop-Location }
}
else {
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw 'pythonw.exe is missing. Use -Console to diagnose this environment.' }
    Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $PSScriptRoot 'desktop_app.py') + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden
}
