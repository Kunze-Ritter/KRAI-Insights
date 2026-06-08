-- 068_radix_employees.sql
-- Globale Mitarbeiter-Namensliste (employee_id -> Name) aus Radix, damit AUCH der
-- Fallback (Ticket ohne zugewiesenen Techniker -> Arbeitszeit-Logger) einen Namen bekommt.
--
-- Problem nach 067: 9 Techniker zeigten noch die ID. Ursache: 3.392 Aktivitäten haben
-- KEINEN verantwortlichen Techniker -> die View fällt auf den Arbeitszeit-Logger zurück,
-- dessen ID aber nicht zum Namen aufgelöst wurde — obwohl dieselbe Person (z. B. Achim
-- Bühler) auf anderen Tickets sehr wohl als Verantwortlicher mit Namen auftaucht.
--
-- Lösung: radix_employees (employee_id -> name), befüllt aus BEIDEN Feldern jeder Aktivität
-- (employee = Arbeitszeit-Logger, employeeResponsible = Verantwortlicher) im Ticket-Crawl.
-- vw_service_visits löst den (effektiven) techniker_id über diese Liste auf.

CREATE TABLE IF NOT EXISTS insights.radix_employees (
    employee_id text PRIMARY KEY,
    name        text,
    ingested_at timestamptz NOT NULL DEFAULT now()
);

-- Soforthilfe: die bereits bekannten Verantwortlichen-Namen aus activity_notes übernehmen
-- (deckt 6 der 9 ab; der Rest kommt mit dem nächsten Ticket-Crawl, der auch Logger-Namen liefert).
INSERT INTO insights.radix_employees (employee_id, name)
SELECT DISTINCT techniker_id, techniker_name
FROM insights.activity_notes
WHERE techniker_id IS NOT NULL AND techniker_name IS NOT NULL
ON CONFLICT (employee_id) DO UPDATE SET name = EXCLUDED.name, ingested_at = now();

-- vw_service_visits: techniker über die Namensliste auflösen. Spalten + Reihenfolge
-- unverändert ggü. 067 -> CREATE OR REPLACE (keine Dependents droppen). Einzige Änderung:
-- LEFT JOIN radix_employees + erweiterte COALESCE-Kette beim Namen.
CREATE OR REPLACE VIEW insights.vw_service_visits AS
WITH dev AS (
    SELECT DISTINCT ON (manufacturer_serial) manufacturer_serial,
           manufacturer_canonical, model_display, customer_name, customer_city
    FROM insights.devices_unified
    WHERE manufacturer_serial IS NOT NULL AND manufacturer_serial <> ''
    ORDER BY manufacturer_serial, (device_status = 'live') DESC
),
mat AS (
    SELECT radix_activity_id, max(radix_ticket_id) AS radix_ticket_id, max(radix_customer_id) AS radix_customer_id,
           min(occurred_at) AS occurred_at, max(device_serial) AS device_serial,
           count(*) AS teile_positionen,
           sum(COALESCE(quantity, 1)) AS teile_stueck,
           count(DISTINCT insights.part_type(description)) AS teiltypen,
           round(sum(COALESCE(total_eur, unit_price * quantity, 0))) AS material_eur,
           string_agg(DISTINCT insights.part_type(description), ', ' ORDER BY insights.part_type(description)) AS teiltyp_liste
    FROM insights.cost_events
    WHERE cost_type = 'material' AND radix_activity_id IS NOT NULL
    GROUP BY radix_activity_id
),
labor AS (
    SELECT radix_activity_id, mode() WITHIN GROUP (ORDER BY employee_id) AS employee_id,
           sum(duration_minutes) AS arbeit_min
    FROM insights.cost_events
    WHERE cost_type = 'labor' AND employee_id IS NOT NULL
    GROUP BY radix_activity_id
)
SELECT m.radix_activity_id, m.radix_ticket_id, m.occurred_at::date AS datum,
       m.device_serial, dev.manufacturer_canonical, dev.model_display,
       dev.customer_name, dev.customer_city,
       COALESCE(an.techniker_id, lb.employee_id) AS techniker_id,
       COALESCE(NULLIF(ta.kuerzel, ''), NULLIF(ta.name, ''),
                NULLIF(an.techniker_name, ''), NULLIF(re.name, ''),
                an.techniker_id, lb.employee_id) AS techniker,
       an.team_name AS team,
       lb.employee_id AS arbeitszeit_logger_id,
       lb.arbeit_min,
       m.teile_positionen, m.teile_stueck, m.teiltypen, m.teiltyp_liste, m.material_eur,
       insights.service_symptom(COALESCE(an.problem_text, '') || ' ' || COALESCE(an.technik_text, '')) AS symptom,
       an.problem_text, an.technik_text,
       (m.teiltypen >= 3
        AND insights.service_symptom(COALESCE(an.problem_text, '') || ' ' || COALESCE(an.technik_text, '')) <> 'Wartung/Installation'
       ) AS shotgun_verdacht,
       'insights'::text AS source_system
FROM mat m
LEFT JOIN labor lb ON lb.radix_activity_id = m.radix_activity_id
LEFT JOIN insights.activity_notes an ON an.radix_activity_id = m.radix_activity_id
LEFT JOIN insights.radix_employees re ON re.employee_id = COALESCE(an.techniker_id, lb.employee_id)
LEFT JOIN insights.technician_aliases ta ON ta.employee_id = COALESCE(an.techniker_id, lb.employee_id)
LEFT JOIN dev ON dev.manufacturer_serial = m.device_serial;
