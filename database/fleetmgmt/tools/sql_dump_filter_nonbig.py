"""Stream the UTF-16 LE dump and write a copy that contains EVERYTHING except
the INSERT / SET IDENTITY_INSERT statements for the two huge tables
(ACCSNMPHISTORY + ACCMIBCOUNTERVALUES).

This is the complement of sql_dump_filter_bigtables.py: the output is a faithful,
sqlcmd-loadable dump of the schema + all *small/mid* table data (~1.5M rows),
which loads in a few hours via `sqlcmd -i`. The big tables are then loaded
separately via BULK INSERT from TSV.

Output is UTF-16 LE (with BOM), same as the source, so sqlcmd reads it exactly
like the original dump (preserves German text in device/customer fields).

Env overrides: FM_DUMP (source), FM_NONBIG_SQL (output).
"""

from __future__ import annotations

import codecs
import os
import sys
import time
from pathlib import Path

SRC = Path(os.environ.get("FM_DUMP", r"C:\Transferr\sql.sql"))
OUT = Path(os.environ.get("FM_NONBIG_SQL", r"database\fleetmgmt\work\nonbig.sql"))

SKIP_TABLES = {"ACCSNMPHISTORY", "ACCMIBCOUNTERVALUES"}
_INS_OFF = len("INSERT [dbo].[")
_SET_OFF = len("SET IDENTITY_INSERT [dbo].[")


def _table_after(line: str, prefix_len: int) -> str | None:
    end = line.find("]", prefix_len)
    return line[prefix_len:end] if end > prefix_len else None


def _skip_target(line: str) -> bool:
    """True if `line` starts a big-table INSERT or SET IDENTITY_INSERT."""
    if line.startswith("INSERT [dbo].["):
        return _table_after(line, _INS_OFF) in SKIP_TABLES
    if line.startswith("SET IDENTITY_INSERT [dbo].["):
        return _table_after(line, _SET_OFF) in SKIP_TABLES
    return False


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: not found: {SRC}", file=sys.stderr)
        return 2
    OUT.parent.mkdir(parents=True, exist_ok=True)
    src_size = SRC.stat().st_size
    print(f"Source: {SRC} ({src_size/1024/1024/1024:.1f} GB)")
    print(f"Output: {OUT}  (skip {sorted(SKIP_TABLES)})")

    in_string = False   # inside a multi-line quoted literal
    skipping = False     # inside a big-table statement being dropped
    kept_lines = skipped_stmts = 0
    bytes_read = 0
    start = last = time.time()

    with SRC.open("rb") as fh, OUT.open("w", encoding="utf-16", newline="") as out:
        bom = fh.read(2)
        bytes_read += 2
        if bom != b"\xff\xfe":
            print(f"WARNING: expected UTF-16 LE BOM, got {bom!r}", file=sys.stderr)
        decoder = codecs.getincrementaldecoder("utf-16-le")(errors="replace")
        leftover_bytes = b""
        leftover_text = ""

        while True:
            buf = fh.read(32 * 1024 * 1024)
            if not buf:
                break
            bytes_read += len(buf)
            data = leftover_bytes + buf
            if len(data) % 2 == 1:
                leftover_bytes, data = data[-1:], data[:-1]
            else:
                leftover_bytes = b""
            text = leftover_text + decoder.decode(data)
            lines = text.split("\n")
            leftover_text = lines.pop()

            for raw in lines:
                line = raw.rstrip("\r")
                odd = (line.count("'") % 2) == 1
                if skipping:
                    if in_string:
                        if odd:
                            in_string = False
                        continue
                    # statement was single-line skip already handled; if we got
                    # here the multi-line skip just ended
                    skipping = False
                if in_string:
                    out.write(line + "\r\n")
                    if odd:
                        in_string = False
                    continue
                if _skip_target(line):
                    skipped_stmts += 1
                    if odd:
                        in_string = True
                        skipping = True
                    continue
                out.write(line + "\r\n")
                kept_lines += 1
                if odd:
                    in_string = True

            now = time.time()
            if now - last >= 10:
                pct = bytes_read / src_size * 100 if src_size else 0
                rate = bytes_read / (now - start) / 1024 / 1024 if now > start else 0
                print(f"[{time.strftime('%H:%M:%S', time.gmtime(now-start))}] "
                      f"{pct:5.1f}% {rate:.0f} MB/s | kept_lines={kept_lines:,} "
                      f"skipped_big_stmts={skipped_stmts:,}", flush=True)
                last = now

    print(f"\n=== DONE === kept_lines={kept_lines:,} skipped_big_stmts={skipped_stmts:,}")
    print(f"Output size: {OUT.stat().st_size/1024/1024/1024:.2f} GB -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
