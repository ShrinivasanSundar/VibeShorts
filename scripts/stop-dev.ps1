# Stop all background services listening on ports 8000 and 3000
$ports = @(8000, 3000)
$connections = Get-NetTCPConnection -LocalPort $ports -ErrorAction SilentlyContinue

if ($connections) {
    $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $pids) {
        if ($processId -and $processId -ne 0) {
            $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
            $name = if ($proc) { $proc.ProcessName } else { "Process" }
            Write-Host "Stopping $name (PID: $processId)..." -ForegroundColor Yellow
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "All services on ports $($ports -join ', ') stopped successfully." -ForegroundColor Green
} else {
    Write-Host "No active processes found listening on ports $($ports -join ', ')." -ForegroundColor Cyan
}
