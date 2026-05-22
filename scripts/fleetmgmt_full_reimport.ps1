<#
Full from-dump re-import of DevFleetMgmt (overnight, detached).

Pipeline:
  A. Extract from C:\Transferr\sql.sql (160 GB UTF-16):
       1. sql_dump_filter_bigtables.py  -> work/bigtables_data.sql
       2. sql_to_tsv_parallel.py        -> work/accsnmphistory.tsv + accmibcountervalues.tsv
       3. sql_dump_filter_nonbig.py     -> work/nonbig.sql  (schema + small/mid data)
  B. VALIDATION GATE: TSV row counts must match the baseline (48,074,445 +
     12,449,058) within tolerance. If NOT, ABORT and leave the current DB
     untouched (no wipe).
  C. Load into a FRESH DevFleetMgmt:
       wipe -> sqlcmd -i nonbig.sql -> BULK big tables -> missing_data.sql
       -> recreate krai_readonly -> verify counts.

Safety net: a botched run is recoverable in 38 s from
database/fleetmgmt/backups/DevFleetMgmt_20260520.bak.
Run:  pwsh -File scripts/fleetmgmt_full_reimport.ps1   (launched detached)
#>
$ErrorActionPreference = 'Continue'
$root  = 'C:\Github\KRAI-Insights'
$work  = "$root\database\fleetmgmt\work"
$tools = "$root\database\fleetmgmt\tools"
$py    = "$root\.venv\Scripts\python.exe"
$ctr   = 'krai-fleetmgmt-mssql'
$log   = "$work\reimport_master.log"

New-Item -ItemType Directory -Force $work | Out-Null
$env:FM_DUMP          = 'C:\Transferr\sql.sql'
$env:FM_WORK          = $work
$env:FM_BIGTABLES_SQL = "$work\bigtables_data.sql"
$env:FM_BIGTABLES_WARN= "$work\bigtables_skipped.log"
$env:FM_NONBIG_SQL    = "$work\nonbig.sql"

# SA password from .env
$PW = (Select-String -Path "$root\.env" -Pattern '^MSSQL_SA_PASSWORD=(.+)$').Matches.Groups[1].Value

function Log($m) { "$([DateTime]::Now.ToString('s'))  $m" | Tee-Object -FilePath $log -Append }
function Sql($db, $q, $extra=@()) {
  docker exec $ctr /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P $PW -C -d $db -h -1 -W -t 0 @extra -Q $q
}

Log "===== FleetMgmt full re-import START ====="

# --- A. Extraction --------------------------------------------------------
Log "STEP A1: filter big tables from dump -> bigtables_data.sql"
& $py "$tools\sql_dump_filter_bigtables.py" *>> $log
Log "STEP A2: parse bigtables_data.sql -> TSVs (parallel)"
& $py "$tools\sql_to_tsv_parallel.py" *>> $log
Log "STEP A3: filter non-big (schema + small/mid) -> nonbig.sql"
& $py "$tools\sql_dump_filter_nonbig.py" *>> $log

# --- B. Validation gate ---------------------------------------------------
$tsvSnmp = "$work\accsnmphistory.tsv"; $tsvMib = "$work\accmibcountervalues.tsv"
if (-not (Test-Path $tsvSnmp) -or -not (Test-Path $tsvMib) -or -not (Test-Path $env:FM_NONBIG_SQL)) {
  Log "GATE FAIL: extraction outputs missing. ABORT before touching DB."; exit 1
}
# Count rows = file size / mean? No -- count 0x1E row terminators reliably via .NET stream.
function Count-Rows($path) {
  $fs = [System.IO.File]::OpenRead($path); $buf = New-Object byte[] (16MB); $n = 0
  while (($r = $fs.Read($buf,0,$buf.Length)) -gt 0) { for ($i=0;$i -lt $r;$i++){ if ($buf[$i] -eq 0x1E){$n++} } }
  $fs.Close(); return $n
}
Log "GATE: counting TSV rows (0x1E terminators)..."
$nSnmp = Count-Rows $tsvSnmp; $nMib = Count-Rows $tsvMib
Log "GATE: SNMP=$nSnmp (expect 48074445)  MIB=$nMib (expect 12449058)"
if ([math]::Abs($nSnmp - 48074445) -gt 1000 -or [math]::Abs($nMib - 12449058) -gt 1000) {
  Log "GATE FAIL: TSV counts off by >1000. ABORT, DB left untouched."; exit 2
}
Log "GATE PASS. Proceeding to destructive load."

