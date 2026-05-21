# Fleet Management import status helper.
# Prints DB state, table counts, import progress, and disk usage.
#
# Usage:
#   .\scripts\fleetmgmt_status.ps1
#   .\scripts\fleetmgmt_status.ps1 -Tail     # also tail recent log lines

param(
    [switch]$Tail
)

$ErrorActionPreference = 'Stop'
$container = 'krai-fleetmgmt-mssql'
$db        = 'DevFleetMgmt'

# Try to load .env to grab MSSQL_SA_PASSWORD
$envFile = Join-Path $PSScriptRoot '..\.env'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^MSSQL_SA_PASSWORD=(.+)$') {
            $env:MSSQL_SA_PASSWORD = $matches[1].Trim()
        }
    }
}
if (-not $env:MSSQL_SA_PASSWORD) {
    Write-Error "MSSQL_SA_PASSWORD not found in .env"
    exit 1
}
$pw = $env:MSSQL_SA_PASSWORD

Write-Host "==========================================="
Write-Host "Fleet Management Import Status"
Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "==========================================="

# Container
$state = docker ps --filter "name=$container" --format "{{.Status}}" 2>$null
if (-not $state) {
    Write-Host "Container NOT running. Start with:"
    Write-Host "  docker compose -f docker-compose.fleetmgmt.yml up -d"
    exit 0
}
Write-Host ("Container: {0} ({1})" -f $container, $state)

# Process state
$procs = docker exec $container pgrep -af "sqlcmd|import.sh" 2>$null
if ($procs) {
    Write-Host ""
    Write-Host "Import process(es):"
    $procs | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Host ""
    Write-Host "No sqlcmd/import.sh running (import probably finished or not started)."
}

# DB state
Write-Host ""
Write-Host "--- Database ---"
docker exec $container /opt/mssql-tools18/bin/sqlcmd `
    -S localhost -U sa -P $pw -C -h -1 -W -s '|' `
    -Q "SET NOCOUNT ON;
        SELECT name, state_desc, recovery_model_desc,
               CONVERT(varchar(19), create_date, 120) AS created
          FROM sys.databases WHERE name = '$db';" 2>&1

# Tables + total rows + size
Write-Host ""
Write-Host "--- Tables / Rows / Size ---"
docker exec $container /opt/mssql-tools18/bin/sqlcmd `
    -S localhost -U sa -P $pw -C -d $db -h -1 -W -s ' | ' `
    -Q "SET NOCOUNT ON;
        SELECT
            CONCAT(
                'tables=',      COUNT(*), ' | ',
                'total_rows=',  ISNULL(SUM(p.row_count), 0), ' | ',
                'data_mb=',     (SELECT SUM(size) * 8 / 1024 FROM sys.master_files
                                  WHERE database_id = DB_ID() AND type = 0), ' | ',
                'log_mb=',      (SELECT SUM(size) * 8 / 1024 FROM sys.master_files
                                  WHERE database_id = DB_ID() AND type = 1)
            ) AS status
          FROM sys.tables t
          LEFT JOIN sys.dm_db_partition_stats p
                 ON t.object_id = p.object_id AND p.index_id < 2;" 2>&1 |
    Select-Object -First 5

# Top 10 tables by row count
Write-Host ""
Write-Host "--- Top 15 tables (by row count so far) ---"
docker exec $container /opt/mssql-tools18/bin/sqlcmd `
    -S localhost -U sa -P $pw -C -d $db -h -1 -W `
    -Q "SET NOCOUNT ON;
        SELECT TOP 15 t.name AS [Table], p.row_count AS [Rows]
          FROM sys.tables t
          LEFT JOIN sys.dm_db_partition_stats p
                 ON t.object_id = p.object_id AND p.index_id < 2
         WHERE p.row_count > 0
         ORDER BY p.row_count DESC;" 2>&1

# Tail recent log lines
if ($Tail) {
    Write-Host ""
    Write-Host "--- Last 30 log lines ---"
    $latest = docker exec $container bash -c 'ls -1t /logs/import_*.log 2>/dev/null | head -1' 2>$null
    if ($latest) {
        docker exec $container tail -30 $latest 2>&1
    } else {
        Write-Host "No log files yet."
    }
}

# Disk space on host
Write-Host ""
Write-Host "--- Host disk (C:) ---"
$disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
$freeGB = [math]::Round($disk.FreeSpace / 1GB, 1)
$sizeGB = [math]::Round($disk.Size / 1GB, 1)
$usedGB = $sizeGB - $freeGB
Write-Host ("C:  {0} GB free of {1} GB ({2} GB used)" -f $freeGB, $sizeGB, $usedGB)
