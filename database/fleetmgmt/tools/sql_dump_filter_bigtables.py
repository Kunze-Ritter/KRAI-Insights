"""Stream the UTF-16 LE dump and extract INSERTs for the two huge tables
(ACCSNMPHISTORY + ACCMIBCOUNTERVALUES) into a clean UTF-8 SQL file.

This version FIXES the original crash by sanitising multi-line string
literals: any newline (or carriage return) that sits *inside* a quoted
string is replaced by `' + CHAR(10) + N'` (resp. `CHAR(13)`). That way the
output file contains exactly ONE statement per line, so sqlcmd's line-
based parser cannot misinterpret an embedded newline as a statement
terminator anymore.

Other safety features:
  * Multi-line statements are flushed only when the unescaped quote balance
    is even again, and abandoned (with a warning) once they grow beyond
    safety limits (likely indicates a corrupted source).
  * Output is broken into batches of 5000 INSERTs separated by `GO`, so a
    single broken batch can never poison the rest of the import.
  * Source is read in 32 MB chunks for high throughput (~300 MB/s).
"""

from __future__ import annotations

import codecs
import sys
import time
from pathlib import Path

SRC = Path(r"C:\Transferr\sql.sql")
OUT = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\scripts\bigtables_data.sql")
WARN = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\bigtables_skipped.log")

KEEP_TABLES = {"ACCSNMPHISTORY", "ACCMIBCOUNTERVALUES"}

