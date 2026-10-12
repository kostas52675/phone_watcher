# Creates the "Phone Watcher" desktop shortcut: an on/off toggle button.
# Run from the project root:  powershell -ExecutionPolicy Bypass -File .\create_shortcut.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$VenvPythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$IconPath = Join-Path $ProjectRoot "icon.ico"
$TogglePath = Join-Path $ProjectRoot "toggle.py"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment not found at $VenvPython. Create it first (see README.md Setup section)."
    exit 1
}
if (-not (Test-Path $VenvPythonw)) {
    Write-Error "pythonw.exe not found at $VenvPythonw."
    exit 1
}
if (-not (Test-Path $TogglePath)) {
    Write-Error "toggle.py not found at $TogglePath."
    exit 1
}

Write-Host "Generating tray/shortcut icon..."
& $VenvPython (Join-Path $ProjectRoot "make_icon.py")
if ($LASTEXITCODE -ne 0) {
    Write-Error "make_icon.py failed."
    exit 1
}

# Resolve the real Desktop folder programmatically -- this correctly follows OneDrive
# folder redirection and localized names (e.g. "Επιφάνεια εργασίας"), unlike a hardcoded
# "$env:USERPROFILE\Desktop" path.
$DesktopPath = [Environment]::GetFolderPath("Desktop")
if (-not (Test-Path $DesktopPath)) {
    Write-Error "Resolved Desktop path does not exist: $DesktopPath"
    exit 1
}

$ShortcutPath = Join-Path $DesktopPath "Phone Watcher.lnk"

$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $VenvPythonw
$Shortcut.Arguments = '"' + $TogglePath + '"'
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.IconLocation = $IconPath
$Shortcut.Description = "Toggle Phone Watcher on/off"
$Shortcut.Save()

Write-Host "Shortcut created at: $ShortcutPath"
Write-Host "Double-click it to start Phone Watcher; double-click again to stop it."
