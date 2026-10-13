param(
    [switch]$ResetEnv,
    [switch]$SkipBrowserInstall,
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RootDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$RuntimeDir = Join-Path $RootDir ".runtime"
$DownloadDir = Join-Path $RuntimeDir "downloads"
$PythonDir = Join-Path $RuntimeDir "python"
$NodeDir = Join-Path $RuntimeDir "node"

$PythonVersion = "3.12.4"
$NodeVersion = "20.15.1"
$PythonZipUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$NodeZipUrl = "https://nodejs.org/dist/v$NodeVersion/node-v$NodeVersion-win-x64.zip"

function Assert-DeploymentLayout {
    $requiredPathList = @(
        (Join-Path $BackendDir "requirements.txt"),
        (Join-Path $BackendDir ".env.example"),
        (Join-Path $FrontendDir "package.json")
    )
    $missingPathList = @($requiredPathList | Where-Object { -not (Test-Path $_) })
    if ($missingPathList.Count -gt 0) {
        throw "Deployment package is incomplete. Extract the entire ZIP before setup. Missing: $($missingPathList -join ', ')"
    }
}

function Ensure-Directory($Path) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Remove-DirectoryIfExists($Path) {
    if (-not (Test-Path $Path)) {
        return
    }
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        }
        catch {
            if ($attempt -eq 3) {
                throw
            }
            Start-Sleep -Milliseconds 500
        }
    }
}

function Expand-ZipFresh($ZipPath, $DestinationPath) {
    Assert-ZipArchive $ZipPath
    Remove-DirectoryIfExists $DestinationPath
    Ensure-Directory $DestinationPath
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $DestinationPath)
}

function Test-ZipArchive($ZipPath) {
    if (-not (Test-Path $ZipPath)) {
        return $false
    }
    $fileItem = Get-Item -LiteralPath $ZipPath
    if ($fileItem.Length -le 100KB) {
        return $false
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = $null
    try {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        return $archive.Entries.Count -gt 0
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $archive) {
            $archive.Dispose()
        }
    }
}

function Assert-ZipArchive($ZipPath) {
    if (-not (Test-ZipArchive $ZipPath)) {
        if (Test-Path $ZipPath) {
            Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
        }
        throw "Downloaded archive is not a valid zip file and has been removed: $ZipPath. Please run setup again; if it repeats, check network/proxy or download blocking."
    }
}

function Download-FileFresh($Url, $Destination) {
    $tempDestination = "$Destination.download"
    if (Test-Path $tempDestination) {
        Remove-Item -LiteralPath $tempDestination -Force
    }
    Invoke-WebRequest -Uri $Url -OutFile $tempDestination -UseBasicParsing
    if (-not (Test-Path $tempDestination)) {
        throw "Download did not create file: $Destination"
    }
    Move-Item -LiteralPath $tempDestination -Destination $Destination -Force
}

function Download-FileIfMissing($Url, $Destination) {
    $isZipFile = [System.IO.Path]::GetExtension($Destination).Equals(".zip", [System.StringComparison]::OrdinalIgnoreCase)
    if (Test-Path $Destination) {
        $downloadedFile = Get-Item -LiteralPath $Destination
        if ($isZipFile -and (Test-ZipArchive $Destination)) {
            Write-Host "Using cached download: $Destination" -ForegroundColor DarkGray
            return
        }
        if ((-not $isZipFile) -and $downloadedFile.Length -gt 100KB) {
            Write-Host "Using cached download: $Destination" -ForegroundColor DarkGray
            return
        }
        Write-Host "Removing invalid cached download: $Destination" -ForegroundColor Yellow
        Remove-Item -LiteralPath $Destination -Force
    }
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Write-Host "Downloading ($attempt/3): $Url" -ForegroundColor Cyan
            Download-FileFresh $Url $Destination
            if ($isZipFile) {
                Assert-ZipArchive $Destination
            }
            return
        }
        catch {
            if (Test-Path $Destination) {
                Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
            }
            if ($attempt -eq 3) {
                throw
            }
            Write-Host "Download failed or file was incomplete. Retrying..." -ForegroundColor Yellow
            Start-Sleep -Seconds 2
        }
    }
}

function Assert-LastExitCode($Message) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Message failed with exit code $LASTEXITCODE"
    }
}

function Use-PortableNodePath {
    $nodeExe = Join-Path $NodeDir "node.exe"
    $npmCmd = Join-Path $NodeDir "npm.cmd"
    if ((Test-Path $nodeExe) -and (Test-Path $npmCmd)) {
        $pathItems = $env:PATH -split ";"
        if (-not ($pathItems -contains $NodeDir)) {
            $env:PATH = "$NodeDir;$env:PATH"
        }
    }
}