BATCH_SIZE = 5000  # INSERTs per GO batch
MAX_STMT_LINES = 200  # if a statement spans this many input lines, treat as broken
MAX_STMT_CHARS = 2_000_000  # 2 MB; any single statement larger than this is broken


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def sanitize_string_newlines(stmt: str) -> str:
    """Replace newlines inside single-quoted strings with `' + CHAR(10) + N'`.

    Operates over the full (possibly multi-line) statement text. Outside of
    strings, characters pass through unchanged.
    """
    if "\n" not in stmt and "\r" not in stmt:
        return stmt
    out: list[str] = []
    in_string = False
    i = 0
    n = len(stmt)
    while i < n:
        c = stmt[i]
        if c == "'":
            if in_string and i + 1 < n and stmt[i + 1] == "'":
                # escaped quote inside string -- copy both
                out.append("''")
                i += 2
                continue
            in_string = not in_string
            out.append(c)
            i += 1
        elif in_string and c == "\n":
            out.append("' + CHAR(10) + N'")
            i += 1
        elif in_string and c == "\r":
            out.append("' + CHAR(13) + N'")
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: not found: {SRC}", file=sys.stderr)
        return 2

    src_size = SRC.stat().st_size
    print(f"Source: {SRC} ({human_bytes(src_size)})")
    print(f"Output: {OUT}")
    print(f"Warn:   {WARN}")
    print(f"Keep:   {sorted(KEEP_TABLES)}")
    print(f"Batch:  {BATCH_SIZE} INSERTs per GO")
    print()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    warn_fh = WARN.open("w", encoding="utf-8")

    inserts_kept = 0
    inserts_skipped_broken = 0
    set_kept = 0
    bytes_read = 0
    start = time.time()
    last_report = start

    inserts_per_table: dict[str, int] = {}
    batch_count_for_current_table = 0
    current_batch_table: str | None = None

    stmt_lines: list[str] = []
    quote_balance = 0
    stmt_total_chars = 0

    INS_PREFIX_TABLE_OFFSET = len("INSERT [dbo].[")

    def extract_insert_table(line: str) -> str | None:
        if not line.startswith("INSERT [dbo].["):
            return None
        end = line.find("]", INS_PREFIX_TABLE_OFFSET)
        if end <= INS_PREFIX_TABLE_OFFSET:
            return None
        return line[INS_PREFIX_TABLE_OFFSET:end]

    def extract_setident_table(line: str) -> str | None:
        if not line.startswith("SET IDENTITY_INSERT [dbo].["):
            return None
        prefix = len("SET IDENTITY_INSERT [dbo].[")
        end = line.find("]", prefix)
        if end <= prefix:
            return None
        return line[prefix:end]

    with SRC.open("rb") as fh, OUT.open("w", encoding="utf-8", newline="\n") as out:
        out.write("-- bigtables_data.sql\n")
        out.write(f"-- Keep:    {sorted(KEEP_TABLES)}\n")
        out.write(f"-- Source:  {SRC}\n")
        out.write("\n")
        out.write("USE [DevFleetMgmt]\n")
        out.write("GO\n")
        out.write("SET NOCOUNT ON\n")
        out.write("GO\n\n")

        bom = fh.read(2)
        bytes_read += 2
        if bom != b"\xff\xfe":
            print(f"WARNING: expected UTF-16 LE BOM, got {bom!r}", file=sys.stderr)

        decoder = codecs.getincrementaldecoder("utf-16-le")(errors="replace")
        leftover_bytes = b""
        leftover_text = ""

        def flush_insert(stmt: str, table: str) -> None:
            nonlocal inserts_kept, batch_count_for_current_table, current_batch_table
            sanitized = sanitize_string_newlines(stmt)
            # Switch batch wrapper if table changed
            if table != current_batch_table:
                if current_batch_table is not None and batch_count_for_current_table > 0:
                    out.write("GO\n")
                current_batch_table = table
                batch_count_for_current_table = 0
            out.write(sanitized)
            out.write("\n")
            inserts_kept += 1
            batch_count_for_current_table += 1
            inserts_per_table[table] = inserts_per_table.get(table, 0) + 1
            if batch_count_for_current_table >= BATCH_SIZE:
                out.write("GO\n")
                batch_count_for_current_table = 0

        def flush_setident(stmt: str, table: str) -> None:
            nonlocal set_kept, current_batch_table, batch_count_for_current_table
            if current_batch_table is not None and batch_count_for_current_table > 0:
                out.write("GO\n")
                batch_count_for_current_table = 0
            current_batch_table = None
            out.write(stmt)
            out.write("\nGO\n")
            set_kept += 1

        def abandon_stmt(reason: str) -> None:
            nonlocal inserts_skipped_broken
            inserts_skipped_broken += 1
            first = stmt_lines[0][:200] if stmt_lines else ""
            warn_fh.write(f"[{reason}] lines={len(stmt_lines)} chars={stmt_total_chars} first_line={first!r}\n")

        while True:
            buf = fh.read(32 * 1024 * 1024)
            if not buf:
                break
            bytes_read += len(buf)
            data = leftover_bytes + buf
            if len(data) % 2 == 1:
                leftover_bytes = data[-1:]
                data = data[:-1]
            else:
                leftover_bytes = b""

            try:
                text = leftover_text + decoder.decode(data)
            except Exception as e:
                print(f"decode error at {bytes_read}: {e}", file=sys.stderr)
                continue

            lines = text.split("\n")
            leftover_text = lines.pop()

            for raw in lines:
                line = raw.rstrip("\r")

                if stmt_lines:
                    stmt_lines.append(line)
                    stmt_total_chars += len(line) + 1
                    quote_balance = (quote_balance + line.count("'")) % 2
                    # safety bail-out for runaway statements
                    if len(stmt_lines) > MAX_STMT_LINES or stmt_total_chars > MAX_STMT_CHARS:
                        abandon_stmt("runaway")
                        stmt_lines = []
                        stmt_total_chars = 0
                        quote_balance = 0
                        continue
                    if quote_balance == 0:
                        first_line = stmt_lines[0]
                        stmt = "\n".join(stmt_lines)
                        tbl = extract_insert_table(first_line)
                        if tbl:
                            if tbl in KEEP_TABLES:
                                flush_insert(stmt, tbl)
                        else:
                            tbl2 = extract_setident_table(first_line)
                            if tbl2 and tbl2 in KEEP_TABLES:
                                flush_setident(stmt, tbl2)
                        stmt_lines = []
                        stmt_total_chars = 0
                else:
                    if not (line.startswith("INSERT [dbo].[") or line.startswith("SET IDENTITY_INSERT")):
                        continue
                    qcount = line.count("'")
                    if qcount % 2 == 0:
                        tbl = extract_insert_table(line)
                        if tbl:
                            if tbl in KEEP_TABLES:
                                flush_insert(line, tbl)
                        else:
                            tbl2 = extract_setident_table(line)
                            if tbl2 and tbl2 in KEEP_TABLES:
                                flush_setident(line, tbl2)
                    else:
                        stmt_lines = [line]
                        stmt_total_chars = len(line) + 1
                        quote_balance = 1

            now = time.time()
            if now - last_report >= 10:
                elapsed = now - start
                pct = (bytes_read / src_size) * 100 if src_size else 0
                rate = bytes_read / elapsed / (1024 * 1024) if elapsed > 0 else 0
                eta_s = (src_size - bytes_read) / (rate * 1024 * 1024) if rate > 0 else 0
                eta = time.strftime("%H:%M:%S", time.gmtime(eta_s)) if eta_s else "?"
                print(
                    f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] "
                    f"{human_bytes(bytes_read)}/{human_bytes(src_size)} ({pct:.1f}%) "
                    f"{rate:.0f} MB/s ETA {eta} | "
                    f"kept={inserts_kept:,} broken={inserts_skipped_broken:,} | "
                    f"accum={len(stmt_lines)}",
                    flush=True,
                )
                last_report = now

        if current_batch_table is not None and batch_count_for_current_table > 0:
            out.write("GO\n")

    warn_fh.close()
    elapsed = time.time() - start
    out_size = OUT.stat().st_size

    print()
    print("=== DONE ===")
    print(f"Elapsed:        {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
    print(f"Output size:    {human_bytes(out_size)}")
    print(f"INSERTs kept:   {inserts_kept:,}")
    print(f"INSERTs broken: {inserts_skipped_broken:,}  (see {WARN.name})")
    print(f"SET kept:       {set_kept}")
    print()
    print("Per kept table:")
    for tbl, cnt in sorted(inserts_per_table.items(), key=lambda x: -x[1]):
        print(f"  {cnt:>12,}  {tbl}")
    print()
    print(f"Wrote: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
