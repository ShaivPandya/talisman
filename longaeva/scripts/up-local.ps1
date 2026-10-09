# Start or stop Longaeva without Docker.
# Requires Python 3.12 or newer and Node.js 20.19 or newer.
param(
    [switch]$Down
)

$ErrorActionPreference = "Stop"
# A missing py -3.12 should fall through to the next interpreter, not abort.
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Find-Python312 {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
        if ($LASTEXITCODE -eq 0) {
            return @("py", "-3.12")
        }
    }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) {
            continue
        }
        & $name -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
        if ($LASTEXITCODE -eq 0) {
            return @($name)
        }
    }
    return @()
}

$python = @(Find-Python312)
if ($python.Count -eq 0) {
    [Console]::Error.WriteLine("Python 3.12 or newer is required.")
    exit 1
}

$scriptPath = Join-Path $Root "scripts\up_local.py"
$scriptArgs = @($scriptPath)
if ($Down) {
    $scriptArgs += "--down"
}
$exe = $python[0]
$prefix = @()
if ($python.Count -gt 1) {
    $prefix = $python[1..($python.Count - 1)]
}
& $exe @prefix @scriptArgs
exit $LASTEXITCODE