function Use-PortablePythonPath {
    $pythonScriptsDir = Join-Path $PythonDir "Scripts"
    foreach ($path in @($PythonDir, $pythonScriptsDir)) {
        if (Test-Path $path) {
            $pathItems = $env:PATH -split ";"
            if (-not ($pathItems -contains $path)) {
                $env:PATH = "$path;$env:PATH"
            }
        }
    }
}

function Find-SystemEdgeExecutable {
    $candidatePathList = @()
    foreach ($baseDir in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if (-not [string]::IsNullOrWhiteSpace($baseDir)) {
            $candidatePathList += Join-Path $baseDir "Microsoft\Edge\Application\msedge.exe"
        }
    }
    foreach ($candidatePath in $candidatePathList) {
        if (Test-Path -LiteralPath $candidatePath) {
            return $candidatePath
        }
    }
    $edgeCommand = Get-Command "msedge.exe" -ErrorAction SilentlyContinue
    if ($edgeCommand) {
        return $edgeCommand.Source
    }
    return ""
}

function Enable-EmbeddedPythonSitePackages {
    $pthFile = Get-ChildItem -LiteralPath $PythonDir -Filter "python*._pth" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $pthFile) {
        return
    }
    $content = Get-Content -LiteralPath $pthFile.FullName -Raw -Encoding UTF8
    if ($content -match "(?m)^#import site\s*$") {
        $content = [regex]::Replace($content, "(?m)^#import site\s*$", "import site")
    }
    elseif ($content -notmatch "(?m)^import site\s*$") {
        $content = $content.TrimEnd() + [Environment]::NewLine + "import site" + [Environment]::NewLine
    }
    [System.IO.File]::WriteAllText($pthFile.FullName, $content, [System.Text.UTF8Encoding]::new($false))
}

function Ensure-PortablePip($PythonExe) {
    $pipModulePath = Join-Path $PythonDir "Lib\site-packages\pip\__init__.py"
    if (Test-Path $pipModulePath) {
        return
    }

    $getPipPath = Join-Path $DownloadDir "get-pip.py"
    Download-FileIfMissing $GetPipUrl $getPipPath
    Write-Host "Installing pip into embedded Python..." -ForegroundColor Cyan
    & $PythonExe $getPipPath --no-warn-script-location | Out-Host
    Assert-LastExitCode "Install pip"

    if (-not (Test-Path $pipModulePath)) {
        throw "pip installation finished but pip module was not found: $pipModulePath"
    }
}

