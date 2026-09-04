[CmdletBinding()]
param(
    [string]$ShortcutName = ([string]::Concat([char]0x9500, [char]0x552E, [char]0x6570, [char]0x636E, [char]0x770B, [char]0x677F))
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcherScript = Join-Path -Path $projectRoot -ChildPath 'scripts\dashboard_launcher.py'
$pythonw = Join-Path -Path $projectRoot -ChildPath '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $launcherScript -PathType Leaf)) {
    throw "找不到启动脚本：$launcherScript"
}
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "找不到无控制台 Python：$pythonw"
}

$desktop = [Environment]::GetFolderPath([System.Environment+SpecialFolder]::DesktopDirectory)
$shortcutPath = Join-Path -Path $desktop -ChildPath "$ShortcutName.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "`"$launcherScript`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'Launch the local sales dashboard'
$shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,15"
$shortcut.WindowStyle = 7
$shortcut.Save()

Write-Host "Desktop shortcut created: $shortcutPath"
