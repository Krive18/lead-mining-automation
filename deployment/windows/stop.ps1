$ErrorActionPreference = "Stop"

foreach ($port in @(8000, 5173)) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force
        Write-Host "Stopped the process listening on port $port."
    }
}
