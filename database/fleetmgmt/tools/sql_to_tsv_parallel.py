"""Parallel version of sql_to_tsv_bulk.py: splits the sanitised INSERT-per-
line SQL file into N byte-range chunks, parses each chunk in a worker
process, and merges the per-worker TSVs into the final files.

CPU-bound parsing is the bottleneck of the single-threaded variant.
Spreading the work across all physical cores typically yields a 4-8x
speedup.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import re
import sys
import time
from pathlib import Path

IN = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\scripts\bigtables_data.sql")
OUT_DIR = Path(r"C:\Users\haast\Docker\KRAI-minimal\database\fleetmgmt\scripts")
TMP_DIR = OUT_DIR / "tsv_tmp"

FIELD_SEP = "\x1f"
ROW_SEP = "\x1e\n"

FINAL = {
    "ACCSNMPHISTORY": OUT_DIR / "accsnmphistory.tsv",
    "ACCMIBCOUNTERVALUES": OUT_DIR / "accmibcountervalues.tsv",
}

INSERT_RE = re.compile(r"^INSERT \[dbo\]\.\[([^\]]+)\] \(([^)]*)\) VALUES \((.*)\)\s*$")
_AS_RE = re.compile(r"\s+AS\s+[A-Za-z0-9_]+(?:\([^)]*\))?\s*$")
_CONCAT_RE = re.compile(r"\+\s*CHAR\((\d+)\)\s*\+\s*N'")


def parse_values(text: str) -> list[str | None]:
    out: list[str | None] = []
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i] in " ,":
            i += 1
        if i >= n:
            break

        if text[i : i + 4].upper() == "NULL" and (i + 4 == n or (not text[i + 4].isalnum() and text[i + 4] != "_")):
            out.append(None)
            i += 4
            continue

        if text[i : i + 5].upper() == "CAST(":
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
            m_as = _AS_RE.search(inner)
            if m_as:
                inner = inner[: m_as.start()]
            inner = inner.strip()
            sub = parse_values(inner)
            out.append(sub[0] if sub else None)
            i = j + 1
            continue

        if text[i] == "N" and i + 1 < n and text[i + 1] == "'":
            i += 1
        if text[i] == "'":
            i += 1
            buf: list[str] = []
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
            while True:
                k = i
                while k < n and text[k] == " ":
                    k += 1
                if k < n and text[k] == "+":
                    m_concat = _CONCAT_RE.match(text[k:])
                    if not m_concat:
                        break
                    buf.append(chr(int(m_concat.group(1))))
                    i = k + m_concat.end()
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


def worker(worker_id: int, start: int, end: int, in_path: str, tmp_dir: str, result_q: mp.Queue) -> None:
    out_paths = {
        "ACCSNMPHISTORY": Path(tmp_dir) / f"w{worker_id:02d}_accsnmphistory.tsv",
        "ACCMIBCOUNTERVALUES": Path(tmp_dir) / f"w{worker_id:02d}_accmibcountervalues.tsv",
    }
    out_fh = {tbl: p.open("w", encoding="utf-8", newline="") for tbl, p in out_paths.items()}
    counts = {tbl: 0 for tbl in out_paths}
    skipped = 0
    bytes_read = 0
    last_ping = time.time()

    try:
        with open(in_path, "rb") as fh:
            if start > 0:
                fh.seek(start - 1)
                # consume up to and including the next newline so we start at a clean line
                while True:
                    b = fh.read(1)
                    if not b or b == b"\n":
                        break
            else:
                fh.seek(0)

            while True:
                if fh.tell() >= end:
                    break
                raw = fh.readline()
                if not raw:
                    break
                bytes_read = fh.tell() - start
                try:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                except Exception:
                    skipped += 1
                    continue
                if not line.startswith("INSERT [dbo]"):
                    continue
                m = INSERT_RE.match(line)
                if not m:
                    skipped += 1
                    continue
                tbl = m.group(1)
                if tbl not in out_fh:
                    continue
                try:
                    fields = parse_values(m.group(3))
                except Exception:
                    skipped += 1
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
                if now - last_ping >= 5:
                    result_q.put(("ping", worker_id, dict(counts), bytes_read, skipped))
                    last_ping = now
    finally:
        for fh in out_fh.values():
            fh.close()
        result_q.put(("done", worker_id, dict(counts), bytes_read, skipped))


def main() -> int:
    if not IN.exists():
        print(f"ERROR: {IN} not found", file=sys.stderr)
        return 2

    n_workers = max(2, (os.cpu_count() or 8) - 1)
    src_size = IN.stat().st_size
    chunk = src_size // n_workers

    ranges: list[tuple[int, int]] = []
    for i in range(n_workers):
        s = i * chunk
        e = (i + 1) * chunk if i < n_workers - 1 else src_size
        ranges.append((s, e))

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Input:  {IN} ({src_size/1024/1024/1024:.1f} GB)")
    print(f"Workers: {n_workers}")
    print(f"Chunk:   {chunk/1024/1024/1024:.1f} GB each")
    print(f"Tmp:     {TMP_DIR}")
    print()

    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    procs = []
    for i, (s, e) in enumerate(ranges):
        p = ctx.Process(target=worker, args=(i, s, e, str(IN), str(TMP_DIR), q))
        p.start()
        procs.append(p)

    start = time.time()
    done_count = 0
    counts_per_worker: dict[int, dict[str, int]] = {
        i: {"ACCSNMPHISTORY": 0, "ACCMIBCOUNTERVALUES": 0} for i in range(n_workers)
    }
    bytes_per_worker: dict[int, int] = {i: 0 for i in range(n_workers)}

    while done_count < n_workers:
        msg = q.get()
        kind, wid, counts, bytes_read, skipped = msg
        counts_per_worker[wid] = counts
        bytes_per_worker[wid] = bytes_read
        if kind == "done":
            done_count += 1
            elapsed = time.time() - start
            snmp = sum(c["ACCSNMPHISTORY"] for c in counts_per_worker.values())
            mib = sum(c["ACCMIBCOUNTERVALUES"] for c in counts_per_worker.values())
            print(
                f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] worker {wid} done; total_snmp={snmp:,} total_mib={mib:,}",
                flush=True,
            )
        else:
            elapsed = time.time() - start
            snmp = sum(c["ACCSNMPHISTORY"] for c in counts_per_worker.values())
            mib = sum(c["ACCMIBCOUNTERVALUES"] for c in counts_per_worker.values())
            bytes_total = sum(bytes_per_worker.values())
            pct = 100 * bytes_total / src_size if src_size else 0
            rate = (snmp + mib) / elapsed if elapsed else 0
            eta_s = (src_size - bytes_total) / (bytes_total / elapsed) if bytes_total and elapsed else 0
            eta = time.strftime("%H:%M:%S", time.gmtime(eta_s)) if eta_s else "?"
            print(
                f"[{time.strftime('%H:%M:%S', time.gmtime(elapsed))}] {pct:5.1f}% rate={rate:,.0f}/s ETA {eta} | snmp={snmp:,} mib={mib:,}",
                flush=True,
            )

    for p in procs:
        p.join()

    # Merge per-worker outputs into final files
    print()
    print("=== merging ===")
    for tbl, dest in FINAL.items():
        with dest.open("wb") as out_fh:
            for wid in range(n_workers):
                src = TMP_DIR / f"w{wid:02d}_{tbl.lower()}.tsv"
                if not src.exists():
                    continue
                with src.open("rb") as src_fh:
                    while True:
                        buf = src_fh.read(32 * 1024 * 1024)
                        if not buf:
                            break
                        out_fh.write(buf)
        size = dest.stat().st_size
        print(f"  {tbl:<28} -> {size/1024/1024/1024:.1f} GB  ({dest})")

    print()
    print("=== DONE ===")
    total_elapsed = time.time() - start
    print(f"Elapsed: {time.strftime('%H:%M:%S', time.gmtime(total_elapsed))}")
    final_snmp = sum(c["ACCSNMPHISTORY"] for c in counts_per_worker.values())
    final_mib = sum(c["ACCMIBCOUNTERVALUES"] for c in counts_per_worker.values())
    print(f"ACCSNMPHISTORY:      {final_snmp:,}")
    print(f"ACCMIBCOUNTERVALUES: {final_mib:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
