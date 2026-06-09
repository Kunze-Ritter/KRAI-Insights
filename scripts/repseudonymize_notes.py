"""
Bestehende activity_notes erneut pseudonymisieren (nach einer pii.py-Verschärfung).

Die Texte werden beim Crawl pseudonymisiert. Wird der Filter (insights/core/pii.py)
verbessert, sind ALTE Zeilen noch nach altem Stand — dieses Skript wendet die aktuelle
Pseudonymisierung in-place an (ohne Radix-Re-Crawl). Idempotent.

    python scripts/repseudonymize_notes.py            # anwenden
    python scripts/repseudonymize_notes.py --dry-run  # nur zählen, was sich ändern würde
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from insights.core.db import insights_engine  # noqa: E402
from insights.core.logging import get_logger  # noqa: E402
from insights.core.pii import pseudonymize_contacts  # noqa: E402

logger = get_logger("repseudonymize")
_FIELDS = ("problem_text", "technik_text", "verlauf_text")


def run(dry_run: bool = False) -> int:
    engine = insights_engine()
    with engine.connect() as conn:
        rows = list(conn.execute(text(
            "SELECT radix_activity_id, problem_text, technik_text, verlauf_text "
            "FROM insights.activity_notes"
        )))
    changes: list[dict[str, str | None]] = []
    for r in rows:
        cleaned = {f: pseudonymize_contacts(getattr(r, f)) for f in _FIELDS}
        if any(cleaned[f] != getattr(r, f) for f in _FIELDS):
            changes.append({"aid": r.radix_activity_id, **cleaned})
    logger.info("%d von %d Notizen würden bereinigt", len(changes), len(rows))
    if dry_run or not changes:
        return len(changes)
    with engine.begin() as conn:
        for i in range(0, len(changes), 1000):
            conn.execute(
                text("UPDATE insights.activity_notes SET problem_text=:problem_text, "
                     "technik_text=:technik_text, verlauf_text=:verlauf_text, ingested_at=now() "
                     "WHERE radix_activity_id=:aid"),
                changes[i:i + 1000],
            )
    logger.info("%d Notizen re-pseudonymisiert", len(changes))
    return len(changes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="activity_notes erneut pseudonymisieren")
    parser.add_argument("--dry-run", action="store_true", help="nur zählen")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
