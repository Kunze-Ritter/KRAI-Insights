"""Extract DDL (CREATE TABLE / CREATE INDEX / ALTER TABLE) from a UTF-16 MSSQL dump.

Smart strategy: most MSSQL "Generate Scripts" dumps put the entire schema (tables,
indexes, constraints) at the START of the file, then the INSERT batches follow.

Once we have seen all 119 CREATE TABLE statements AND we have hit our first INSERT,
we know we're past the schema section -- but indexes/FKs typically come AT THE END
of the dump (after all data). So we do two passes:

  Pass 1: read until first INSERT, capture all schema seen so far
  Pass 2: skip ahead in the file (seek) to grab the tail (~500 MB) for trailing
          ALTER TABLE / CREATE INDEX / constraints

Output:
  database/fleetmgmt/schema_head.sql    - schema before first INSERT
  database/fleetmgmt/schema_tail.sql    - last ~500 MB of file (constraints/indexes)
  database/fleetmgmt/sample_rows.sql    - first few INSERTs per table for inspection
"""

from __future__ import annotations

import codecs
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

SRC = Path(r"C:\Transferr\sql.sql")
OUT_DIR = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt")
OUT_HEAD = OUT_DIR / "schema_head.sql"
OUT_TAIL = OUT_DIR / "schema_tail.sql"
OUT_SAMPLES = OUT_DIR / "sample_rows.sql"

SAMPLES_PER_TABLE = 3
TAIL_BYTES = 1024 * 1024 * 1024  # last 1 GB of file (UTF-16 = 500 MB text)

insert_re = re.compile(r"^INSERT \[dbo\]\.\[([^\]]+)\]")


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def pass_head() -> tuple[int, dict[str, int], list[str]]:
    """Read from start, capture every line UNTIL we have captured a healthy
    number of INSERT samples (3 per table * ~30 tables seen)."""
    print("\n=== PASS 1: head schema ===")
    OUT_HEAD.write_text("", encoding="utf-8")  # truncate

    sample_count: dict[str, int] = defaultdict(int)
    sample_lines: list[str] = []
    head_buf: list[str] = []
    bytes_read = 0
    line_count = 0
    insert_count = 0
    start = time.time()
    last_report = start

    with SRC.open("rb") as fh:
        bom = fh.read(2)
        bytes_read += 2
        if bom != b"\xff\xfe":
            print(f"WARNING: expected UTF-16 LE BOM, got {bom!r}")

        decoder = codecs.getincrementaldecoder("utf-16-le")(errors="replace")
        leftover = ""

        while True:
            buf = fh.read(8 * 1024 * 1024)
            if not buf:
                break
            bytes_read += len(buf)
            text = leftover + decoder.decode(buf)
            lines = text.split("\n")
            leftover = lines.pop()

            for raw in lines:
                line_count += 1
                line = raw.rstrip("\r")

                # Detect INSERT and capture sample
                im = insert_re.match(line)
                if im:
                    insert_count += 1
                    tbl = im.group(1)
                    if sample_count[tbl] < SAMPLES_PER_TABLE:
                        sample_count[tbl] += 1
                        # Keep sample line (truncate to 2000 chars to avoid bloat)
                        sample_lines.append(line[:2000])
                    # When we hit the first INSERT, the schema head is done.
                    # We keep scanning so we collect samples for all tables.
                    continue

                # Pre-INSERT: this is pure schema, capture verbatim
                if insert_count == 0:
                    head_buf.append(line)
                else:
                    # We're now in INSERT-land; only collect samples from now on.
                    # Flush head_buf to disk once
                    if head_buf:
                        with OUT_HEAD.open("a", encoding="utf-8") as out:
                            out.write("\n".join(head_buf) + "\n")
                        head_buf.clear()

                # Stop early if we've collected enough samples from many tables
                if insert_count > 200_000 and len(sample_lines) >= 50:
                    # Probably have a decent sample; stop pass 1
                    print(f"  pass1: stop after {insert_count:,} inserts, {len(sample_lines)} samples")
                    if head_buf:
                        with OUT_HEAD.open("a", encoding="utf-8") as out:
                            out.write("\n".join(head_buf) + "\n")
                        head_buf.clear()
                    return bytes_read, dict(sample_count), sample_lines

            now = time.time()
            if now - last_report >= 5:
                elapsed = now - start
                rate = bytes_read / elapsed / (1024 * 1024) if elapsed > 0 else 0
                print(
                    f"  pass1 [{elapsed:6.1f}s] {human_bytes(bytes_read)} | "
                    f"{rate:.0f} MB/s | inserts={insert_count:,} samples={len(sample_lines)} "
                    f"tables_with_samples={len(sample_count)}",
                    flush=True,
                )
                last_report = now

    # End of file before threshold
    if head_buf:
        with OUT_HEAD.open("a", encoding="utf-8") as out:
            out.write("\n".join(head_buf) + "\n")
    return bytes_read, dict(sample_count), sample_lines


