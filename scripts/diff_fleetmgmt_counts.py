"""
Diff restored FleetMgmt per-table row counts against the dump baseline.

    python scripts/diff_fleetmgmt_counts.py <restored_csv> <baseline_txt>

restored_csv : lines "TABLE,count" (from verify_fleetmgmt_restore.sql query 3)
baseline_txt : fleetmgmt_table_stats.txt (lines "   <count>  <TABLE>")

Reports table-count, total-row delta, and every differing table. It does NOT
hard-fail on a small total delta: the baseline is the INSERT count of the source
dump, which can legitimately exceed the rows actually imported into the DB.
"""

from __future__ import annotations

import re
import sys


def parse_restored(path: str) -> dict[str, int]:
    out: dict[str, int] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or "," not in line:
                continue
            name, _, cnt = line.rpartition(",")
            try:
                out[name.strip()] = int(cnt)
            except ValueError:
                continue
    return out


def parse_baseline(path: str) -> dict[str, int]:
    out: dict[str, int] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r"\s*([\d,]+)\s+([A-Z0-9_]+)\s*$", line)
            if m:
                out[m.group(2)] = int(m.group(1).replace(",", ""))
    return out


def main() -> int:
    restored = parse_restored(sys.argv[1])
    baseline = parse_baseline(sys.argv[2])

    b_total, r_total = sum(baseline.values()), sum(restored.values())
    missing = sorted(set(baseline) - set(restored))
    extra = sorted(set(restored) - set(baseline))
    diffs = sorted(
        ((t, baseline.get(t), restored.get(t)) for t in set(baseline) | set(restored)
         if baseline.get(t) != restored.get(t)),
        key=lambda x: abs((x[2] or 0) - (x[1] or 0)),
        reverse=True,
    )

    print(f"tables : baseline={len(baseline)} restored={len(restored)}")
    print(f"total  : baseline={b_total:,} restored={r_total:,} delta={r_total - b_total:+,}")
    print(f"missing tables: {missing or 'none'}")
    print(f"extra tables  : {extra or 'none'}")
    print(f"differing tables: {len(diffs)}")
    for t, b, r in diffs:
        print(f"  {t:32} baseline={b} restored={r} delta={(r or 0) - (b or 0):+}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
