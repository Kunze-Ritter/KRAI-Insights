"""Convert a sanitised UTF-8 SQL file (one INSERT per line) into a smaller
multi-row INSERT file: `INSERT [dbo].[T] (cols) VALUES (vals1), (vals2), ...;`.

This dramatically reduces RPC overhead in sqlcmd, typically 50-100x faster
for bulk inserts.

Input expects lines of the form:
    INSERT [dbo].[Table] ([c1], [c2], ...) VALUES (v1, v2, ...)
Lines that don't match (SET IDENTITY_INSERT, USE, GO, comments) are passed
through verbatim.

Each multi-row batch holds at most BATCH_ROWS rows and switches automatically
when the target table or its column list changes. A `GO` is emitted after
every BATCH_GROUPS multi-row INSERTs to keep transactions manageable.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

IN = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\scripts\bigtables_data.sql")
OUT = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\scripts\bigtables_multirow.sql")

# SQL Server max is 1000 row values per INSERT; we stay below for safety.
BATCH_ROWS = 500
# Emit GO after this many multi-row INSERTs (each up to BATCH_ROWS).
BATCH_GROUPS = 20


# Match: INSERT [dbo].[Table] (col1, col2) VALUES (...)
HEAD_RE = re.compile(r"^(INSERT \[dbo\]\.\[[^\]]+\] \([^)]*\) VALUES )(\(.*\))\s*$")


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def main() -> int:
    if not IN.exists():
        print(f"ERROR: not found: {IN}", file=sys.stderr)
        return 2

    src_size = IN.stat().st_size
    print(f"Input:    {IN} ({human_bytes(src_size)})")
    print(f"Output:   {OUT}")
    print(f"Batch:    up to {BATCH_ROWS} rows per multi-row INSERT")
    print(f"GO every: {BATCH_GROUPS} INSERTs ({BATCH_GROUPS * BATCH_ROWS} rows)")
    print()

    rows_seen = 0
    rows_kept = 0
    lines_passed = 0
    groups_emitted = 0
    start = time.time()
    last_report = start

    cur_head: str | None = None
    cur_values: list[str] = []

    def flush_current(out_fh) -> None:
        nonlocal cur_head, cur_values, rows_kept, groups_emitted
        if not cur_head or not cur_values:
            cur_head = None
            cur_values = []
            return
        out_fh.write(cur_head)
        out_fh.write(",\n".join(cur_values))
        out_fh.write(";\n")
        rows_kept += len(cur_values)
        groups_emitted += 1
        if groups_emitted % BATCH_GROUPS == 0:
            out_fh.write("GO\n")
        cur_head = None
        cur_values = []

    with IN.open("r", encoding="utf-8", newline="") as in_fh, OUT.open("w", encoding="utf-8", newline="\n") as out_fh:
        while True:
            raw = in_fh.readline()
            if not raw:
                break
            line = raw.rstrip("\r\n")
            if not line:
                continue
            m = HEAD_RE.match(line)
            if not m:
                # not an INSERT row -- flush current group and pass line through
                flush_current(out_fh)
                out_fh.write(line)
                out_fh.write("\n")
                lines_passed += 1
                continue
            head = m.group(1)
            values = m.group(2)
            rows_seen += 1
            if cur_head != head or len(cur_values) >= BATCH_ROWS:
                flush_current(out_fh)
                cur_head = head
            cur_values.append(values)

            now = time.time()
            if now - last_report >= 10:
                elapsed = now - start
                pos = in_fh.tell()
                pct = (pos / src_size) * 100 if src_size else 0
                rate_rows = rows_seen / elapsed if elapsed else 0
                eta_s = (src_size - pos) / (pos / elapsed) if pos and elapsed else 0
                eta = time.strftime("%H:%M:%S", time.gmtime(eta_s)) if eta_s else "?"
                print(
                    f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] "
                    f"{human_bytes(pos)}/{human_bytes(src_size)} ({pct:.1f}%) "
                    f"rows={rows_seen:,} ({rate_rows:,.0f}/s) "
                    f"groups={groups_emitted:,} ETA {eta}",
                    flush=True,
                )
                last_report = now

        # final flush
        flush_current(out_fh)

    out_size = OUT.stat().st_size
    elapsed = time.time() - start
    print()
    print("=== DONE ===")
    print(f"Elapsed:        {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
    print(f"Rows seen:      {rows_seen:,}")
    print(f"Rows kept:      {rows_kept:,}")
    print(f"Groups emitted: {groups_emitted:,}")
    print(f"Pass-through:   {lines_passed:,}")
    print(f"Input size:     {human_bytes(src_size)}")
    print(f"Output size:    {human_bytes(out_size)}  ({100 * out_size / src_size:.1f}% of input)")
    print(f"Compression:    {src_size / out_size:.1f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
