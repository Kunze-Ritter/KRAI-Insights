"""Fix migration 072 views: Stoerung -> Störung (umlaut encoding fix)."""
from __future__ import annotations

from insights.core.db import insights_engine
from sqlalchemy import text

VIEWS_SQL = """
DROP VIEW IF EXISTS insights.vw_sla_compliance CASCADE;
DROP VIEW IF EXISTS insights.vw_ticket_volume_monthly CASCADE;
DROP VIEW IF EXISTS insights.vw_sla_tickets CASCADE;

CREATE VIEW insights.vw_sla_tickets AS
WITH close_time AS (
    SELECT
        radix_ticket_id,
        COALESCE(
            MAX(activity_datetime),
            MAX(activity_date)::TIMESTAMPTZ + INTERVAL '17 hours'
        ) AS closed_ts
    FROM insights.activity_notes
    GROUP BY radix_ticket_id
),
classified AS (
    SELECT
        t.*,
        CASE
            WHEN t.maintenance_type ILIKE '%040/010%'  THEN 'A'
            WHEN t.priority_type    = 'High'           THEN 'A'
            WHEN t.maintenance_type ILIKE '%/040/%'    THEN 'B'
            WHEN t.maintenance_type ILIKE '%/020/%'    THEN 'B'
            WHEN t.maintenance_type ILIKE '%/030/%'    THEN 'B'
            WHEN t.maintenance_type ILIKE '%/070/%'    THEN 'B'
            ELSE 'C'
        END AS priority_code,
        CASE
            WHEN t.maintenance_type ILIKE '%/040/%'
              OR t.maintenance_type ILIKE '%/020/%'
              OR t.maintenance_type ILIKE '%/030/%'
              OR t.maintenance_type ILIKE '%/070/%' THEN 'Störung'
            WHEN t.maintenance_type ILIKE '%/010/%'   THEN 'Wartung'
            WHEN t.maintenance_type ILIKE '%/080/%'   THEN 'Installation'
            WHEN t.maintenance_type ILIKE '%/090/%'   THEN 'Support'
            ELSE 'Sonstiges'
        END AS ticket_category,
        ct.closed_ts
    FROM insights.radix_tickets t
    LEFT JOIN close_time ct ON ct.radix_ticket_id = t.ticket_id
)
SELECT
    *,
    CASE
        WHEN state_code = 'ERL'
         AND closed_ts IS NOT NULL
         AND created_at IS NOT NULL
         AND closed_ts >= created_at
        THEN ROUND(EXTRACT(EPOCH FROM (closed_ts - created_at)) / 3600.0, 1)::NUMERIC
    END AS recovery_hours,
    CASE
        WHEN state_code = 'ERL'
         AND closed_ts IS NOT NULL
         AND created_at IS NOT NULL
         AND closed_ts >= created_at
        THEN (closed_ts::DATE - created_at::DATE)
    END AS recovery_days,
    CASE
        WHEN state_code != 'ERL'
          OR closed_ts IS NULL
          OR created_at IS NULL
          OR closed_ts < created_at THEN NULL
        WHEN priority_code = 'A'
            AND (closed_ts - created_at) <= INTERVAL '8 hours'  THEN true
        WHEN priority_code = 'B'
            AND (closed_ts::DATE - created_at::DATE) <= 1       THEN true
        WHEN priority_code IN ('A', 'B')                        THEN false
        ELSE NULL
    END AS sla_met
FROM classified;

CREATE VIEW insights.vw_ticket_volume_monthly AS
SELECT
    DATE_TRUNC('month', created_at)::DATE AS monat,
    priority_code,
    ticket_category,
    COUNT(*) AS anzahl
FROM insights.vw_sla_tickets
WHERE created_at >= NOW() - INTERVAL '3 years'
GROUP BY 1, 2, 3;

CREATE VIEW insights.vw_sla_compliance AS
SELECT
    DATE_TRUNC('month', created_at)::DATE    AS monat,
    priority_code,
    COUNT(*)                                  AS gesamt,
    COUNT(*) FILTER (WHERE sla_met = true)   AS eingehalten,
    COUNT(*) FILTER (WHERE sla_met = false)  AS ueberschritten,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE sla_met = true)
              / NULLIF(COUNT(*) FILTER (WHERE sla_met IS NOT NULL), 0),
        1
    ) AS quote_prozent,
    ROUND(AVG(recovery_hours), 1) AS avg_recovery_stunden,
    ROUND(AVG(recovery_days),  1) AS avg_recovery_tage
FROM insights.vw_sla_tickets
WHERE state_code = 'ERL'
  AND priority_code IN ('A', 'B')
  AND created_at >= NOW() - INTERVAL '3 years'
GROUP BY 1, 2;
"""

if __name__ == "__main__":
    with insights_engine().begin() as conn:
        for stmt in VIEWS_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
    print("SLA views fixed (Störung umlaut restored).")

    with insights_engine().connect() as conn:
        cats = conn.execute(
            text("SELECT DISTINCT ticket_category FROM insights.vw_sla_tickets ORDER BY 1")
        ).fetchall()
        print("ticket_category values:", [r[0] for r in cats])

        comp = conn.execute(
            text(
                "SELECT priority_code, SUM(gesamt) g, SUM(eingehalten) e "
                "FROM insights.vw_sla_compliance GROUP BY 1 ORDER BY 1"
            )
        ).fetchall()
        print("SLA compliance totals:", comp)