# --- C. Load --------------------------------------------------------------
Log "STEP C1: wipe + recreate DevFleetMgmt (SIMPLE recovery)"
Sql 'master' "IF DB_ID('DevFleetMgmt') IS NOT NULL BEGIN ALTER DATABASE DevFleetMgmt SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE DevFleetMgmt; END; CREATE DATABASE DevFleetMgmt COLLATE Latin1_General_CI_AS; ALTER DATABASE DevFleetMgmt SET RECOVERY SIMPLE;" *>> $log

Log "STEP C2: load nonbig.sql (schema + small/mid, ~hours)"
docker exec $ctr /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P $PW -C -d DevFleetMgmt -i /work/nonbig.sql -m 11 -t 0 *>> $log

Log "STEP C3: BULK ACCMIBCOUNTERVALUES"
Sql 'DevFleetMgmt' "BULK INSERT [dbo].[ACCMIBCOUNTERVALUES] FROM '/work/accmibcountervalues.tsv' WITH (FIELDTERMINATOR='0x1F', ROWTERMINATOR='0x1E0x0A', DATAFILETYPE='char', TABLOCK, KEEPNULLS, BATCHSIZE=100000, MAXERRORS=1000, KEEPIDENTITY);" *>> $log
Log "STEP C4: BULK ACCSNMPHISTORY"
Sql 'DevFleetMgmt' "BULK INSERT [dbo].[ACCSNMPHISTORY] FROM '/work/accsnmphistory.tsv' WITH (FIELDTERMINATOR='0x1F', ROWTERMINATOR='0x1E0x0A', DATAFILETYPE='char', TABLOCK, KEEPNULLS, BATCHSIZE=100000, MAXERRORS=1000);" *>> $log

Log "STEP C5: missing_data.sql"
docker exec $ctr /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P $PW -C -d DevFleetMgmt -i /data/missing_data.sql -m 11 -t 0 *>> $log

Log "STEP C6: recreate krai_readonly"
Sql 'master' "IF NOT EXISTS(SELECT 1 FROM sys.sql_logins WHERE name='krai_readonly') CREATE LOGIN krai_readonly WITH PASSWORD='KraiInsightsRO!2026', CHECK_POLICY=ON;" *>> $log
Sql 'DevFleetMgmt' "IF NOT EXISTS(SELECT 1 FROM sys.database_principals WHERE name='krai_readonly') CREATE USER krai_readonly FOR LOGIN krai_readonly; ALTER ROLE db_datareader ADD MEMBER krai_readonly;" *>> $log

Log "STEP C7: verify"
$tables = (Sql 'DevFleetMgmt' "SET NOCOUNT ON; SELECT COUNT(*) FROM sys.tables;") -join ''
$totnew = (Sql 'DevFleetMgmt' "SET NOCOUNT ON; SELECT SUM(p.rows) FROM sys.partitions p JOIN sys.tables t ON t.object_id=p.object_id WHERE p.index_id IN (0,1);") -join ''
Log "RESULT: tables=$tables  total_rows=$totnew  (baseline 119 / 62000209)"
Sql 'DevFleetMgmt' "SET NOCOUNT ON; SELECT t.name, SUM(p.rows) FROM sys.tables t JOIN sys.partitions p ON p.object_id=t.object_id AND p.index_id IN (0,1) GROUP BY t.name ORDER BY SUM(p.rows) DESC;" @('-s',',','-o','/work/reimport_counts.csv')
Log "===== FleetMgmt full re-import DONE ====="
