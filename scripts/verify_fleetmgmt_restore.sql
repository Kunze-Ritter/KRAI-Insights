-- Verify the FleetMgmt (DevFleetMgmt) restore against the known baseline.
-- Baseline: 119 tables, 62,000,209 rows (transfer_to_insights/.../fleetmgmt_table_stats.txt).
-- Run: sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -d DevFleetMgmt -i verify_fleetmgmt_restore.sql
USE DevFleetMgmt;
GO

-- 1) Table count  (expect 119)
SELECT COUNT(*) AS table_count FROM sys.tables;
GO

-- 2) Total rows across all base tables  (expect 62,000,209; rowstore-exact)
SELECT SUM(p.rows) AS total_rows
FROM sys.partitions p
JOIN sys.tables t ON t.object_id = p.object_id
WHERE p.index_id IN (0, 1);
GO

-- 3) Per-table row counts, descending (full 119-row list -> diff vs baseline)
SELECT t.name AS table_name, SUM(p.rows) AS row_count
FROM sys.tables t
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
GROUP BY t.name
ORDER BY row_count DESC;
GO

-- 4) Top-10 baseline assertions (each must match exactly)
--      ACCSNMPHISTORY            48,074,445
--      ACCMIBCOUNTERVALUES       12,449,058
--      ACCEVENTHISTORY              836,187
--      ACCMARKERREFILL              199,172
--      ACCDEVICEMARKERCOVERAGE      141,936
--      ACCFMREPORTING               128,087
--      ACCMIBCOUNTERTEMPLATE         45,095
--      ACCDEVICECONTRACTS            31,493
--      ACCINPUTTRAYS                 22,186
--      ACCMARKERCOVERAGE             20,525
SELECT t.name AS table_name, SUM(p.rows) AS row_count
FROM sys.tables t
JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
WHERE t.name IN (
    'ACCSNMPHISTORY','ACCMIBCOUNTERVALUES','ACCEVENTHISTORY','ACCMARKERREFILL',
    'ACCDEVICEMARKERCOVERAGE','ACCFMREPORTING','ACCMIBCOUNTERTEMPLATE',
    'ACCDEVICECONTRACTS','ACCINPUTTRAYS','ACCMARKERCOVERAGE'
)
GROUP BY t.name
ORDER BY row_count DESC;
GO

-- 5) Sanity read
SELECT TOP 5 SerialNumber, IPAddress, Description FROM ACCDEVICES;
GO
