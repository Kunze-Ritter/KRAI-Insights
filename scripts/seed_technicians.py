"""
Entwurf für config/technicians.yaml aus dem Ticket-Call-Log raten.

Radix liefert nur die pseudonyme employee_id. In den Ticket-Notizen steht aber oft
das Techniker-Kürzel im Call-Log-Format „<KÜRZEL> <TT.MM.JJJJ> <HH:MM:SS>:". Dieses
Skript korreliert je employee_id (aus der Arbeitszeile des Einsatzes) das häufigste
solche Kürzel und schreibt einen ENTWURF, den du prüfst und korrigierst.

    python scripts/seed_technicians.py            # schreibt config/technicians.draft.yaml
    python scripts/seed_technicians.py --print    # nur ausgeben

Danach: Entwurf prüfen → nach config/technicians.yaml kopieren →
    docker exec krai-insights-app python -m insights.etl.load --technicians
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

logger = get_logger("seed_technicians")

# employee_id -> häufigstes Call-Log-Kürzel + Trefferzahl + Anteil (Konfidenz).
_SQL = r"""
WITH labor AS (
    SELECT DISTINCT radix_activity_id, employee_id
    FROM insights.cost_events WHERE cost_type = 'labor' AND employee_id IS NOT NULL
),
hits AS (
    SELECT l.employee_id,
           (regexp_matches(
               COALESCE(an.technik_text, '') || ' ' || COALESCE(an.verlauf_text, ''),
               '\y([A-ZÄÖÜ]{2,4})\y\s+\d{2}\.\d{2}\.\d{4}', 'g'))[1] AS kuerzel
    FROM labor l
    JOIN insights.activity_notes an USING (radix_activity_id)
),
cnt AS (
    SELECT employee_id, kuerzel, count(*) AS n FROM hits GROUP BY employee_id, kuerzel
),
ranked AS (
    SELECT employee_id, kuerzel, n,
           sum(n) OVER (PARTITION BY employee_id) AS gesamt,
           row_number() OVER (PARTITION BY employee_id ORDER BY n DESC) AS rk
    FROM cnt
)
SELECT employee_id, kuerzel, n, gesamt, round(100.0 * n / gesamt, 0) AS konfidenz_pct
FROM ranked WHERE rk = 1 AND n >= 3 ORDER BY gesamt DESC
"""


def build_draft() -> str:
    lines = [
        "# ENTWURF — automatisch aus dem Ticket-Call-Log geraten. BITTE PRÜFEN.",
        "# Konfidenz = Anteil dieses Kürzels an allen Kürzeln des Technikers.",
        "technicians:",
    ]
    with insights_engine().connect() as conn:
        rows = list(conn.execute(text(_SQL)))
    for r in rows:
        lines.append(f'  "{r.employee_id}": {{ kuerzel: "{r.kuerzel}" }}'
                     f"  # {r.n}/{r.gesamt} Treffer, Konfidenz {int(r.konfidenz_pct)}%")
    if not rows:
        lines.append("  # (keine Kürzel im Call-Log gefunden)")
    logger.info("seed_technicians: %d Kandidaten geraten", len(rows))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Techniker-Kürzel-Entwurf aus Call-Log")
    parser.add_argument("--print", action="store_true", dest="to_stdout", help="nur ausgeben statt schreiben")
    args = parser.parse_args()
    draft = build_draft()
    if args.to_stdout:
        print(draft)
    else:
        out = _REPO_ROOT / "config" / "technicians.draft.yaml"
        out.write_text(draft, encoding="utf-8")
        logger.info("Entwurf geschrieben: %s — prüfen und nach config/technicians.yaml kopieren", out)
