"""
Konfigurations-/Umgebungs-Check beim Start.

Prüft, dass die wichtigen `.env`-Werte gesetzt und plausibel sind, BEVOR sie erst
tief im ETL/UI als unklarer Fehler auffallen. Bewusst tolerant: im offenen Dev-/
Docker-Netz sind leere Passwörter ok — dort gibt es nur Warnungen, kein Abbruch.
Mit `--strict` (für Prod-Deploy / CI) führen Probleme zu Exit-Code 1.

    python scripts/env_check.py            # nur prüfen + ausgeben
    python scripts/env_check.py --strict   # Exit 1, wenn Probleme gefunden

Als Bibliothek (vom App-/Scheduler-Start, nicht-fatal):
    from scripts.env_check import check_env
    check_env()   # loggt Warnungen, wirft nie
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from insights.core.config import get_settings  # noqa: E402
from insights.core.logging import get_logger  # noqa: E402

logger = get_logger("env_check")


def collect_problems() -> list[str]:
    """Liste plausibler Konfigurationsprobleme (leer = alles ok)."""
    try:
        s = get_settings()
    except Exception as exc:  # malformed .env / Validation
        return [f".env konnte nicht geladen werden: {exc}"]

    problems: list[str] = []
    is_prod = s.app_env.lower() not in ("dev", "development", "local", "test")

    # Insights-DB: das einzige Ziel, in das wir schreiben — in Prod muss ein Passwort stehen.
    if not s.insights_db_password and is_prod:
        problems.append("INSIGHTS_DB_PASSWORD ist leer (in Produktion erforderlich).")

    # Quellen-Credentials: ohne sie liefert das ETL still leere Ergebnisse.
    if not s.fleetmgmt_mssql_password:
        problems.append("FLEETMGMT_MSSQL_PASSWORD ist leer — FleetMgmt-ETL wird scheitern.")
    if not s.krai_pg_password:
        problems.append("KRAI_PG_PASSWORD ist leer — KRAI-Anreicherung wird scheitern.")
    if not s.is_radix_configured:
        problems.append(
            "Radix ist unvollständig konfiguriert (RADIX_USERNAME / _PASSWORD_BASE64 / "
            "_CLIENT_CODE / _LICENSE_ID) — Radix-Crawls werden scheitern."
        )

    # Dashboard offen im Prod-Betrieb.
    if is_prod and not s.dashboard_password:
        problems.append("DASHBOARD_PASSWORD ist leer, obwohl APP_ENV nicht dev — Dashboard ist offen.")

    # LLM-Provider plausibel?
    if s.llm_provider.lower() == "openrouter" and not s.openrouter_api_key:
        problems.append("LLM_PROVIDER=openrouter, aber OPENROUTER_API_KEY fehlt (fällt auf Ollama zurück).")

    return problems


def check_env(strict: bool = False) -> bool:
    """Loggt Probleme; gibt True zurück, wenn sauber. Wirft nie (für App-/Scheduler-Start)."""
    problems = collect_problems()
    if not problems:
        logger.info("env-Check: Konfiguration ist plausibel.")
        return True
    level = logger.error if strict else logger.warning
    level("env-Check: %d Punkt(e):", len(problems))
    for p in problems:
        level("  - %s", p)
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insights env/config check")
    parser.add_argument("--strict", action="store_true", help="Exit 1, wenn Probleme gefunden")
    args = parser.parse_args()
    ok = check_env(strict=args.strict)
    raise SystemExit(0 if ok or not args.strict else 1)
