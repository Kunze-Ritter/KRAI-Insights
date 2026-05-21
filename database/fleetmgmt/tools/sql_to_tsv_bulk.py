"""Convert the sanitised INSERT-per-line SQL file into TSV files suitable
for SQL Server BULK INSERT, one file per target table.

We pick exotic field/row terminators that won't appear in printer
fleet-management data:
  * FIELDTERMINATOR = 0x1F  (UNIT SEPARATOR)
  * ROWTERMINATOR   = 0x1E + 0x0A (RECORD SEPARATOR + LF)

Within strings the value is written as-is (including embedded newlines).
NULL becomes an empty field. The SQL "N'...'" string prefix is stripped.
CAST(N'<value>' AS <type>) is unwrapped to just the inner value.

Output files:
  /scripts/accsnmphistory.tsv
  /scripts/accmibcountervalues.tsv
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

IN = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\scripts\bigtables_data.sql")
OUT_DIR = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\scripts")

FIELD_SEP = "\x1f"
ROW_SEP = "\x1e\n"

OUT_FILES = {
    "ACCSNMPHISTORY": OUT_DIR / "accsnmphistory.tsv",
    "ACCMIBCOUNTERVALUES": OUT_DIR / "accmibcountervalues.tsv",
}

INSERT_RE = re.compile(r"^INSERT \[dbo\]\.\[([^\]]+)\] \(([^)]*)\) VALUES \((.*)\)\s*$")


def parse_values(text: str) -> list[str | None]:
    """Parse the contents of a VALUES (...) tuple into a list of fields.

    Each element is either:
      * None (for SQL NULL)
      * a str (already unwrapped: CAST() removed, N'...' unwrapped, escapes
        like '' → ', and our sanitiser sequence
        `' + CHAR(10) + N'` → '\\n')
    """
    out: list[str | None] = []
    i = 0
    n = len(text)

    while i < n:
        # skip leading whitespace/commas
        while i < n and text[i] in " ,":
            i += 1
        if i >= n:
            break

        # NULL literal?
        if text[i : i + 4].upper() == "NULL" and (i + 4 == n or (not text[i + 4].isalnum() and text[i + 4] != "_")):
            out.append(None)
            i += 4
            continue

        # CAST(...) wrapper?
        if text[i : i + 5].upper() == "CAST(":
            # find matching close paren, then strip the " AS <type>" suffix from the inside.
            j = i + 5
            depth = 1
            in_str = False
            while j < n and depth > 0:
                c = text[j]
                if c == "'":
                    if in_str and j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    in_str = not in_str
                elif not in_str:
                    if c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                        if depth == 0:
                            break
                j += 1
            inner = text[i + 5 : j]
            # strip "... AS DateTime2" / AS Date / AS Decimal(...)
            m_as = re.search(r"\s+AS\s+[A-Za-z0-9_]+(?:\([^)]*\))?\s*$", inner)
            if m_as:
                inner = inner[: m_as.start()]
            inner = inner.strip()
            # inner is now a value expression (e.g. N'2017-...' or 12.5)
            sub = parse_values(inner)
            if sub:
                out.append(sub[0])
            else:
                out.append(None)
            i = j + 1
            continue

        # N'...' or '...' string literal
        if text[i] == "N" and i + 1 < n and text[i + 1] == "'":
            i += 1  # skip N
        if text[i] == "'":
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == "'":
                    # check '' escape
                    if i + 1 < n and text[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(c)
                i += 1
            # Look ahead for `' + CHAR(10) + N'` sanitiser concat sequences.
            while True:
                # skip optional whitespace
                k = i
                while k < n and text[k] == " ":
                    k += 1
                if text[k : k + 4] == "+ CH" or text[k : k + 5] == "+ CHA":
                    # try to match "+ CHAR(NN) + N'..."
                    m_concat = re.match(r"\+\s*CHAR\((\d+)\)\s*\+\s*N'", text[k:])
                    if not m_concat:
                        break
                    buf.append(chr(int(m_concat.group(1))))
                    i = k + m_concat.end()
                    # now read the next string literal until matching '
                    while i < n:
                        c = text[i]
                        if c == "'":
                            if i + 1 < n and text[i + 1] == "'":
                                buf.append("'")
                                i += 2
                                continue
                            i += 1
                            break
                        buf.append(c)
                        i += 1
                    continue
                break
            out.append("".join(buf))
            continue

        # numeric / bare token: read until comma at depth 0 (won't have parens here, since CAST handled above)
        start = i
        depth = 0
        while i < n:
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "," and depth == 0:
                break
            i += 1
        token = text[start:i].strip()
        if not token or token.upper() == "NULL":
            out.append(None)
        else:
            out.append(token)
    return out


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def main() -> int:
    if not IN.exists():
        print(f"ERROR: {IN} not found", file=sys.stderr)
        return 2

    src_size = IN.stat().st_size
    print(f"Input:  {IN} ({human_bytes(src_size)})")
    print(f"FIELD:  0x{ord(FIELD_SEP):02X}")
    print(f"ROW:    0x{ord(ROW_SEP[0]):02X} + LF")
    for tbl, path in OUT_FILES.items():
        print(f"Out:    {path}  -> {tbl}")
    print()

    out_fh = {tbl: path.open("w", encoding="utf-8", newline="") for tbl, path in OUT_FILES.items()}
    counts = {tbl: 0 for tbl in OUT_FILES}
    skipped = 0
    other = 0
    start = time.time()
    last_report = start

    try:
        with IN.open("r", encoding="utf-8", newline="") as in_fh:
            while True:
                raw = in_fh.readline()
                if not raw:
                    break
                line = raw.rstrip("\r\n")
                if not line or not line.startswith("INSERT [dbo]"):
                    other += 1
                    continue
                m = INSERT_RE.match(line)
                if not m:
                    skipped += 1
                    continue
                tbl = m.group(1)
                if tbl not in out_fh:
                    skipped += 1
                    continue
                vals_text = m.group(3)
                try:
                    fields = parse_values(vals_text)
                except Exception as e:
                    skipped += 1
                    if skipped < 5:
                        print(f"parse error {tbl}: {e}; line head: {line[:200]!r}", file=sys.stderr)
                    continue
                tsv_fields: list[str] = []
                for f in fields:
                    if f is None:
                        tsv_fields.append("")
                    else:
                        tsv_fields.append(str(f))
                out_fh[tbl].write(FIELD_SEP.join(tsv_fields))
                out_fh[tbl].write(ROW_SEP)
                counts[tbl] += 1

                now = time.time()
                if now - last_report >= 10:
                    elapsed = now - start
                    pos = in_fh.tell()
                    pct = (pos / src_size) * 100 if src_size else 0
                    rate = sum(counts.values()) / elapsed if elapsed else 0
                    eta_s = (src_size - pos) / (pos / elapsed) if pos and elapsed else 0
                    eta = time.strftime("%H:%M:%S", time.gmtime(eta_s)) if eta_s else "?"
                    counts_str = " ".join(f"{t}={c:,}" for t, c in counts.items())
                    print(
                        f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] "
                        f"{human_bytes(pos)}/{human_bytes(src_size)} ({pct:.1f}%) "
                        f"rate={rate:,.0f}/s ETA {eta} | {counts_str}",
                        flush=True,
                    )
                    last_report = now
    finally:
        for fh in out_fh.values():
            fh.close()

    elapsed = time.time() - start
    print()
    print("=== DONE ===")
    print(f"Elapsed:  {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
    for tbl, cnt in counts.items():
        size = OUT_FILES[tbl].stat().st_size if OUT_FILES[tbl].exists() else 0
        print(f"  {tbl:<28} {cnt:>12,} rows -> {human_bytes(size)}  ({OUT_FILES[tbl]})")
    print(f"Pass-through lines: {other}")
    print(f"Skipped (parse fail / unknown table): {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
