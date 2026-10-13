$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$LogDir = Join-Path $RootDir "runtime_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Resolve-BackendPython {
    $portablePythonDir = Join-Path $RootDir ".runtime\python"
    $portablePython = Join-Path $portablePythonDir "python.exe"
    $portablePythonScripts = Join-Path $portablePythonDir "Scripts"
    if (Test-Path $portablePython) {
        foreach ($path in @($portablePythonDir, $portablePythonScripts)) {
            if (Test-Path $path) {
                $pathItems = $env:PATH -split ";"
                if (-not ($pathItems -contains $path)) {
                    $env:PATH = "$path;$env:PATH"
                }
            }
        }
        return $portablePython
    }

    $venvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }

    throw "Backend Python not found. Run deployment\windows\setup_env.ps1 first."
}

function Resolve-NpmCommand {
    $portableNpm = Join-Path $RootDir ".runtime\node\npm.cmd"
    $portableNodeDir = Join-Path $RootDir ".runtime\node"
    if (Test-Path $portableNpm) {
        $pathItems = $env:PATH -split ";"
        if (-not ($pathItems -contains $portableNodeDir)) {
            $env:PATH = "$portableNodeDir;$env:PATH"
        }
        return $portableNpm
    }
    $globalNpm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($globalNpm) {
        return $globalNpm.Source
    }
    throw "npm.cmd not found. Run deployment\windows\setup_env.ps1 first."
}

$BackendPython = Resolve-BackendPython
$NpmCommand = Resolve-NpmCommand

function Stop-PortProcess($Port) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force
        Start-Sleep -Seconds 1
    }
}

Stop-PortProcess 8000
Stop-PortProcess 5173

Write-Host "启动后端 http://127.0.0.1:8000" -ForegroundColor Cyan
Start-Process `
    -FilePath $BackendPython `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
    -WorkingDirectory $BackendDir `
    -RedirectStandardOutput (Join-Path $LogDir "backend.out.log") `
    -RedirectStandardError (Join-Path $LogDir "backend.err.log") `
    -WindowStyle Hidden

Write-Host "启动前端 http://127.0.0.1:5173" -ForegroundColor Cyan
Start-Process `
    -FilePath $NpmCommand `
    -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173") `
    -WorkingDirectory $FrontendDir `
    -RedirectStandardOutput (Join-Path $LogDir "frontend.out.log") `
    -RedirectStandardError (Join-Path $LogDir "frontend.err.log") `
    -WindowStyle Hidden

Start-Sleep -Seconds 5
Write-Host "项目已启动：" -ForegroundColor Green
Write-Host "前端：http://127.0.0.1:5173/"
Write-Host "后端：http://127.0.0.1:8000/api/health"
