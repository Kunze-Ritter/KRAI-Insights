"""Extract first N INSERTs per specific tables of interest, scanning the whole dump.

Reads the 168 GB UTF-16 LE file, for each target table captures up to N samples,
short-circuits once everything is collected (since the dump is grouped by table,
once we've moved past a table we won't see it again).
"""

from __future__ import annotations

import codecs
import re
import sys
import time
from pathlib import Path

SRC = Path(r"C:\Transferr\sql.sql")
OUT = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\targeted_samples.sql")

TARGETS = {
    "ACCDEVICES": 5,
    "ACCMODELDATA": 5,
    "ACCFIRMWARE": 5,
    "ACCDEVICEMAINTENANCE": 5,
    "ACCDEVICECONTRACTS": 5,
    "ACCSUBMITTERCLIENTS": 5,
    "ACCEVENTHISTORY": 5,
    "ACCMARKERREFILL": 5,
    "ACCMIBPROPERTYVALUES": 5,
    "ACCMIBCOUNTERTEMPLATE": 5,
    "ACCMIBCOUNTERDEF": 5,
    "ACCDEVICEALIAS": 5,
    "ACCDEVICEMARKERCOVERAGE": 5,
    "ACCMARKERCOVERAGE": 5,
    "ACCINPUTTRAYS": 5,
    "ACCDEVICEVENDORS": 30,  # vendor list - capture all
    "ACCMAINTENANCE": 21,  # whole table (21 rows)
    "ACCMARKERALERT": 50,
    "ACCFMREPORTING": 5,
    "ACCCONTRACTS": 5,
    "ACCBRINFO": 5,
    "ACCFORMATS": 10,
}

insert_re = re.compile(r"^INSERT \[dbo\]\.\[([^\]]+)\]")


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: not found: {SRC}", file=sys.stderr)
        return 2

    samples: dict[str, list[str]] = {t: [] for t in TARGETS}
    counts: dict[str, int] = {t: 0 for t in TARGETS}
    bytes_read = 0
    start = time.time()
    last_report = start
    line_count = 0
    target_set = set(TARGETS.keys())
    done_set: set[str] = set()

    with SRC.open("rb") as fh:
        bom = fh.read(2)
        bytes_read += 2
        if bom != b"\xff\xfe":
            print(f"WARNING: expected UTF-16 LE BOM, got {bom!r}")

        decoder = codecs.getincrementaldecoder("utf-16-le")(errors="replace")
        leftover = ""

        while True:
            buf = fh.read(16 * 1024 * 1024)
            if not buf:
                break
            bytes_read += len(buf)
            text = leftover + decoder.decode(buf)
            lines = text.split("\n")
            leftover = lines.pop()

            for raw in lines:
                line_count += 1
                line = raw.rstrip("\r")
                m = insert_re.match(line)
                if not m:
                    continue
                tbl = m.group(1)
                if tbl not in target_set or tbl in done_set:
                    continue
                if counts[tbl] < TARGETS[tbl]:
                    samples[tbl].append(line[:4000])
                    counts[tbl] += 1
                    if counts[tbl] >= TARGETS[tbl]:
                        done_set.add(tbl)
                        print(f"  done: {tbl} ({counts[tbl]} samples) - {len(done_set)}/{len(TARGETS)}")
                        if len(done_set) == len(TARGETS):
                            print("All targets satisfied, stopping early.")
                            now = time.time()
                            elapsed = now - start
                            print(f"Scanned {bytes_read/1024/1024/1024:.1f} GB in {elapsed:.1f}s")
                            _write(samples)
                            return 0

            now = time.time()
            if now - last_report >= 10:
                elapsed = now - start
                rate = bytes_read / elapsed / (1024 * 1024) if elapsed > 0 else 0
                pending = [t for t in TARGETS if t not in done_set]
                print(
                    f"[{elapsed:6.1f}s] {bytes_read/1024/1024/1024:.1f} GB | {rate:.0f} MB/s | "
                    f"done={len(done_set)}/{len(TARGETS)} pending={pending[:4]}",
                    flush=True,
                )
                last_report = now

    _write(samples)
    print("\nDone (end of file reached).")
    return 0


def _write(samples: dict[str, list[str]]) -> None:
    out_lines = []
    for tbl in TARGETS:
        if samples[tbl]:
            out_lines.append(f"-- ============== {tbl} ({len(samples[tbl])} rows) ==============")
            out_lines.extend(samples[tbl])
            out_lines.append("")
    OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
