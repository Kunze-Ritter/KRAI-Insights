#!/usr/bin/env bash
# Bulk-load the two big tables from TSV files into DevFleetMgmt.
# Field terminator: 0x1F, row terminator: 0x1E + LF.
# Uses TABLOCK + minimal logging (DB is in SIMPLE recovery).
# Re-creates the primary keys at the end.

set -euo pipefail

LOGDIR="/tmp"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="${LOGDIR}/bulk_import_${TS}.log"
PROGRESS="${LOGDIR}/bulk_import_${TS}.progress"

SNMP_TSV="/scripts/accsnmphistory.tsv"
MIB_TSV="/scripts/accmibcountervalues.tsv"

if [[ ! -f "${MIB_TSV}" ]]; then
  echo "ERROR: ${MIB_TSV} not found" >&2
  exit 1
fi
if [[ ! -f "${SNMP_TSV}" ]]; then
  echo "ERROR: ${SNMP_TSV} not found" >&2
  exit 1
fi

echo "MIB TSV:  $(ls -lh ${MIB_TSV} | awk '{print $5}')"
echo "SNMP TSV: $(ls -lh ${SNMP_TSV} | awk '{print $5}')"
echo "Log:      ${LOG}"
echo "Progress: ${PROGRESS}"
echo

# Background monitor
{
  while true; do
    sleep 30
    /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C \
      -d DevFleetMgmt -h -1 -W -Q "SET NOCOUNT ON;
        SELECT CONCAT(
          '[', CONVERT(varchar, SYSUTCDATETIME(), 120), '] ',
          'snmp=', (SELECT COUNT(*) FROM ACCSNMPHISTORY WITH (NOLOCK)),
          ' mib=',  (SELECT COUNT(*) FROM ACCMIBCOUNTERVALUES WITH (NOLOCK)),
          ' data_gb=', CAST((SELECT SUM(size)*8/1024.0/1024.0 FROM sys.master_files
                          WHERE database_id=DB_ID() AND type=0) AS decimal(8,2))
        )" 2>&1 | grep -v '^$' >> "${PROGRESS}" || true
  done
} &
MON_PID=$!
trap "kill ${MON_PID} 2>/dev/null || true" EXIT

START=$(date +%s)
echo "[$(date)] starting BULK INSERT ACCMIBCOUNTERVALUES" | tee -a "${LOG}"

# IMPORTANT: BULK INSERT field/row terminators must be specified with the
# explicit hex syntax to send 0x1F / 0x1E. Use sqlcmd '!' escape for raw
# control chars by reading the SQL from a here-document.
/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C \
  -d DevFleetMgmt -h -1 -W -t 0 -Q "
SET NOCOUNT ON;
BULK INSERT [dbo].[ACCMIBCOUNTERVALUES]
  FROM '${MIB_TSV}'
  WITH (
    FIELDTERMINATOR = '0x1F',
    ROWTERMINATOR   = '0x1E0x0A',
    DATAFILETYPE    = 'char',
    TABLOCK,
    KEEPNULLS,
    BATCHSIZE       = 100000,
    MAXERRORS       = 100,
    KEEPIDENTITY
  );
SELECT 'ACCMIBCOUNTERVALUES rows=' + CAST(COUNT(*) AS varchar) FROM ACCMIBCOUNTERVALUES;
" >> "${LOG}" 2>&1 || echo "[WARN] MIB BULK INSERT returned non-zero" | tee -a "${LOG}"

MID=$(date +%s)
echo "[$(date)] MIB done in $((MID - START))s; starting ACCSNMPHISTORY" | tee -a "${LOG}"

/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C \
  -d DevFleetMgmt -h -1 -W -t 0 -Q "
SET NOCOUNT ON;
BULK INSERT [dbo].[ACCSNMPHISTORY]
  FROM '${SNMP_TSV}'
  WITH (
    FIELDTERMINATOR = '0x1F',
    ROWTERMINATOR   = '0x1E0x0A',
    DATAFILETYPE    = 'char',
    TABLOCK,
    KEEPNULLS,
    BATCHSIZE       = 100000,
    MAXERRORS       = 100
  );
SELECT 'ACCSNMPHISTORY rows=' + CAST(COUNT(*) AS varchar) FROM ACCSNMPHISTORY;
" >> "${LOG}" 2>&1 || echo "[WARN] SNMP BULK INSERT returned non-zero" | tee -a "${LOG}"

END=$(date +%s)
echo "[$(date)] SNMP done in $((END - MID))s; total $((END - START))s" | tee -a "${LOG}"

echo "[$(date)] re-creating primary keys" | tee -a "${LOG}"
/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C \
  -d DevFleetMgmt -h -1 -W -t 0 -Q "
SET NOCOUNT ON;
ALTER TABLE [dbo].[ACCMIBCOUNTERVALUES]
  ADD CONSTRAINT [ACCMIBCOUNTERVALUES_PK] PRIMARY KEY CLUSTERED ([pkId]);
ALTER TABLE [dbo].[ACCSNMPHISTORY]
  ADD CONSTRAINT [ACCSNMPHISTORY_PK] PRIMARY KEY CLUSTERED ([DeviceId],[sType],[sKey],[TimeUTC]);
SELECT 'final ACCMIBCOUNTERVALUES rows=' + CAST(COUNT(*) AS varchar) FROM ACCMIBCOUNTERVALUES;
SELECT 'final ACCSNMPHISTORY rows='     + CAST(COUNT(*) AS varchar) FROM ACCSNMPHISTORY;
SELECT 'final data_gb=' + CAST((SELECT SUM(size)*8/1024.0/1024.0 FROM sys.master_files
                                WHERE database_id=DB_ID() AND type=0) AS varchar);
" 2>&1 | tee -a "${LOG}"

FIN=$(date +%s)
echo "[$(date)] PK rebuild done in $((FIN - END))s; grand total $((FIN - START))s" | tee -a "${LOG}"

echo
echo "=== Errors in log ==="
grep -iE 'Msg [0-9]+|Level [0-9]+, State' "${LOG}" | head -30 || echo "(none)"
