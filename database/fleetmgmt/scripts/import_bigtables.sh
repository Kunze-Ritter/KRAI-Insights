#!/usr/bin/env bash
# Import bigtables_data.sql (ACCSNMPHISTORY + ACCMIBCOUNTERVALUES) into
# DevFleetMgmt. Runs sqlcmd in the background and produces a progress log
# that fleetmgmt_status.ps1 can tail.

set -euo pipefail

SCRIPTDIR="/scripts"
LOGDIR="/tmp"
DATAFILE="${SCRIPTDIR}/bigtables_data.sql"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="${LOGDIR}/import_bigtables_${TS}.log"
PROGRESS="${LOGDIR}/import_bigtables_${TS}.progress"

if [[ ! -f "${DATAFILE}" ]]; then
  echo "ERROR: ${DATAFILE} not found" >&2
  exit 1
fi

DATAFILE_SIZE=$(stat -c %s "${DATAFILE}")
echo "Importing ${DATAFILE} ($(numfmt --to=iec --suffix=B ${DATAFILE_SIZE}))"
echo "Log:      ${LOG}"
echo "Progress: ${PROGRESS}"
echo

# Background monitor
{
  while true; do
    sleep 30
    /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C \
      -d DevFleetMgmt -h -1 -W -Q "SET NOCOUNT ON;
        SELECT
          CONCAT(
            '[', CONVERT(varchar, SYSUTCDATETIME(), 120), '] ',
            'snmp=', (SELECT COUNT(*) FROM ACCSNMPHISTORY WITH (NOLOCK)),
            ' mib=',  (SELECT COUNT(*) FROM ACCMIBCOUNTERVALUES WITH (NOLOCK)),
            ' data_mb=', (SELECT SUM(size)*8/1024 FROM sys.master_files
                          WHERE database_id=DB_ID() AND type=0)
          )" 2>&1 | grep -v '^$' >> "${PROGRESS}" || true
  done
} &
MON_PID=$!
trap "kill ${MON_PID} 2>/dev/null || true" EXIT

START=$(date +%s)
echo "[$(date)] starting sqlcmd"
/opt/mssql-tools18/bin/sqlcmd \
  -S localhost \
  -U sa \
  -P "${MSSQL_SA_PASSWORD}" \
  -C \
  -d DevFleetMgmt \
  -i "${DATAFILE}" \
  -m 10 \
  -V 16 \
  -h -1 \
  -t 600 \
  > "${LOG}" 2>&1 || true
END=$(date +%s)
ELAPSED=$((END - START))

echo "[$(date)] sqlcmd done after ${ELAPSED}s"
echo
echo "=== Final counts ==="
/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C \
  -d DevFleetMgmt -h -1 -W -Q "SET NOCOUNT ON;
    SELECT 'ACCSNMPHISTORY=' + CAST(COUNT(*) AS varchar) FROM ACCSNMPHISTORY WITH (NOLOCK);
    SELECT 'ACCMIBCOUNTERVALUES=' + CAST(COUNT(*) AS varchar) FROM ACCMIBCOUNTERVALUES WITH (NOLOCK);
    SELECT 'data_mb=' + CAST(SUM(size)*8/1024 AS varchar) FROM sys.master_files
      WHERE database_id=DB_ID() AND type=0;"

echo
echo "=== Errors found in log ==="
grep -iE 'Msg [0-9]+|Level [0-9]+, State' "${LOG}" | head -30 || echo "(none)"
