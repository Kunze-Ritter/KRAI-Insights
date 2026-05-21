"""Fast scanner for huge MSSQL dump files (UTF-16 LE).

MSSQL Management Studio Generate-Scripts produces UTF-16 LE files with a BOM.
This scanner reads the file in large chunks, decodes UTF-16 LE -> str, splits
at newlines and tracks CREATE TABLE / INSERT statements per table.

The actual file is 168 GB on disk, but as UTF-16 that's only ~84 GB of text.
"""

from __future__ import annotations

import re
import sys
import time
from collections import defaultdict
from pathlib import Path

SRC = Path(r"C:\Transferr\sql.sql")
OUT = Path(r"C:\Users\haast\Docker\KRAI-minimal\docs\fleetmgmt_table_stats.txt")

CHUNK = 32 * 1024 * 1024  # 32 MB

create_re = re.compile(r"CREATE TABLE \[dbo\]\.\[([^\]]+)\]")
insert_re = re.compile(r"INSERT \[dbo\]\.\[([^\]]+)\]")


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: not found: {SRC}", file=sys.stderr)
        return 2

    size = SRC.stat().st_size
    print(f"Scanning {SRC} ({human_bytes(size)})")

    tables: set[str] = set()
    inserts: dict[str, int] = defaultdict(int)
    bytes_read = 0
    start = time.time()
    last_report = start
    leftover_bytes = b""

    with SRC.open("rb") as f:
        # Skip UTF-16 LE BOM (2 bytes: 0xFF 0xFE)
        bom = f.read(2)
        bytes_read += 2
        if bom != b"\xff\xfe":
            print(f"WARNING: expected UTF-16 LE BOM, got {bom!r}")

        while True:
            buf = f.read(CHUNK)
            if not buf:
                break
            bytes_read += len(buf)
            data = leftover_bytes + buf

            # Ensure even length for UTF-16 (2 bytes per code unit)
            if len(data) % 2 != 0:
                leftover_bytes = data[-1:]
                data = data[:-1]
            else:
                leftover_bytes = b""

            try:
                text = data.decode("utf-16-le", errors="replace")
            except Exception as e:  # pragma: no cover - defensive
                print(f"decode error at {bytes_read}: {e}")
                continue

            # Find last newline boundary to avoid splitting a line
            nl = text.rfind("\n")
            if nl < 0:
                # No newline in this chunk: keep the corresponding bytes for next round
                leftover_bytes = data + leftover_bytes
                continue
            scan = text[: nl + 1]
            tail_text = text[nl + 1 :]
            # Re-encode the tail back to bytes so it lines up with the next chunk
            leftover_bytes = tail_text.encode("utf-16-le") + leftover_bytes

            for m in create_re.finditer(scan):
                tables.add(m.group(1))
            for m in insert_re.finditer(scan):
                inserts[m.group(1)] += 1

            now = time.time()
            if now - last_report >= 5:
                elapsed = now - start
                pct = (bytes_read / size) * 100 if size else 0
                rate = bytes_read / elapsed / (1024 * 1024) if elapsed > 0 else 0
                eta_s = (size - bytes_read) / (rate * 1024 * 1024) if rate > 0 else 0
                eta = time.strftime("%H:%M:%S", time.gmtime(eta_s)) if eta_s else "?"
                total_inserts = sum(inserts.values())
                print(
                    f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] "
                    f"{human_bytes(bytes_read)} / {human_bytes(size)} "
                    f"({pct:.1f}%) | {rate:.1f} MB/s | ETA {eta} | "
                    f"tables={len(tables)} inserts={total_inserts:,}",
                    flush=True,
                )
                last_report = now

        if leftover_bytes:
            try:
                tail_text = leftover_bytes.decode("utf-16-le", errors="replace")
                for m in create_re.finditer(tail_text):
                    tables.add(m.group(1))
                for m in insert_re.finditer(tail_text):
                    inserts[m.group(1)] += 1
            except Exception:
                pass

    elapsed = time.time() - start
    total_inserts = sum(inserts.values())

    print("\n=== DONE ===")
    print(f"Elapsed:       {time.strftime('%H:%M:%S', time.gmtime(elapsed))}")
    print(f"Tables:        {len(tables):,}")
    print(f"INSERT rows:   {total_inserts:,}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Fleet Management SQL Dump - Statistics",
        f"Source:         {SRC}",
        f"Size on disk:   {human_bytes(size)} (UTF-16 LE; ~{human_bytes(size / 2)} effective text)",
        f"Scanned:        {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Tables:         {len(tables):,}",
        f"INSERT rows:    {total_inserts:,}",
        "",
        "All tables, sorted by row count (descending):",
        "---------------------------------------------",
    ]
    sorted_tables = sorted(
        ((name, inserts.get(name, 0)) for name in tables),
        key=lambda x: (-x[1], x[0]),
    )
    for name, cnt in sorted_tables:
        lines.append(f"{cnt:>14,}  {name}")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
