-- 069_technician_is_executor.sql
-- KORREKTUR zu 067: Der Techniker ist der AUSFÜHRENDE (`employee` der Aktivität, identisch
-- mit der Arbeitszeit-Zeile), NICHT der Verantwortliche/Dispo (`employeeResponsible`).
--
-- Befund (Nutzer + API-Beleg): `employeeResponsible` ist Office/Dispo — z. B. Oliver Kraska
-- hält/disponiert sehr viele Tickets, war aber nie vor Ort. Der echte Techniker steht in
-- `employee` (Header) bzw. auf der Worktime-Zeile (beide identisch: Valeri Rhein, Achim
-- Bühler, Stefan Lebtig, Peter Matt …). 067 hatte die Felder vertauscht.
--
-- Fix: activity_notes.techniker_* hält ab jetzt den Ausführenden (Loader umgestellt);
-- der Verantwortliche/Dispo wandert in dispo_id/dispo_name. View reicht `dispo` zusätzlich
-- durch. Namen liegen bereits in radix_employees (068 erntet beide Felder).

ALTER TABLE insights.activity_notes
    ADD COLUMN IF NOT EXISTS dispo_id   text,
    ADD COLUMN IF NOT EXISTS dispo_name text;

-- Spalten + Reihenfolge wie 068, NEU nur `dispo` am Ende angehängt -> CREATE OR REPLACE ok.
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
       -- Techniker = Ausführender (Header `employee` == Worktime-Zeile). Fallback: Worktime-Logger.
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
       'insights'::text AS source_system,
       an.dispo_name AS dispo
FROM mat m
LEFT JOIN labor lb ON lb.radix_activity_id = m.radix_activity_id
LEFT JOIN insights.activity_notes an ON an.radix_activity_id = m.radix_activity_id
LEFT JOIN insights.radix_employees re ON re.employee_id = COALESCE(an.techniker_id, lb.employee_id)
LEFT JOIN insights.technician_aliases ta ON ta.employee_id = COALESCE(an.techniker_id, lb.employee_id)
LEFT JOIN dev ON dev.manufacturer_serial = m.device_serial;
