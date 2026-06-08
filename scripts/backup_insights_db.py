"""
Nächtliches Backup der Insights-DB (pg_dump) mit Aufbewahrung.

Die Insights-DB ist zwar aus den Quellen rebuildbar, aber NICHT alles: die
Lauf-Historie (scheduler_runs) und manuell gepflegte config-Daten gingen bei einem
Verlust verloren, und ein Rebuild dauert (Cost-Crawl ~16 min). Ein komprimierter
Dump je Nacht + Aufbewahrung ist billig und erspart das im Ernstfall.

Voraussetzung: `pg_dump` (Paket postgresql-client) muss verfügbar sein. Ist es nicht,
beendet sich das Skript mit einer klaren Meldung (kein stiller Fehlschlag).

    python scripts/backup_insights_db.py

Env:
    INSIGHTS_BACKUP_DIR             Zielverzeichnis (Standard: ./backups)
    INSIGHTS_BACKUP_RETENTION_DAYS  Aufbewahrung in Tagen (Standard: 30)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from insights.core.config import get_settings  # noqa: E402
from insights.core.logging import get_logger  # noqa: E402

logger = get_logger("backup")


def run_backup() -> Path:
    """Erzeugt einen komprimierten pg_dump und löscht alte Dumps. Gibt den Dateipfad zurück."""
    if shutil.which("pg_dump") is None:
        raise RuntimeError(
            "pg_dump nicht gefunden — bitte postgresql-client installieren "
            "(im App-Image: apt-get install -y postgresql-client)."
        )
    s = get_settings()
    backup_dir = Path(os.getenv("INSIGHTS_BACKUP_DIR", str(_REPO_ROOT / "backups")))
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = backup_dir / f"insights_{stamp}.dump"

    env = {**os.environ, "PGPASSWORD": s.insights_db_password}
    cmd = [
        "pg_dump",
        "-h", s.insights_db_host, "-p", str(s.insights_db_port),
        "-U", s.insights_db_user, "-d", s.insights_db_name,
        "-n", "insights", "-Fc", "-f", str(out),
    ]
    logger.info("pg_dump -> %s", out)
    subprocess.run(cmd, env=env, check=True, capture_output=True)

    retention_days = int(os.getenv("INSIGHTS_BACKUP_RETENTION_DAYS", "30"))
    cutoff = datetime.now().timestamp() - retention_days * 86400
    removed = 0
    for old in backup_dir.glob("insights_*.dump"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
            removed += 1
    logger.info("Backup ok (%.1f MB); %d alte Dumps entfernt (>%d Tage).",
                out.stat().st_size / 1e6, removed, retention_days)
    return out


if __name__ == "__main__":
    try:
        run_backup()
    except Exception as exc:
        logger.error("Backup fehlgeschlagen: %s", exc)
        raise SystemExit(1) from exc
