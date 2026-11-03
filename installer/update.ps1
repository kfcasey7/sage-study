# Started by the app when you click "Update and restart". Waits for the app to close, then installs the release's own
# installer over this copy. Your study data is kept in its separate folder. Runs hidden; details go to update.log.
param([Parameter(Mandatory)][string]$Tag, [int]$WaitPid = 0, [string]$DataDir = "")

$ErrorActionPreference = "Stop"
$GithubRepo = "kfcasey7/sage-study"
$Root = $PSScriptRoot
$Log = Join-Path $Root "update.log"
Start-Transcript -Path $Log -Force | Out-Null

try {
    if ($Tag -notmatch '^v\d+\.\d+\.\d+$') { throw "Unexpected version '$Tag'." }
    if ($WaitPid) { try { Wait-Process -Id $WaitPid -Timeout 60 -ErrorAction Stop } catch { } }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $work = Join-Path ([IO.Path]::GetTempPath()) ("sage-update-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        $zip = Join-Path $work "release.zip"
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$GithubRepo/archive/refs/tags/$Tag.zip" -OutFile $zip
        Expand-Archive -LiteralPath $zip -DestinationPath $work
        $folder = Get-ChildItem -LiteralPath $work -Directory | Select-Object -First 1
        $env:SAGE_INSTALL_NONINTERACTIVE = "1"
        $installArgs = @{}
        if ($DataDir) { $installArgs["DataDir"] = $DataDir }
        & (Join-Path $folder.FullName "installer\install.ps1") @installArgs
        if ($LASTEXITCODE -ne 0) { throw "The new version's installer failed." }
    } finally {
        Set-Location $Root
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
} catch {
    Write-Host "Update failed: $($_.Exception.Message)"
    Add-Type -AssemblyName PresentationFramework
    [void][Windows.MessageBox]::Show("Sage Study couldn't update: $($_.Exception.Message)`n`nYour study data is safe. To finish updating, download the newest version from https://github.com/$GithubRepo/releases and run Install.bat.", "Sage Study")
    $gui = Join-Path $Root "tools\sage-study\Scripts\sage-study-gui.exe"
    if (Test-Path $gui) {
        if ($DataDir) { Start-Process -FilePath $gui -ArgumentList @("--data-dir", $DataDir) } else { Start-Process -FilePath $gui }
    }
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
