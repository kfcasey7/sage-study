# Removes Sage Study: the app, its environment, and its shortcuts. Asks before deleting your study data.
#
#   -DeleteData / -KeepData   answer the question up front
#
# SAGE_INSTALL_ROOT relocates the install folder (used by the tests).
param([switch]$DeleteData, [switch]$KeepData)

$ErrorActionPreference = "Stop"
$AppName = "Sage Study"
$Root = if ($env:SAGE_INSTALL_ROOT) { $env:SAGE_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "Programs\SageStudy" }
$python = Join-Path $Root "tools\sage-study\Scripts\python.exe"

if (-not (Test-Path $Root)) {
    Write-Host "$AppName isn't installed here, so there's nothing to remove."
    exit 0
}

Write-Host "Removing $AppName..."
@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith("$Root\", [StringComparison]::OrdinalIgnoreCase) }) |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# The data folder: the one chosen at install time, otherwise wherever the app says its default is.
$customData = ""
try { $customData = [string](Get-Content (Join-Path $Root "sage-install.json") -Raw | ConvertFrom-Json).data_dir } catch { }
$dataDir = $customData
$pythonWorks = Test-Path $python
if (-not $dataDir -and $pythonWorks) { $dataDir = (& $python -m sage.cli --print-data-dir | Select-Object -Last 1) }

if ($pythonWorks) {
    & $python -m sage.shortcuts remove | Out-Null
    # Only the default data folder owns the saved YouTube key.
    $forgetKey = $DeleteData -and -not $customData
}

$delete = [bool]$DeleteData
if ($dataDir -and (Test-Path $dataDir) -and -not $DeleteData -and -not $KeepData) {
    Write-Host ""
    Write-Host "Your study data (quizzes, study guides, uploaded files) is in:"
    Write-Host "   $dataDir"
    $answer = Read-Host "Delete it too? This can't be undone. Type yes to delete, or press Enter to keep it"
    $delete = $answer -eq "yes"
    if ($pythonWorks) { $forgetKey = $delete -and -not $customData }
}
if ($forgetKey) { & $python -m sage.cli --forget-youtube-key | Out-Null }

Set-Location $env:TEMP  # Windows won't delete the folder a script is running in
Remove-Item -LiteralPath $Root -Recurse -Force

if ($delete -and $dataDir -and (Test-Path $dataDir)) {
    Remove-Item -LiteralPath $dataDir -Recurse -Force
    Write-Host "Removed $AppName and your study data."
} else {
    Write-Host "Removed $AppName."
    if ($dataDir -and (Test-Path $dataDir)) { Write-Host "Your study data is still in: $dataDir" }
}
exit 0
