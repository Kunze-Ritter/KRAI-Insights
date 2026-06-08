"""
PII-Schema-Scan für die Insights-DB (DSGVO-Verifikation).

Prüft das `insights`-Schema auf Spaltennamen, die auf personenbezogene Daten
hindeuten (E-Mail, Telefon/Fax, Passwort/Token, Geburtsdatum, Kontakt-Person).
Erfüllt die in CLAUDE.md versprochene "schema PII-scan"-Verifikation und den
offenen Punkt aus todo_security.md.

WICHTIG zur Policy: Firmenname + Ort sind erlaubt; der Drucker-eigene Management-IP/
MAC ist erlaubt. Daher scannen wir NICHT pauschal auf "name"/"ip" (zu viele legitime
Treffer: model_display, customer_name=Firma, printer_ip, mac_address), sondern gezielt
auf echte Personen-/Credential-Muster. Eine kleine Allowlist deckt bekannte, geprüfte
Ausnahmen ab.

    python scripts/pii_schema_scan.py

Exit-Codes: 0 = sauber · 1 = verdächtige Spalte(n) gefunden · 2 = DB nicht erreichbar.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from insights.core.db import insights_engine  # noqa: E402
from insights.core.logging import get_logger  # noqa: E402

logger = get_logger("pii_scan")

# Gezielte PII-/Credential-Muster (SQL ILIKE). Bewusst KEIN generisches "%name%"/"%ip%"
# — Firmenname/Ort und der Drucker-eigene IP/MAC sind laut Policy erlaubt.
_SUSPECT_PATTERNS = [
    "%email%", "%e_mail%", "%mail%",
    "%phone%", "%telefon%", "%mobile%", "%fax%",
    "%password%", "%passwort%", "%secret%", "%token%", "%credential%",
    "%ssn%", "%geburt%", "%birthday%", "%birthdate%",
    "%contact_person%", "%kontaktperson%", "%ansprechpartner%",
    "%client_ip%", "%clientip%",  # Personen-Client-IP ist ausgeschlossen (≠ printer_ip)
]

# Geprüfte, erlaubte Ausnahmen (schema.tabelle.spalte), falls ein Muster legitim trifft.
_ALLOWLIST: set[str] = set()


def scan() -> int:
    rows: list[tuple[str, str]] = []
    try:
        with insights_engine().connect() as conn:
            like = " OR ".join(f"lower(column_name) LIKE '{p}'" for p in _SUSPECT_PATTERNS)
            sql = (
                "SELECT table_name, column_name FROM information_schema.columns "
                f"WHERE table_schema = 'insights' AND ({like}) "
                "ORDER BY table_name, column_name"
            )
            rows = [(r.table_name, r.column_name) for r in conn.execute(text(sql))]
    except Exception as exc:
        logger.error("PII-Scan: DB nicht erreichbar (%s) — übersprungen", exc)
        return 2

    hits = [(t, c) for (t, c) in rows if f"insights.{t}.{c}" not in _ALLOWLIST]
    if not hits:
        logger.info("PII-Scan sauber: keine verdächtigen Spalten im insights-Schema.")
        return 0

    logger.error("PII-Scan: %d verdächtige Spalte(n) gefunden:", len(hits))
    for t, c in hits:
        logger.error("  insights.%s.%s", t, c)
    logger.error("Bitte prüfen: echtes PII entfernen oder (geprüft) in _ALLOWLIST aufnehmen.")
    return 1


if __name__ == "__main__":
    raise SystemExit(scan())
