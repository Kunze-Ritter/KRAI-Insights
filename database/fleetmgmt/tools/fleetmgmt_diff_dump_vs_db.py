"""Diff the original dump scan vs the live DB row counts and report
which tables are fully loaded, partially loaded, or missing rows."""

from pathlib import Path

STATS = Path(r"C:\Users\haast\Docker\KRAI-minimal\docs\fleetmgmt_table_stats.txt")
DBCNT = Path(r"C:\Users\haast\Docker\KRAI-minimal\docs\fleetmgmt_db_counts.txt")


def parse_stats():
    expected = {}
    in_section = False
    for line in STATS.read_text(encoding="utf-8").splitlines():
        if line.startswith("-----"):
            in_section = True
            continue
        if not in_section or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 2:
            count = int(parts[0].replace(",", ""))
            name = parts[1]
            expected[name] = count
    return expected


def parse_db():
    actual = {}
    for line in DBCNT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        name, _, count = line.partition(",")
        name = name.strip()
        try:
            actual[name] = int(count.strip())
        except ValueError:
            continue
    return actual


def main():
    expected = parse_stats()
    actual = parse_db()

    only_in_dump = sorted(set(expected) - set(actual))
    only_in_db = sorted(set(actual) - set(expected))
    common = sorted(set(expected) & set(actual))

    exact = []
    partial = []
    missing = []
    extra = []
    empty_in_both = []

    for t in common:
        e, a = expected[t], actual[t]
        if e == 0 and a == 0:
            empty_in_both.append(t)
        elif e == a:
            exact.append((t, e))
        elif a == 0:
            missing.append((t, e))
        elif a < e:
            partial.append((t, e, a))
        else:
            extra.append((t, e, a))

    print(f"Tables in dump scan:   {len(expected)}")
    print(f"Tables in live DB:     {len(actual)}")
    print(f"Common tables:         {len(common)}")
    print(f"Only in dump (missing in DB): {len(only_in_dump)}")
    print(f"Only in DB (extra):    {len(only_in_db)}")
    print()
    print(f"Exact match (count identical): {len(exact)}")
    print(f"Empty in both:                  {len(empty_in_both)}")
    print(f"Partial (DB < dump):           {len(partial)}")
    print(f"Missing (DB = 0, dump > 0):    {len(missing)}")
    print(f"Extra rows (DB > dump):        {len(extra)}")
    print()

    if partial:
        print("=== Partial loads (DB has fewer rows than dump) ===")
        total_missing_rows = 0
        for t, e, a in sorted(partial, key=lambda x: -(x[1] - x[2])):
            diff = e - a
            total_missing_rows += diff
            pct = 100 * a / e if e else 0
            print(f"  {t:<35} dump={e:>12,}  db={a:>12,}  missing={diff:>12,}  ({pct:5.1f}% loaded)")
        print(f"\n  TOTAL MISSING ROWS in partial loads: {total_missing_rows:,}")
        print()

    if missing:
        print("=== Completely missing (dump>0, DB=0) ===")
        for t, e in sorted(missing, key=lambda x: -x[1]):
            print(f"  {t:<35} dump={e:,}  db=0")
        print()

    if extra:
        print("=== Extra rows (DB > dump) ===")
        for t, e, a in extra:
            print(f"  {t:<35} dump={e:,}  db={a:,}")
        print()

    if only_in_dump:
        print(f"=== Tables in dump scan but NOT in DB ({len(only_in_dump)}) ===")
        for t in only_in_dump:
            print(f"  {t}  (dump={expected[t]:,})")
        print()
    if only_in_db:
        print(f"=== Tables in DB but NOT in dump scan ({len(only_in_db)}) ===")
        for t in only_in_db:
            print(f"  {t}  (db={actual[t]:,})")
        print()

    total_dump = sum(expected.values())
    total_db = sum(actual.values())
    print(f"Dump total rows:       {total_dump:,}")
    print(f"DB total rows:         {total_db:,}")
    print(f"Difference:            {total_dump - total_db:,} rows missing in DB")


if __name__ == "__main__":
    main()
