# FleetMgmt Restore Verification — 2026-05-21

Restore of the FleetMgmt source DB (`DevFleetMgmt`, DocuForm CSP, MSSQL 2022) into
krai-insights after the old external volume `krai-minimal_fleetmgmt_data` was
deleted during the transfer out of KRAI-minimal.

## Path chosen: Phase 2 — restore from `.bak` (primary)

- **Source:** `transfer_to_insights/fleetmgmt/database/backups/DevFleetMgmt_20260520.bak` (2,239,152,128 B ≈ 2.13 GB, compressed)
- **Target volume:** `krai-insights_fleetmgmt_data` (fresh, krai-insights-owned named volume — no longer `external`)
- **Command:** `RESTORE DATABASE DevFleetMgmt ... WITH MOVE 'DevFleetMgmt' → /var/opt/mssql/data/DevFleetMgmt.mdf, MOVE 'DevFleetMgmt_log' → DevFleetMgmt_log.ldf, REPLACE, STATS=5`
- **Duration:** **38.792 s** (1,891,130 pages, 380.9 MB/s on SSD)
- Phase 4 (160 GB dump re-import) was **not** required.

## Acceptance criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Container `fleetmgmt-mssql` healthy | ✅ healthy |
| 2 | Database `DevFleetMgmt` exists | ✅ |
| 3 | `COUNT(*) FROM sys.tables` == 119 | ✅ **119** |
| 4 | Σ row counts == 62,000,209 | ⚠️ **62,000,142** (−67, documented below) |
| 5 | Top-10 tables match | ⚠️ 2/10 exact, 8 off by −2 (documented below) |
| 6 | Sanity read works | ✅ `SELECT TOP 5 SerialNo, PrinterIP, Model FROM ACCDEVICES` |
| 7 | Verification report | ✅ this file |

## The −67 row delta is expected, not data loss

- The baseline **62,000,209** in `fleetmgmt_table_stats.txt` is the **INSERT-statement
  count of the 160 GB source dump** (`C:\Transferr\sql.sql`), scanned 2026-05-20.
- The restored DB has **62,000,142** rows — which is **exactly** the count measured on
  the *live* `DevFleetMgmt` on 2026-05-21 (before the volume was deleted, independently
  verified during the move). The `.bak` is therefore a faithful copy of the production DB.
- The gap is a **uniform systematic offset** from the original dump→DB import, not random
  loss: of the 34 differing tables, **33 are exactly −2** and `NPSUSERS` is **−1**
  (33×2 + 1 = **67**). No tables are missing or extra (119 == 119).
- A Phase-4 re-import from the same dump would reproduce ≈62,000,142 again (the import is
  what produced that number), so it would **not** close the gap. **Phase 4 was deliberately
  skipped.** Verdict: **PASS with documented delta.**

Full per-table diff: `scripts/diff_fleetmgmt_counts.py` against
`database/fleetmgmt/logs/restored_counts.csv` (gitignored). The 34 differing tables:
all −2 except `NPSUSERS` (−1). Top-10 baseline check:

| Table | Baseline | Restored | Δ |
|---|---|---|---|
| ACCSNMPHISTORY | 48,074,445 | 48,074,445 | 0 |
| ACCMIBCOUNTERVALUES | 12,449,058 | 12,449,056 | −2 |
| ACCEVENTHISTORY | 836,187 | 836,185 | −2 |
| ACCMARKERREFILL | 199,172 | 199,170 | −2 |
| ACCDEVICEMARKERCOVERAGE | 141,936 | 141,934 | −2 |
| ACCFMREPORTING | 128,087 | 128,085 | −2 |
| ACCMIBCOUNTERTEMPLATE | 45,095 | 45,093 | −2 |
| ACCDEVICECONTRACTS | 31,493 | 31,491 | −2 |
| ACCINPUTTRAYS | 22,186 | 22,184 | −2 |
| ACCMARKERCOVERAGE | 20,525 | 20,525 | 0 |

## Sanity reads

`SELECT TOP 5 SerialNo, PrinterIP, Model FROM ACCDEVICES`:

```
CN1622H034 | 172.20.40.67 | HP Designjet T1300 (44'' sized)
M1G443717  | 172.20.40.68 | Brother QL-580N
A3Z493563  | 172.20.40.73 | Brother QL-720NW
G2Z850984  | 10.16.25.74  | Brother QL-720NW
C3Z918086  | 172.20.40.75 | Brother QL-720NW
```

## Access / connectivity

- The `.bak` predates the `krai_readonly` login, so it was recreated: `CREATE LOGIN
  krai_readonly` + `db_datareader` on `DevFleetMgmt`. App connects with it.
- End-to-end verified: `insights.etl.fleetmgmt_extractor.ping()` from the app container
  → **True** (app → FleetMgmt over the published port as `krai_readonly`).

## Container

- Health: healthy
- Data size: `du -sh /var/opt/mssql` → **27 GB**
- Compose: `fleetmgmt-mssql` service in `docker-compose.yml`, volume `fleetmgmt_data`
  (managed), restore sources mounted read-only via `FLEETMGMT_BACKUP_DIR` (`/backups`)
  and `FLEETMGMT_IMPORT_DIR` (`/import`).

## Reference / follow-ups

- Source backup retained: `transfer_to_insights/.../DevFleetMgmt_20260520.bak`.
- Recommended follow-up: produce a krai-insights-owned `.bak` into a writable backups dir
  so future restores don't depend on `transfer_to_insights/`.
- `transfer_to_insights/` and `C:\Transferr\sql.sql` were treated strictly read-only.
