[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$NoInstall
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = & (Join-Path $PSScriptRoot 'run_desktop.ps1') -PrintPython -BuildDependencies -NoInstall:$NoInstall -PythonPath $PythonPath

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean --onedir --windowed --paths . --name 'ZFZS-Anime-Tracker' scripts\desktop_app.py
    if ($LASTEXITCODE -ne 0) { throw "Desktop build failed with exit code $LASTEXITCODE." }
    $bundle = Join-Path $projectRoot 'dist\ZFZS-Anime-Tracker'
    foreach ($relative in @('ZFZS-Anime-Tracker.exe', '_internal\_tkinter.pyd')) {
        if (-not (Test-Path -LiteralPath (Join-Path $bundle $relative) -PathType Leaf)) {
            throw "Incomplete desktop bundle: missing $relative"
        }
    }
    $verifyTk = @'
from pathlib import Path
import sys
from PyInstaller.utils.hooks.tcl_tk import tcltk_info
assert tcltk_info.available and not tcltk_info.tcl_data_missing and not tcltk_info.tk_data_missing
root = Path(sys.argv[1]) / '_internal'
missing = [name for name, _, _ in tcltk_info.data_files if not (root / name).is_file()]
assert not missing, f'Missing Tcl/Tk resources: {missing}'
'@
    & $python -I -B -c $verifyTk $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Incomplete Tcl/Tk bundle.' }
    Write-Host "Windows bundle verified: $bundle (distribute the entire folder, not just the .exe)." -ForegroundColor Green
}
finally { Pop-Location }
