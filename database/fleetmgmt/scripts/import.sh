#!/usr/bin/env bash
# Import the UTF-16 LE T-SQL dump into the local MSSQL instance.
# Designed to be run *inside* krai-fleetmgmt-mssql via `docker exec`.
#
# Strategy:
#   1. Pre-create DevFleetMgmt with Linux-friendly paths (the dump's own
#      CREATE DATABASE uses Windows paths C:\Program Files\... and would fail).
#   2. Set SIMPLE recovery model so bulk INSERTs don't blow up the transaction log.
#   3. Run sqlcmd with the connection already pointing at DevFleetMgmt, so the
#      dump's `USE [DevFleetMgmt]` succeeds and subsequent CREATE/INSERT land
#      in the right database. The dump's leading CREATE DATABASE + ALTER
#      DATABASE statements will fail harmlessly (the DB already exists).
#
# Output is written to /logs/import_<timestamp>.log (bind-mounted to host).

set -uo pipefail

SA_PASS="${MSSQL_SA_PASSWORD:?MSSQL_SA_PASSWORD must be set}"
DB_NAME="${MSSQL_DB_NAME:-DevFleetMgmt}"
DUMP="${DUMP_PATH:-/import/sql.sql}"
LOG_DIR="/logs"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="${LOG_DIR}/import_${TS}.log"
PROGRESS="${LOG_DIR}/import_${TS}.progress"
RUNNING_MARK="${LOG_DIR}/import.running"

mkdir -p "${LOG_DIR}"

echo "===========================================" | tee -a "${LOG}"
echo "Fleet Management dump import"                 | tee -a "${LOG}"
echo "Started:  $(date -u +%FT%TZ)"                 | tee -a "${LOG}"
echo "Dump:     ${DUMP}"                            | tee -a "${LOG}"
echo "Target:   ${DB_NAME}"                         | tee -a "${LOG}"
echo "Log:      ${LOG}"                             | tee -a "${LOG}"
echo "Progress: ${PROGRESS}"                        | tee -a "${LOG}"
echo "==========================================="  | tee -a "${LOG}"

if [[ ! -f "${DUMP}" ]]; then
  echo "ERROR: dump not found at ${DUMP}" | tee -a "${LOG}"
  exit 2
fi

SIZE=$(stat -c '%s' "${DUMP}")
echo "Dump size: ${SIZE} bytes ($((SIZE/1024/1024/1024)) GiB)" | tee -a "${LOG}"

# --- Step 1: pre-create the target DB with sensible defaults -----------------
echo "" | tee -a "${LOG}"
echo "[1/3] Creating target DB ${DB_NAME}..." | tee -a "${LOG}"
/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${SA_PASS}" -C \
  -d master -b -t 60 \
  -Q "
    IF DB_ID('${DB_NAME}') IS NULL
        CREATE DATABASE [${DB_NAME}]
            ON PRIMARY (
                NAME = N'${DB_NAME}',
                FILENAME = N'/var/opt/mssql/data/${DB_NAME}.mdf',
                SIZE = 256MB,
                MAXSIZE = UNLIMITED,
                FILEGROWTH = 256MB
            )
            LOG ON (
                NAME = N'${DB_NAME}_log',
                FILENAME = N'/var/opt/mssql/data/${DB_NAME}_log.ldf',
                SIZE = 128MB,
                MAXSIZE = 8GB,
                FILEGROWTH = 128MB
            );
    ALTER DATABASE [${DB_NAME}] SET RECOVERY SIMPLE;
    ALTER DATABASE [${DB_NAME}] SET READ_COMMITTED_SNAPSHOT ON;
    SELECT name, recovery_model_desc, state_desc
      FROM sys.databases WHERE name = '${DB_NAME}';
  " 2>&1 | tee -a "${LOG}"

RC1=${PIPESTATUS[0]}
if [[ ${RC1} -ne 0 ]]; then
    echo "ERROR: pre-create step failed (rc=${RC1})" | tee -a "${LOG}"
    exit 3
fi

# --- Step 2: background row-count monitor -----------------------------------
touch "${RUNNING_MARK}"
{
    while [[ -f "${RUNNING_MARK}" ]]; do
        sleep 60
        TS_NOW=$(date -u +%FT%TZ)
        ROW_INFO=$(/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${SA_PASS}" -C \
            -d "${DB_NAME}" -h -1 -W -s '|' -t 30 \
            -Q "SET NOCOUNT ON;
                SELECT COUNT(*) AS tables,
                       ISNULL(SUM(p.row_count),0) AS total_rows,
                       (SELECT (SUM(size) * 8 / 1024) FROM sys.master_files
                          WHERE database_id = DB_ID('${DB_NAME}') AND type=0) AS data_mb,
                       (SELECT (SUM(size) * 8 / 1024) FROM sys.master_files
                          WHERE database_id = DB_ID('${DB_NAME}') AND type=1) AS log_mb
                  FROM sys.tables t
                  LEFT JOIN sys.dm_db_partition_stats p
                       ON t.object_id = p.object_id AND p.index_id < 2;" 2>/dev/null | head -1)
        echo "${TS_NOW} ${ROW_INFO}" >> "${PROGRESS}"
    done
} &
MON_PID=$!

# --- Step 3: run the import -------------------------------------------------
echo "" | tee -a "${LOG}"
echo "[2/3] Streaming dump into ${DB_NAME}..." | tee -a "${LOG}"
echo "      (the dump's leading CREATE/ALTER DATABASE statements will" | tee -a "${LOG}"
echo "       fail harmlessly because the DB already exists)" | tee -a "${LOG}"
START_EPOCH=$(date +%s)

set +e
/opt/mssql-tools18/bin/sqlcmd \
    -S localhost \
    -U sa -P "${SA_PASS}" \
    -C \
    -d "${DB_NAME}" \
    -i "${DUMP}" \
    -m 11 \
    -t 0 \
    -k 1 \
    2>&1 | tee -a "${LOG}"
RC=$?
set -e

rm -f "${RUNNING_MARK}"
kill "${MON_PID}" 2>/dev/null || true

END_EPOCH=$(date +%s)
ELAPSED=$((END_EPOCH - START_EPOCH))

echo "" | tee -a "${LOG}"
echo "[3/3] Finished: $(date -u +%FT%TZ) (exit=${RC}, elapsed=${ELAPSED}s)" | tee -a "${LOG}"

if [[ ${RC} -ne 0 ]]; then
    echo "Import returned non-zero status ${RC}; check ${LOG} for details" | tee -a "${LOG}"
fi

echo "" | tee -a "${LOG}"
echo "===== Final row counts =====" | tee -a "${LOG}"
/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "${SA_PASS}" -C \
    -d "${DB_NAME}" -W -t 120 \
    -Q "SELECT t.name AS tbl, ISNULL(p.row_count, 0) AS row_count
          FROM sys.tables t
          LEFT JOIN sys.dm_db_partition_stats p
               ON t.object_id = p.object_id AND p.index_id < 2
         ORDER BY p.row_count DESC NULLS LAST, t.name;" 2>&1 | tee -a "${LOG}"

exit ${RC}
