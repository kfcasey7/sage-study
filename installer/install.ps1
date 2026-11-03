# Sage Study installer for Windows. Run it through Install.bat. Safe to run again: running it again repairs the app.
#
# Everything goes in one folder of its own: a private copy of uv, the Python it provides, and the app. Your PATH, any
# Python you already have, and any uv you already have stay untouched. Your study data is kept elsewhere and never touched.
#
#   -DataDir <folder>   keep study data in this folder instead of the default
#   -NoLaunch           don't open the app afterwards
#
# SAGE_INSTALL_ROOT relocates the install folder and SAGE_INSTALL_NONINTERACTIVE=1 skips prompts (used by the tests).
param([string]$DataDir = "", [switch]$NoLaunch)

$ErrorActionPreference = "Stop"
$UvVersion = "0.13.6"
$PythonVersion = "3.13"
$AppName = "Sage Study"

$Repo = Split-Path -Parent $PSScriptRoot
$Root = if ($env:SAGE_INSTALL_ROOT) { $env:SAGE_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "Programs\SageStudy" }
$Bin = Join-Path $Root "bin"
$Uv = Join-Path $Bin "uv.exe"
$Scripts = Join-Path $Root "tools\sage-study\Scripts"
$Interactive = $env:SAGE_INSTALL_NONINTERACTIVE -ne "1"

function Say($text) { Write-Host $text }
function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Green }

function Stop-RunningApp {
    $running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith("$Root\", [StringComparison]::OrdinalIgnoreCase) })
    if ($running.Count -eq 0) { return }
    if ($Interactive) {
        Say "$AppName is open. Please close its window, then press Enter here."
        [void][Console]::ReadLine()
    }
    @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith("$Root\", [StringComparison]::OrdinalIgnoreCase) }) |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

function Install-Uv {
    if (Test-Path $Uv) {
        Say "   Already have uv."
        return
    }
    New-Item -ItemType Directory -Force -Path $Bin | Out-Null
    # UV_UNMANAGED_INSTALL: exactly this folder, with no PATH changes and no receipt left elsewhere.
    $env:UV_UNMANAGED_INSTALL = $Bin
    # The method from uv's own install docs, at a pinned version. It runs in a child PowerShell so nothing it sets leaks into this one.
    $command = "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; irm https://astral.sh/uv/$UvVersion/install.ps1 | iex"
    & powershell -NoProfile -ExecutionPolicy Bypass -Command $command
    if (-not (Test-Path $Uv)) { throw "uv didn't install." }
}

try {
    Say "Installing $AppName. This takes a few minutes the first time, and needs an internet connection."

    Step "Closing the app if it's open"
    Stop-RunningApp

    Step "Getting uv (it provides Python and the app's other parts)"
    Install-Uv

    # Everything uv touches stays inside the install folder, which is what makes uninstalling clean.
    $env:UV_TOOL_DIR = Join-Path $Root "tools"
    $env:UV_TOOL_BIN_DIR = $Bin
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Root "python"
    $env:UV_PYTHON_BIN_DIR = $Bin
    $env:UV_CACHE_DIR = Join-Path $Root "cache"
    $env:UV_PYTHON_PREFERENCE = "only-managed"
    $env:UV_PYTHON_INSTALL_REGISTRY = "0"
    $env:UV_NO_MODIFY_PATH = "1"

    Step "Installing $AppName"
    & $Uv tool install --quiet --force --reinstall --python $PythonVersion --constraints (Join-Path $Repo "constraints.txt") $Repo
    if ($LASTEXITCODE -ne 0) { throw "uv couldn't install the app (exit code $LASTEXITCODE)." }
    & $Uv cache clean --quiet
    $python = Join-Path $Scripts "python.exe"
    if (-not (Test-Path $python)) { throw "The app's environment is missing after installing." }

    Step "Creating the shortcuts"
    $marker = @{ installed_by = "installer"; data_dir = $DataDir } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $Root "sage-install.json"), $marker, (New-Object Text.UTF8Encoding($false)))
    Copy-Item (Join-Path $PSScriptRoot "uninstall.ps1") (Join-Path $Root "uninstall.ps1") -Force
    Copy-Item (Join-Path $PSScriptRoot "update.ps1") (Join-Path $Root "update.ps1") -Force
    $shortcutArgs = @("-m", "sage.shortcuts", "create")
    $appArgs = @()
    if ($DataDir) { $shortcutArgs += @("--data-dir", $DataDir); $appArgs = @("--data-dir", $DataDir) }
    & $python @shortcutArgs
    if ($LASTEXITCODE -ne 0) { throw "The shortcuts couldn't be created." }

    Step "Checking Claude Code"
    & (Join-Path $Scripts "sage-study.exe") @appArgs --check

    Write-Host ""
    Write-Host "All done! Open $AppName from your Desktop or the Start Menu." -ForegroundColor Green
    if (-not $NoLaunch) { Start-Process -FilePath (Join-Path $Scripts "sage-study-gui.exe") -ArgumentList $appArgs }
    exit 0
} catch {
    Write-Host ""
    Write-Host "The install didn't finish: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Your study data wasn't touched. Check your internet connection and run this again."
    Write-Host "If it keeps failing, see the Troubleshooting section of README.md."
    exit 1
}
