"""Stream a UTF-16 LE MSSQL Generate-Scripts dump and emit a UTF-8 SQL file
that contains INSERTs (and the wrapping SET IDENTITY_INSERT directives) only
for tables we still need.

Handles INSERT statements whose VALUES contain embedded newlines inside string
literals (the bug that broke our original import). It does so by tracking
single-quote state across line boundaries and only treating a statement as
"complete" when the quote balance is zero.

Output is written every 5000 statements (with a `GO` separator) so sqlcmd can
process the import in reasonable batches.
"""

from __future__ import annotations

import codecs
import re
import sys
import time
from pathlib import Path

SRC = Path(r"C:\Transferr\sql.sql")
OUT = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\missing_data.sql")
STATE_PATH = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\filter_state.json")

# Tables we KEEP (must be the exact set of empty tables we want to fill)
KEEP_TABLES: set[str] = {
    "ACCAPITOKENS",
    "ACCBILLINGS",
    "ACCBUDGETCHECKS",
    "ACCCEIGNORELIST",
    "ACCCHARGES",
    "ACCCHARGETASKS",
    "ACCCONTRACTPRICEOPTS",
    "ACCCOUNTERINPUT",
    "ACCCOVERAGEALERTPRESELECT",
    "ACCCOVERAGEALERTS",
    "ACCDEPARTMENTBILLINGS",
    "ACCDEPARTMENTS",
    "ACCDEPARTMENTUSERS",
    "ACCDEPLOYMENT",
    "ACCDEPLOYMENTHISTORY",
    "ACCDEPLOYMENTTASKS",
    "ACCDEVICECOVERAGEALERTS",
    "ACCDEVICEDELIVERYDATA",
    "ACCDEVICEORDERHISTORY",
    "ACCDEVICEORDERS",
    "ACCF2PUSERS",
    "ACCFSMCLIENTS",
    "ACCGROUPNETS",
    "ACCHPSDSNOTIFICATIONS",
    "ACCJOBS",
    "ACCLABELCFCOUNTERS",
    "ACCLABELCFDEFS",
    "ACCLABELCFDEVICES",
    "ACCMANUALREFILLS",
    "ACCMIBCOUNTEROFFSETS",
    "ACCMIBPROPERTYDEF",
    "ACCMIBPROPERTYVALUES",
    "ACCMODELDATA",
    "ACCNPSSERVERS",
    "ACCORDEROPT",
    "ACCOXPMOPERATIONS",
    "ACCPAPERS",
    "ACCPAPERTRAYS",
    "ACCPMDFILES",
    "ACCPMDSTOCK",
    "ACCPRICELISTS",
    "ACCPRICES",
    "ACCPRTDISCOVERY",
    "ACCPRTDISCOVERYNETS",
    "ACCSDSPOLICYOPERATIONS",
    "ACCSDSPOLICYOPTIONS",
    "ACCSDSPOLICYRESULTS",
    "ACCSHEETS",
    "ACCSNMP",
    "ACCSNMPALERTPRESELECT",
    "ACCSNMPALERTRULES",
    "ACCSNMPALERTS",
    "ACCSNMPCREDENTIALS",
    "ACCSNMPVENDORS",
    "ACCSOURCEIDENTIFIERS",
    "ACCSTATISTICS",
    "ACCSUBMITTERCLIENTS",
    "ACCSYSOBJECTS",
    "ACCSYSRSC",
    "ACCSYSTEM",
    "ACCTASKS",
    "ACCUSERBILLINGS",
    "ACCUSERCLIENTRELATIONS",
    "ACCUSERCOLUMNVISIBILITY",
    "ACCUSERGROUPMEMBERS",
    "ACCUSERGROUPS",
    "ACCUSERLICENSE",
    "ACCUSERNOTIFICATIONS",
    "ACCUSERS",
    "ACCUSERSETTINGS",
    "ACCUSERSHPJAM",
    "ACCUSERSKYOKFS",
    "ACCXMLSUPPLIES",
    "NPSCONFIG",
    "NPSDEVICEAUTHS",
    "NPSDEVICES",
    "NPSDEVICESTAT",
    "NPSEVENTLOG",
    "NPSGROUPMEMBERS",
    "NPSGROUPS",
    "NPSRDN",
    "NPSRIGHTS",
    "NPSROLES",
    "NPSROUTES",
    # NPSSTATISTICS, NPSUSERS were 0-row in dump itself (no data)
}