function Reset-PortablePythonIfBroken {
    $pythonExe = Join-Path $PythonDir "python.exe"
    if ((Test-Path $PythonDir) -and (-not (Test-Path $pythonExe))) {
        $resolvedPythonDir = (Resolve-Path $PythonDir).Path
        $resolvedRuntimeDir = (Resolve-Path $RuntimeDir).Path
        if (-not $resolvedPythonDir.StartsWith($resolvedRuntimeDir, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean unexpected Python directory: $resolvedPythonDir"
        }
        Write-Host "Removing incomplete Python runtime: $PythonDir" -ForegroundColor Yellow
        Remove-Item -LiteralPath $PythonDir -Recurse -Force
    }
}

function Install-PortablePython {
    Reset-PortablePythonIfBroken

    $pythonExe = Join-Path $PythonDir "python.exe"
    if (-not (Test-Path $pythonExe)) {
        Ensure-Directory $RuntimeDir
        $zipPath = Join-Path $DownloadDir "python-$PythonVersion-embed-amd64.zip"
        Download-FileIfMissing $PythonZipUrl $zipPath

        Write-Host "Extracting embedded Python $PythonVersion into project runtime..." -ForegroundColor Cyan
        Expand-ZipFresh $zipPath $PythonDir
    }

    if (-not (Test-Path $pythonExe)) {
        throw "Embedded Python extraction finished but python.exe was not found: $pythonExe"
    }

    Enable-EmbeddedPythonSitePackages
    Use-PortablePythonPath
    & $pythonExe -c "import sys; print(sys.version)" | Out-Host
    Assert-LastExitCode "Check embedded Python"
    Ensure-PortablePip $pythonExe | Out-Host
    Write-Host "Embedded Python ready: $pythonExe" -ForegroundColor Green
    return $pythonExe
}

function Install-PortableNode {
    $npmCmd = Join-Path $NodeDir "npm.cmd"
    if (Test-Path $npmCmd) {
        Write-Host "Node.js already installed: $NodeDir" -ForegroundColor Green
        return $npmCmd
    }

    Ensure-Directory $RuntimeDir
    $zipPath = Join-Path $DownloadDir "node-v$NodeVersion-win-x64.zip"
    Download-FileIfMissing $NodeZipUrl $zipPath

    $extractDir = Join-Path $RuntimeDir "node_extract"
    Remove-DirectoryIfExists $extractDir
    Remove-DirectoryIfExists $NodeDir

    Write-Host "Extracting Node.js $NodeVersion into project runtime..." -ForegroundColor Cyan
    Expand-ZipFresh $zipPath $extractDir
    $nodeRoot = Get-ChildItem -LiteralPath $extractDir -Directory | Select-Object -First 1
    if (-not $nodeRoot) {
        throw "Node.js archive did not contain an extracted directory."
    }
    Move-Item -LiteralPath $nodeRoot.FullName -Destination $NodeDir
    Remove-DirectoryIfExists $extractDir

    if (-not (Test-Path $npmCmd)) {
        throw "Node.js installation finished but npm.cmd was not found: $npmCmd"
    }
    Use-PortableNodePath
    return $npmCmd
}

function Write-EnvironmentFile {
    $envPath = Join-Path $BackendDir ".env"
    $examplePath = Join-Path $BackendDir ".env.example"
    if ((Test-Path $envPath) -and (-not $ResetEnv)) {
        Write-Host "Keeping existing backend\.env. Use -ResetEnv to recreate it." -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path $examplePath)) {
        throw "Missing env template: $examplePath"
    }

    $content = Get-Content -LiteralPath $examplePath -Raw -Encoding UTF8
    $content = [regex]::Replace($content, "(?m)^LEAD_DATABASE_DRIVER=.*$", "LEAD_DATABASE_DRIVER=sqlite")
    $content = [regex]::Replace($content, "(?m)^LEAD_DATABASE_PATH=.*$", "LEAD_DATABASE_PATH=backend/data/lead_mining.db")
    $content = [regex]::Replace($content, "(?m)^LEAD_EXPORT_DIR=.*$", "LEAD_EXPORT_DIR=backend/exports")

    [System.IO.File]::WriteAllText($envPath, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Created backend\.env for SQLite local deployment." -ForegroundColor Green
}

function Install-BackendDependencies($PythonExe) {
    Write-Host "Installing backend Python dependencies..." -ForegroundColor Cyan
    Use-PortablePythonPath
    & $PythonExe -m pip install --upgrade pip
    Assert-LastExitCode "Upgrade pip"
    & $PythonExe -m pip install -r (Join-Path $BackendDir "requirements.txt")
    Assert-LastExitCode "Install backend requirements"

    if (-not $SkipBrowserInstall) {
        Write-Host "Installing Playwright Chromium browser fallback..." -ForegroundColor Cyan
        & $PythonExe -m playwright install chromium
        Assert-LastExitCode "Install Playwright Chromium"

        $edgeExecutable = Find-SystemEdgeExecutable
        if ($edgeExecutable) {
            Write-Host "Using installed Microsoft Edge: $edgeExecutable" -ForegroundColor Green
        }
        else {
            Write-Host "Microsoft Edge was not detected. The app will use Playwright Chromium fallback." -ForegroundColor Yellow
        }
    }
}

function Install-FrontendDependencies($NpmCmd) {
    Write-Host "Installing frontend npm dependencies..." -ForegroundColor Cyan
    Use-PortableNodePath
    & (Join-Path $NodeDir "node.exe") --version
    Assert-LastExitCode "Check portable Node"
    Push-Location $FrontendDir
    try {
        & $NpmCmd install
        Assert-LastExitCode "npm install"
        & $NpmCmd run build
        Assert-LastExitCode "npm run build"
    }
    finally {
        Pop-Location
    }
}

Assert-DeploymentLayout
if ($PreflightOnly) {
    Write-Host "Preflight passed: deployment layout and PowerShell launcher are available." -ForegroundColor Green
    exit 0
}

Ensure-Directory $RuntimeDir
Ensure-Directory $DownloadDir
Ensure-Directory (Join-Path $BackendDir "data")
Ensure-Directory (Join-Path $BackendDir "exports")
$RuntimeLogDir = Join-Path $RootDir "runtime_logs"
Ensure-Directory $RuntimeLogDir
$SetupLogPath = Join-Path $RuntimeLogDir "setup_environment.log"
try {
    Start-Transcript -Path $SetupLogPath -Append | Out-Null
}
catch {
    Write-Host "Could not start setup transcript: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host "== Lead Mining environment setup ==" -ForegroundColor Cyan
Write-Host "Project: $RootDir" -ForegroundColor DarkGray

$pythonExe = Install-PortablePython
$npmCmd = Install-PortableNode
Write-EnvironmentFile
Install-BackendDependencies $pythonExe
Install-FrontendDependencies $npmCmd

Write-Host ""
Write-Host "Environment setup completed." -ForegroundColor Green
Write-Host "Start the project with start_project.bat or deployment\windows\start.bat" -ForegroundColor Green
try {
    Stop-Transcript | Out-Null
}
catch {
    # No transcript was active.
}
