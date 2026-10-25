[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$DistPath,
    [switch]$NoInstall
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $DistPath) { $DistPath = Join-Path $projectRoot 'dist' }
elseif (-not [IO.Path]::IsPathRooted($DistPath)) { $DistPath = Join-Path $projectRoot $DistPath }
$DistPath = [IO.Path]::GetFullPath($DistPath)
$projectPrefix = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
if (-not $DistPath.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build output must be a subdirectory of the desktop project.'
}
$bundle = Join-Path $DistPath 'ZFZS-Anime-Tracker'
$executable = Join-Path $bundle 'ZFZS-Anime-Tracker.exe'
$python = & (Join-Path $PSScriptRoot 'run_desktop.ps1') -PrintPython -BuildDependencies -NoInstall:$NoInstall -PythonPath $PythonPath

# Do not let PyInstaller replace files that a desktop window/worker still uses.
$running = Get-Process -Name 'ZFZS-Anime-Tracker' -ErrorAction SilentlyContinue |
    Where-Object { -not $_.Path -or $_.Path -eq $executable }
if ($running) {
    throw 'Close ZFZS and stop its background reminder worker before rebuilding.'
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean --onedir --windowed --paths . --distpath $DistPath --name 'ZFZS-Anime-Tracker' scripts\desktop_app.py
    if ($LASTEXITCODE -ne 0) { throw "Desktop build failed with exit code $LASTEXITCODE." }
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
assert any((root / 'PIL').glob('_imaging*.pyd')), 'Missing Pillow image decoder'
assert (root / 'certifi' / 'cacert.pem').is_file(), 'Missing portable TLS certificates'
missing = [name for name, _, _ in tcltk_info.data_files if not (root / name).is_file()]
assert not missing, f'Missing Tcl/Tk resources: {missing}'
'@
    & $python -I -B -c $verifyTk $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Incomplete Tcl/Tk bundle.' }
    Write-Host "Windows bundle verified: $bundle (distribute the entire folder, not just the .exe)." -ForegroundColor Green
}
finally { Pop-Location }
