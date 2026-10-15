[CmdletBinding()]
param(
    [string]$Destination = [Environment]::GetFolderPath("DesktopDirectory"),
    [ValidateSet('Source', 'Packaged', 'Auto')]
    [string]$Mode = 'Auto'
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $projectRoot "start.bat"
$packagedApp = Join-Path $projectRoot "dist\ZFZS-Anime-Tracker\ZFZS-Anime-Tracker.exe"
$destinationPath = [IO.Path]::GetFullPath($Destination)

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Desktop launcher not found: $launcher"
}
if ($Mode -eq 'Packaged' -and -not (Test-Path -LiteralPath $packagedApp -PathType Leaf)) {
    throw "Packaged app not found: $packagedApp. Build it first or select -Mode Source."
}
if (-not (Test-Path -LiteralPath $destinationPath -PathType Container)) {
    New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
}

# Keep this script ASCII-compatible with Windows PowerShell 5.1.
$shortcutName = 'ZFZS ' + [char]0x8ffd + [char]0x756a + [char]0x52a9 + [char]0x624b + '.lnk'
$shortcutPath = Join-Path $destinationPath $shortcutName
$iconLibrary = Join-Path $env:SystemRoot "System32\imageres.dll"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.Arguments = '-Mode Source'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Open ZFZS native anime tracker"
$shortcut.IconLocation = "$iconLibrary,67"
if ($Mode -ne 'Source' -and (Test-Path -LiteralPath $packagedApp -PathType Leaf)) {
    $shortcut.TargetPath = $packagedApp
    $shortcut.Arguments = ""
    $shortcut.WorkingDirectory = Split-Path -Parent $packagedApp
    $shortcut.IconLocation = "$packagedApp,0"
}
$shortcut.WindowStyle = 1
$shortcut.Save()

if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    throw "Desktop shortcut was not created."
}

Write-Host "Desktop shortcut created:" -ForegroundColor Green
Write-Host $shortcutPath
Write-Host "Target: $($shortcut.TargetPath)"
Write-Host 'Auto selects the current packaged app if present; rerun with -Mode Source to follow source changes.'
