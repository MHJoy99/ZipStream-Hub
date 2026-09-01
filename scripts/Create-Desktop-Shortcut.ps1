# scripts/Create-Desktop-Shortcut.ps1
# Creates a clean desktop shortcut for ZipStream Hub with custom icon

$ErrorActionPreference = "Stop"

# Resolve root repo directory (one level up from scripts/)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = (Get-Item -LiteralPath $scriptDir).Parent.FullName

$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path -Path $desktopPath -ChildPath "ZipStream Hub.lnk"

# Target launcher (prefer VBS for silent background launch or BAT for console launcher)
$targetVbs = Join-Path -Path $rootDir -ChildPath "launch_zipstream.vbs"
$targetBat = Join-Path -Path $rootDir -ChildPath "Start-ZipStream.bat"
$iconPath = Join-Path -Path $rootDir -ChildPath "zipstream_icon.ico"

$wshShell = New-Object -ComObject WScript.Shell
$shortcut = $wshShell.CreateShortcut($shortcutPath)

if (Test-Path -LiteralPath $targetVbs) {
    $shortcut.TargetPath = "wscript.exe"
    $shortcut.Arguments = "`"$targetVbs`""
} elseif (Test-Path -LiteralPath $targetBat) {
    $shortcut.TargetPath = $targetBat
} else {
    $shortcut.TargetPath = Join-Path -Path $rootDir -ChildPath "control_panel.py"
}

$shortcut.WorkingDirectory = $rootDir
$shortcut.Description = "ZipStream Hub - Instant Virtual Remote ZIP Video Streaming Engine"

if (Test-Path -LiteralPath $iconPath) {
    $shortcut.IconLocation = "$iconPath,0"
}

$shortcut.Save()

Write-Host "[OK] Desktop shortcut successfully created: $shortcutPath" -ForegroundColor Green