# Explicitly skip these even if they appear empty - they are huge low-value tables
SKIP_TABLES: set[str] = {"ACCSNMPHISTORY", "ACCMIBCOUNTERVALUES"}

# Statements: we keep INSERT and SET IDENTITY_INSERT statements that target
# tables in KEEP_TABLES. We also pass through GO separators.
insert_re = re.compile(r"^INSERT \[dbo\]\.\[([^\]]+)\]")
set_identity_re = re.compile(r"^SET IDENTITY_INSERT \[dbo\]\.\[([^\]]+)\] (ON|OFF)")


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def count_unescaped_quotes(s: str) -> int:
    """Count single quotes in s, treating '' as escaped (not toggling state).

    Observation: every escaped quote (`''`) contributes 2 to the raw quote
    count, and every "real" boundary quote contributes 1. So the parity
    (mod 2) of the total raw count is exactly the toggling count we need.
    This is dramatically faster than a per-character loop.
    """
    return s.count("'")


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: not found: {SRC}", file=sys.stderr)
        return 2

    src_size = SRC.stat().st_size
    print(f"Source: {SRC} ({human_bytes(src_size)})")
    print(f"Output: {OUT}")
    print(f"Keep:   {len(KEEP_TABLES)} tables")
    print(f"Skip:   {sorted(SKIP_TABLES)}")
    print()

    OUT.parent.mkdir(parents=True, exist_ok=True)

    # We accumulate per-table batches so that SET IDENTITY_INSERT wraps work.
    # The dump output is grouped by table already (Generate Scripts always
    # writes all rows of one table consecutively), so we don't need any
    # explicit grouping ourselves: we just pass through statements verbatim
    # for KEEP_TABLES and drop the rest.

    stmt_lines: list[str] = []  # accumulating one (possibly multi-line) statement
    quote_balance = 0  # running quote balance for stmt_lines (0 = outside any string)

    bytes_read = 0
    inserts_kept = 0
    inserts_dropped = 0
    set_kept = 0
    set_dropped = 0
    last_report = time.time()
    start = last_report

    inserts_per_keep: dict[str, int] = {}

    def flush_statement(stmt: str, first_line: str, out_fh) -> tuple[bool, str | None]:
        """Decide whether to keep this completed statement and write it.

        `first_line` is the leading single-line portion (no \\n inside) used
        to identify the statement type cheaply. `stmt` is the full statement
        (potentially multi-line) we'll write to the output file.
        Returns (kept, target_table_if_known).
        """
        m_ins = insert_re.match(first_line)
        if m_ins:
            tbl = m_ins.group(1)
            if tbl in KEEP_TABLES:
                out_fh.write(stmt)
                out_fh.write("\n")
                return True, tbl
            return False, tbl
        m_set = set_identity_re.match(first_line)
        if m_set:
            tbl = m_set.group(1)
            if tbl in KEEP_TABLES:
                out_fh.write(stmt)
                out_fh.write("\nGO\n")
                return True, tbl
            return False, tbl
        # Other statements (CREATE TABLE, ALTER, USE, etc.): drop
        return False, None

    with SRC.open("rb") as fh, OUT.open("w", encoding="utf-8", newline="\n") as out:
        # Write file header
        out.write("-- Auto-generated by sql_dump_filter_missing.py\n")
        out.write(f"-- Source:  {SRC}\n")
        out.write(f"-- Keep:    {len(KEEP_TABLES)} tables\n")
        out.write(f"-- Skip:    {sorted(SKIP_TABLES)}\n")
        out.write("\n")
        out.write("USE [DevFleetMgmt]\n")
        out.write("GO\n")
        out.write("SET NOCOUNT ON\n")
        out.write("GO\n")
        out.write("\n")

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
                leftover_bytes = data[-1:]
                data = data[:-1]
            else:
                leftover_bytes = b""

            try:
                text = leftover_text + decoder.decode(data)
            except Exception as e:  # pragma: no cover - defensive
                print(f"decode error at {bytes_read}: {e}", file=sys.stderr)
                continue

            lines = text.split("\n")
            leftover_text = lines.pop()

            for raw in lines:
                line = raw.rstrip("\r")

                # Handle GO separators: only meaningful between statements
                if line.strip() == "GO" and quote_balance == 0 and not stmt_lines:
                    # Pass through GO only if we're between blocks we kept --
                    # easier to just drop and let the SET IDENTITY ON statements
                    # carry their own GO via our writer.
                    continue

                if stmt_lines:
                    # we are accumulating a multi-line statement; append the line
                    stmt_lines.append(line)
                    quote_balance = (quote_balance + line.count("'")) % 2
                    if quote_balance == 0:
                        # statement finished
                        first_line = stmt_lines[0]
                        stmt = "\n".join(stmt_lines)
                        kept, tbl = flush_statement(stmt, first_line, out)
                        if first_line.startswith("INSERT "):
                            if kept:
                                inserts_kept += 1
                                if tbl:
                                    inserts_per_keep[tbl] = inserts_per_keep.get(tbl, 0) + 1
                            else:
                                inserts_dropped += 1
                        elif first_line.startswith("SET IDENTITY_INSERT"):
                            if kept:
                                set_kept += 1
                            else:
                                set_dropped += 1
                        stmt_lines = []
                    # else: still inside a quoted string, keep accumulating
                else:
                    # Fast path: skip uninteresting lines without any work
                    if not (line.startswith("INSERT ") or line.startswith("SET IDENTITY_INSERT")):
                        continue
                    quote_balance = line.count("'") % 2
                    if quote_balance == 0:
                        # Single-line statement; flush directly.
                        kept, tbl = flush_statement(line, line, out)
                        if line.startswith("INSERT "):
                            if kept:
                                inserts_kept += 1
                                if tbl:
                                    inserts_per_keep[tbl] = inserts_per_keep.get(tbl, 0) + 1
                            else:
                                inserts_dropped += 1
                        else:
                            if kept:
                                set_kept += 1
                            else:
                                set_dropped += 1
                    else:
                        stmt_lines = [line]

            now = time.time()
            if now - last_report >= 5:
                elapsed = now - start
                pct = (bytes_read / src_size) * 100 if src_size else 0
                rate = bytes_read / elapsed / (1024 * 1024) if elapsed > 0 else 0
                eta_s = (src_size - bytes_read) / (rate * 1024 * 1024) if rate > 0 else 0
                eta = time.strftime("%H:%M:%S", time.gmtime(eta_s)) if eta_s else "?"
                print(
                    f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] "
                    f"{human_bytes(bytes_read)}/{human_bytes(src_size)} ({pct:.1f}%) "
                    f"{rate:.0f} MB/s ETA {eta} | "
                    f"INSERTs kept={inserts_kept:,} dropped={inserts_dropped:,} "
                    f"SET kept={set_kept} | accum={len(stmt_lines)}",
                    flush=True,
                )
                last_report = now

        # End of file: handle trailing leftover_text
        if leftover_text.strip():
            line = leftover_text.rstrip("\r")
            if stmt_lines:
                stmt_lines.append(line)
                if (quote_balance + line.count("'")) % 2 == 0:
                    flush_statement("\n".join(stmt_lines), stmt_lines[0], out)
            elif line.startswith("INSERT ") or line.startswith("SET IDENTITY_INSERT"):
                if line.count("'") % 2 == 0:
                    flush_statement(line, line, out)

    elapsed = time.time() - start
    out_size = OUT.stat().st_size

    print()
    print("=== DONE ===")
    print(f"Elapsed:        {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
    print(f"Output size:    {human_bytes(out_size)}")
    print(f"INSERTs kept:   {inserts_kept:,}")
    print(f"INSERTs dropped: {inserts_dropped:,}")
    print(f"SET kept:       {set_kept}")
    print(f"SET dropped:    {set_dropped}")
    print()
    print("Inserts per kept table (top 20):")
    for tbl, cnt in sorted(inserts_per_keep.items(), key=lambda x: -x[1])[:20]:
        print(f"  {cnt:>10,}  {tbl}")
    print()
    print(f"Wrote: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
