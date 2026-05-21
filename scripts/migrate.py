"""
Sequential SQL migration runner for the Insights DB.

Applies every `db/migrations/NNN_*.sql` file in order exactly once, tracked in
`insights.schema_migrations`. Idempotent: already-applied files are skipped, and
a checksum guards against editing a migration after it has been applied.

    python scripts/migrate.py            # apply all pending
    python scripts/migrate.py --status   # show applied vs pending

Per the plan we use plain SQL files (not ORM auto-migration) so the schema stays
portable back into KRAI's migrations_postgresql/ if we ever merge.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from sqlalchemy import text

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from insights.core.db import insights_engine  # noqa: E402
from insights.core.logging import get_logger  # noqa: E402

logger = get_logger("migrate")
MIGRATIONS_DIR = _REPO_ROOT / "db" / "migrations"


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _discover() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9]*.sql"))


def _ensure_tracking() -> None:
    with insights_engine().begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS insights")
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS insights.schema_migrations (
                filename   TEXT PRIMARY KEY,
                checksum   TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def _applied() -> dict[str, str]:
    with insights_engine().connect() as conn:
        rows = conn.execute(text("SELECT filename, checksum FROM insights.schema_migrations"))
        return {r.filename: r.checksum for r in rows}


def status() -> None:
    _ensure_tracking()
    applied = _applied()
    for path in _discover():
        mark = "applied" if path.name in applied else "PENDING"
        drift = ""
        if path.name in applied and applied[path.name] != _checksum(path.read_text(encoding="utf-8")):
            drift = " (CHECKSUM MISMATCH — file edited after apply!)"
        print(f"  [{mark:>7}] {path.name}{drift}")


def migrate() -> None:
    _ensure_tracking()
    applied = _applied()
    pending = [p for p in _discover() if p.name not in applied]
    if not pending:
        logger.info("No pending migrations. Schema is up to date.")
        return
    for path in pending:
        sql = path.read_text(encoding="utf-8")
        logger.info("Applying %s ...", path.name)
        with insights_engine().begin() as conn:
            conn.exec_driver_sql(sql)
            conn.execute(
                text(
                    "INSERT INTO insights.schema_migrations (filename, checksum) "
                    "VALUES (:f, :c)"
                ),
                {"f": path.name, "c": _checksum(sql)},
            )
        logger.info("  applied %s", path.name)
    logger.info("Applied %d migration(s).", len(pending))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insights DB migration runner")
    parser.add_argument("--status", action="store_true", help="show applied/pending without applying")
    args = parser.parse_args()
    if args.status:
        status()
    else:
        migrate()
