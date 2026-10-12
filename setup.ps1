# Sage Study setup for Windows. Usage (from this folder):
#   powershell -ExecutionPolicy Bypass -File setup.ps1 [--no-shortcut] [--skip-frontend]
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("3.13", "3.12", "3.11")) { $candidates += ,@("py", "-$v") }
    }
    $candidates += ,@("python")
    $candidates += ,@("python3")
    foreach ($c in $candidates) {
        try {
            $exe = $c[0]; $rest = @($c | Select-Object -Skip 1)
            $ok = & $exe @rest -c "import sys; print(sys.version_info >= (3, 11))" 2>$null
            if ($ok -eq "True") { return ,$c }
        } catch { }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ and run setup again." -ForegroundColor Red
    exit 1
}
$exe = $py[0]; $rest = @($py | Select-Object -Skip 1)
& $exe @rest scripts/setup.py @args
exit $LASTEXITCODE
