param(
    [string]$OutputDir = "",
    [string]$PackageName = ""
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $RootDir "release"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$resolvedOutputDir = (Resolve-Path $OutputDir).Path
$packageName = $PackageName.Trim()
if ([string]::IsNullOrWhiteSpace($packageName)) {
    $packageName = "lead-mining-windows-deploy-" + (Get-Date -Format "yyyyMMdd-HHmmss")
}
if ($packageName.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
    throw "PackageName contains invalid filename characters: $packageName"
}
$stageDir = Join-Path $resolvedOutputDir $packageName
$zipPath = Join-Path $resolvedOutputDir "$packageName.zip"

if (Test-Path $stageDir) {
    $resolvedStageDir = (Resolve-Path $stageDir).Path
    if (-not $resolvedStageDir.StartsWith($resolvedOutputDir, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected stage directory: $resolvedStageDir"
    }
    Remove-Item -LiteralPath $resolvedStageDir -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

$excludeDirs = @(
    (Join-Path $RootDir ".agents"),
    (Join-Path $RootDir ".codex"),
    (Join-Path $RootDir ".codex-tmp"),
    (Join-Path $RootDir ".git"),
    (Join-Path $RootDir ".pytest_cache"),
    (Join-Path $RootDir ".runtime"),
    (Join-Path $RootDir ".superpowers"),
    (Join-Path $RootDir "artifacts"),
    ".pytest_cache",
    "__pycache__",
    (Join-Path $RootDir "release"),
    (Join-Path $RootDir "runtime_logs"),
    (Join-Path $RootDir "tmp"),
    (Join-Path $RootDir "backend\.runtime"),
    (Join-Path $RootDir "backend\.venv"),
    (Join-Path $RootDir "backend\data"),
    (Join-Path $RootDir "backend\exports"),
    (Join-Path $RootDir "backend\logs"),
    (Join-Path $RootDir "frontend\.runtime"),
    (Join-Path $RootDir "frontend\node_modules"),
    (Join-Path $RootDir "frontend\dist")
)

$excludeFiles = @(
    ".env",
    "*.pyc",
    "*.pyo",
    "*.log",
    "lead_mining.db",
    "lead_mining.db-*"
)

Write-Host "Copying project files into package stage..." -ForegroundColor Cyan
$robocopyArgs = @(
    $RootDir,
    $stageDir,
    "/E",
    "/XD"
) + $excludeDirs + @(
    "/XF"
) + $excludeFiles + @(
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP"
)

& robocopy @robocopyArgs | Out-Null
$robocopyExitCode = $LASTEXITCODE
if ($robocopyExitCode -gt 7) {
    throw "robocopy failed with exit code $robocopyExitCode"
}

$manifestPath = Join-Path $stageDir ".deploy_manifest.txt"
$manifest = @(
    "Lead Mining Windows deployment package",
    "GeneratedAt=$(Get-Date -Format "yyyy-MM-dd HH:mm:ss")",
    "DefaultDatabase=SQLite",
    "SetupScript=deployment\windows\setup_env.ps1",
    "StartScript=start_project.bat"
) -join [Environment]::NewLine
[System.IO.File]::WriteAllText($manifestPath, $manifest, [System.Text.UTF8Encoding]::new($false))

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

Write-Host "Creating zip package..." -ForegroundColor Cyan
Compress-Archive -LiteralPath $stageDir -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Deployment package created:" -ForegroundColor Green
Write-Host $zipPath
