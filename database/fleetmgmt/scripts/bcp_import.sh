#!/usr/bin/env bash
# Load the two big tables from TSV via bcp (character mode), then recreate
# the primary keys. bcp accepts multi-byte field/row terminators directly,
# bypassing the BULK INSERT hex-syntax limitation on Linux.

set -euo pipefail

LOGDIR="/tmp"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="${LOGDIR}/bcp_import_${TS}.log"
PROGRESS="${LOGDIR}/bcp_import_${TS}.progress"
ERR_MIB="${LOGDIR}/bcp_err_mib_${TS}.txt"
ERR_SNMP="${LOGDIR}/bcp_err_snmp_${TS}.txt"

SNMP_TSV="/scripts/accsnmphistory.tsv"
MIB_TSV="/scripts/accmibcountervalues.tsv"

# Multi-byte terminators (must match what the python converter emitted).
FT=$'\x1f'
RT=$'\x1e\n'

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
echo "[$(date)] bcp ACCMIBCOUNTERVALUES" | tee -a "${LOG}"

/opt/mssql-tools18/bin/bcp [dbo].[ACCMIBCOUNTERVALUES] in "${MIB_TSV}" \
  -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" \
  -d DevFleetMgmt \
  -u \
  -c \
  -t "${FT}" \
  -r "${RT}" \
  -E \
  -k \
  -h "TABLOCK" \
  -m 100 \
  -b 100000 \
  -e "${ERR_MIB}" \
  >> "${LOG}" 2>&1 || echo "[WARN] bcp MIB returned non-zero (rc=$?)" | tee -a "${LOG}"

MID=$(date +%s)
echo "[$(date)] MIB done in $((MID - START))s" | tee -a "${LOG}"

echo "[$(date)] bcp ACCSNMPHISTORY" | tee -a "${LOG}"
/opt/mssql-tools18/bin/bcp [dbo].[ACCSNMPHISTORY] in "${SNMP_TSV}" \
  -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" \
  -d DevFleetMgmt \
  -u \
  -c \
  -t "${FT}" \
  -r "${RT}" \
  -k \
  -h "TABLOCK" \
  -m 100 \
  -b 100000 \
  -e "${ERR_SNMP}" \
  >> "${LOG}" 2>&1 || echo "[WARN] bcp SNMP returned non-zero (rc=$?)" | tee -a "${LOG}"

END=$(date +%s)
echo "[$(date)] SNMP done in $((END - MID))s; total $((END - START))s" | tee -a "${LOG}"

echo "[$(date)] re-creating primary keys" | tee -a "${LOG}"
/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${MSSQL_SA_PASSWORD}" -C \
  -d DevFleetMgmt -h -1 -W -t 0 -Q "
SET NOCOUNT ON;
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='ACCMIBCOUNTERVALUES_PK')
  ALTER TABLE [dbo].[ACCMIBCOUNTERVALUES]
    ADD CONSTRAINT [ACCMIBCOUNTERVALUES_PK] PRIMARY KEY CLUSTERED ([pkId]);
IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='ACCSNMPHISTORY_PK')
  ALTER TABLE [dbo].[ACCSNMPHISTORY]
    ADD CONSTRAINT [ACCSNMPHISTORY_PK] PRIMARY KEY CLUSTERED ([DeviceId],[sType],[sKey],[TimeUTC]);
SELECT 'final ACCMIBCOUNTERVALUES rows=' + CAST(COUNT(*) AS varchar) FROM ACCMIBCOUNTERVALUES;
SELECT 'final ACCSNMPHISTORY rows='     + CAST(COUNT(*) AS varchar) FROM ACCSNMPHISTORY;
SELECT 'final data_gb=' + CAST((SELECT SUM(size)*8.0/1024/1024 FROM sys.master_files
                                WHERE database_id=DB_ID() AND type=0) AS varchar);
" 2>&1 | tee -a "${LOG}"

FIN=$(date +%s)
echo "[$(date)] PK rebuild done in $((FIN - END))s; grand total $((FIN - START))s" | tee -a "${LOG}"

echo
echo "=== Error files ==="
ls -lh "${ERR_MIB}" "${ERR_SNMP}" 2>/dev/null || true