def pass_tail() -> None:
    """Read the last TAIL_BYTES of the file for trailing schema (indexes/FKs)."""
    print(f"\n=== PASS 2: tail schema (last {human_bytes(TAIL_BYTES)}) ===")
    size = SRC.stat().st_size
    offset = max(2, size - TAIL_BYTES)
    # UTF-16 = 2 bytes per char, align to even
    if offset % 2 == 1:
        offset += 1
    start = time.time()
    tail_lines: list[str] = []
    bytes_read = 0
    last_report = start
    insert_lines = 0
    schema_lines = 0

    with SRC.open("rb") as fh:
        fh.seek(offset)
        decoder = codecs.getincrementaldecoder("utf-16-le")(errors="replace")
        leftover = ""

        # First decoded char might be partial; the search for the first \n
        # restores alignment.
        first_chunk = True

        while True:
            buf = fh.read(8 * 1024 * 1024)
            if not buf:
                break
            bytes_read += len(buf)
            text = leftover + decoder.decode(buf)
            if first_chunk:
                # discard until first newline to avoid mid-line garbage
                nl = text.find("\n")
                if nl >= 0:
                    text = text[nl + 1 :]
                    first_chunk = False
                else:
                    leftover = text
                    continue

            lines = text.split("\n")
            leftover = lines.pop()

            for raw in lines:
                line = raw.rstrip("\r")
                if insert_re.match(line):
                    insert_lines += 1
                    continue
                tail_lines.append(line)
                schema_lines += 1

            now = time.time()
            if now - last_report >= 5:
                elapsed = now - start
                rate = bytes_read / elapsed / (1024 * 1024) if elapsed > 0 else 0
                print(
                    f"  pass2 [{elapsed:6.1f}s] {human_bytes(bytes_read)} | "
                    f"{rate:.0f} MB/s | tail_lines={schema_lines:,} skipped_inserts={insert_lines:,}",
                    flush=True,
                )
                last_report = now

        if leftover:
            tail_lines.append(leftover)

    OUT_TAIL.write_text("\n".join(tail_lines), encoding="utf-8")
    print(f"  pass2 done: {len(tail_lines):,} lines, skipped {insert_lines:,} INSERTs")


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: not found: {SRC}", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    size = SRC.stat().st_size
    print(f"Source: {SRC} ({human_bytes(size)})")

    bytes_read, sample_count, sample_lines = pass_head()
    OUT_SAMPLES.write_text("\n".join(sample_lines), encoding="utf-8")

    pass_tail()

    print("\n=== DONE ===")
    print(f"Head:    {OUT_HEAD}  ({human_bytes(OUT_HEAD.stat().st_size)})")
    print(f"Tail:    {OUT_TAIL}  ({human_bytes(OUT_TAIL.stat().st_size)})")
    print(f"Samples: {OUT_SAMPLES}  ({human_bytes(OUT_SAMPLES.stat().st_size)})")
    print(f"Tables w/ samples: {len(sample_count)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
