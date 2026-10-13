$ErrorActionPreference = "Stop"

$SetupScript = Join-Path $PSScriptRoot "setup_env.ps1"
if (-not (Test-Path $SetupScript)) {
    throw "Missing setup script: $SetupScript"
}

& $SetupScript
