-- Migration 072: SLA-Dashboard — Ticket-Tabelle + Auswertungs-Views
-- Daten: Radix /api/ticket (documentDate = Erstellzeit, maintenanceType = Kategorie)
-- Priorität wird aus maintenanceType abgeleitet (Blockierend=A, Störungen=B, Rest=C).
-- Abschlusszeit = letztes Activity-Datum aus activity_notes (Tagesgenauigkeit).
-- SLA A: gleicher Tag = näherungsweise eingehalten; SLA B: <= 1 Tag (NBD).
-- Um Stundenpräzision zu ermöglichen, wird activity_notes.activity_datetime ergänzt.

-- 1. Uhrzeit-Spalte an activity_notes (für neue Crawls; Altdaten bleiben NULL)
ALTER TABLE insights.activity_notes
    ADD COLUMN IF NOT EXISTS activity_datetime TIMESTAMPTZ;

-- 2. Ticket-Haupttabelle
CREATE TABLE IF NOT EXISTS insights.radix_tickets (
    ticket_id        TEXT PRIMARY KEY,
    ticket_code      TEXT,
    maintenance_type TEXT,           -- roh, z.B. "010/040/010 - Blockierend"
    priority_type    TEXT,           -- "Normal" / "High" aus Radix
    created_at       TIMESTAMPTZ,   -- documentDate (Erstellzeit)
    customer_id      TEXT,
    customer_name    TEXT,
    state            TEXT,           -- "Done" etc.
    state_code       TEXT,           -- "ERL" etc.
    device_id        UUID REFERENCES insights.devices_unified(id) ON DELETE SET NULL,
    description      TEXT,           -- pseudonymisierter Ticket-Betreff
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_radix_tickets_created
    ON insights.radix_tickets (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_radix_tickets_customer
    ON insights.radix_tickets (customer_id);
CREATE INDEX IF NOT EXISTS ix_radix_tickets_state
    ON insights.radix_tickets (state_code);

-- 3. Basis-View: klassifiziert Priorität + Kategorie, ergänzt Abschluss + SLA-Bewertung
CREATE OR REPLACE VIEW insights.vw_sla_tickets AS
WITH close_time AS (
    -- Abschlusszeit: volle Uhrzeit wenn vorhanden, sonst letztes activity_date (Tagesende)
    SELECT
        radix_ticket_id,
        COALESCE(
            MAX(activity_datetime),
            MAX(activity_date)::TIMESTAMPTZ + INTERVAL '17 hours'  -- konservativer Tages-Fallback
        ) AS closed_ts
    FROM insights.activity_notes
    GROUP BY radix_ticket_id
),
classified AS (
    SELECT
        t.*,
        -- Prioritäts-Code: A = Blockierend oder High, B = Störung sonstig, C = Rest
        CASE
            WHEN t.maintenance_type ILIKE '%040/010%'  THEN 'A'
            WHEN t.priority_type    = 'High'           THEN 'A'
            WHEN t.maintenance_type ILIKE '%/040/%'    THEN 'B'
            WHEN t.maintenance_type ILIKE '%/020/%'    THEN 'B'
            WHEN t.maintenance_type ILIKE '%/030/%'    THEN 'B'
            WHEN t.maintenance_type ILIKE '%/070/%'    THEN 'B'
            ELSE 'C'
        END AS priority_code,
        -- Ticket-Kategorie für den "Ticketarten"-Chart
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
    -- Wiederherstellungszeit in Stunden (Näherung; NULL bei negativen Werten = Datenfehler)
    CASE
        WHEN state_code = 'ERL'
         AND closed_ts IS NOT NULL
         AND created_at IS NOT NULL
         AND closed_ts >= created_at
        THEN ROUND(EXTRACT(EPOCH FROM (closed_ts - created_at)) / 3600.0, 1)::NUMERIC
    END AS recovery_hours,
    -- Wiederherstellungszeit in Tagen
    CASE
        WHEN state_code = 'ERL'
         AND closed_ts IS NOT NULL
         AND created_at IS NOT NULL
         AND closed_ts >= created_at
        THEN (closed_ts::DATE - created_at::DATE)
    END AS recovery_days,
    -- SLA eingehalten? (nur A+B; NULL = kein SLA-Ziel oder Datenfehler)
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

-- 4. Monatliche Volumen-Übersicht (Dringlichkeit + Ticketarten)
CREATE OR REPLACE VIEW insights.vw_ticket_volume_monthly AS
SELECT
    DATE_TRUNC('month', created_at)::DATE AS monat,
    priority_code,
    ticket_category,
    COUNT(*) AS anzahl
FROM insights.vw_sla_tickets
WHERE created_at >= NOW() - INTERVAL '3 years'
GROUP BY 1, 2, 3;

-- 5. SLA-Compliance je Monat und Priorität (nur erledigt + A/B)
CREATE OR REPLACE VIEW insights.vw_sla_compliance AS
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
