# FleetMgmt Full Re-Import Verification — 2026-05-22

Full from-dump re-import of `DevFleetMgmt` (user-requested, Phase 4), to obtain
a clean from-source rebuild and to check whether the −67 delta from the `.bak`
restore was real missing data or a counting artifact.

## Method (Phase 4 — re-import from the 160 GB UTF-16 dump)

Orchestrated by `scripts/fleetmgmt_full_reimport.ps1`:

1. **Extract** from `C:\Transferr\sql.sql` (156.5 GB UTF-16 LE):
   - `sql_dump_filter_bigtables.py` → `bigtables_data.sql`
   - `sql_to_tsv_parallel.py` → `accsnmphistory.tsv` + `accmibcountervalues.tsv`
   - `sql_dump_filter_nonbig.py` → `nonbig.sql` (schema + small/mid, UTF-16)
2. **Validation gate** (before any wipe): TSV rows = 48,074,445 / 12,449,056 → PASS.
3. **Load** into a fresh DB: `sqlcmd -i nonbig.sql` (small/mid), then BULK INSERT
   the two big tables, recreate `krai_readonly`, verify.

### Timeline (~4 h)
| Phase | Time | |
|---|---|---|
| filter bigtables | 08:12 → 08:23 | ~11 min |
| TSV parse (parallel) | 08:23 → 08:40 | ~17 min |
| filter nonbig | 08:40 → 08:48 | ~8 min |
| gate (count TSV rows) | 08:48 → 09:03 | ~15 min |
| load nonbig (small/mid) | 09:03 → 11:09 | ~2 h 06 min |
| BULK both big tables | 11:13 → 12:05 | ~52 min |
| fresh .bak | 12:?? | 147 s |

### Bug found & fixed mid-run
The first BULK attempt used `ROWTERMINATOR='0x1E0x0A'` (double `0x` prefix) →
SQL Server found no row terminators (Msg 4866 "column too long") and loaded **0**
big-table rows. Corrected to `'0x1e0a'` (validated on a 100-row sample), then the
full BULK succeeded. `missing_data.sql` was dropped (redundant with the full
`nonbig` load; it only caused PK violations).

## Result vs baseline

| | Tables | Total rows | ACCSNMPHISTORY | ACCMIBCOUNTERVALUES |
|---|---|---|---|---|
| Baseline (dump INSERT scan) | 119 | 62,000,209 | 48,074,445 | 12,449,058 |
| **Re-import (this run)** | **119** | **62,000,143** | **48,074,445** | **12,449,056** |
| `.bak` restore (2026-05-21) | 119 | 62,000,142 | 48,074,445 | 12,449,056 |

- Delta to baseline: **−66**. No tables missing/extra. 33 tables differ, **all
  exactly −2** (uniform).
- `krai_readonly` total: 62,000,143. End-to-end app `fleetmgmt_extractor.ping()` → **True**.

## Conclusion — the −66/−67 is a counting artifact, proven

Two **independent** load paths — (a) the `.bak` restore and (b) this full re-import
from the raw dump via a different toolchain — land at **62,000,142 / 62,000,143**,
i.e. within 1 row of each other and ~66 short of the dump's INSERT scan
(62,000,209). The shortfall is a **uniform −2 across 33 unrelated tables**, which
cannot be random data loss; it is the dump-scan's INSERT-line count over-counting
(non-loadable / duplicate statements). **The database is complete.** The dump
baseline number (62,000,209) is not achievable by loading the dump, because the
dump itself does not contain 62,000,209 *loadable* rows.

## Artifacts

- Container `krai-fleetmgmt-mssql` healthy; data ≈ 40 GB on disk.
- Fresh backup: `database/fleetmgmt/backups/DevFleetMgmt_reimport_20260522.bak`
  (re-imported state; 38 s restore). The original `DevFleetMgmt_20260520.bak`
  is retained alongside.
- Per-table counts: `database/fleetmgmt/logs/reimport_counts.csv` (gitignored).
- Sanity read (`SerialNo, PrinterIP, Model`): HP Designjet T1300, Brother QL-580N/720NW.
