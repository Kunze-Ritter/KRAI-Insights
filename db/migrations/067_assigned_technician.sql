-- 067_assigned_technician.sql
-- Den ZUGEWIESENEN Techniker direkt aus Radix nutzen (statt Mining / Arbeitszeit-Logger).
--
-- Radix liefert je Aktivität `employeeIdResponsible` + `employeeResponsible` (= der
-- verantwortliche Techniker, mit Klarnamen) und `team`. Diese Namen sind eigene
-- Mitarbeiter — laut Policy erlaubt (nur Kunden-Kontakte werden pseudonymisiert). Bisher
-- wurde der Name verworfen und das Service-Dashboard nutzte den Arbeitszeit-Logger
-- (`cost_events.employee_id`), der oft das LAGER ist (Teile-Buchung), nicht der Techniker.
-- → activity_notes um techniker_id/name/team erweitern; die Service-Views stellen auf den
--   zugewiesenen Techniker um (config/technicians.yaml nur noch optionaler Override).

ALTER TABLE insights.activity_notes
    ADD COLUMN IF NOT EXISTS techniker_id   text,
    ADD COLUMN IF NOT EXISTS techniker_name text,
    ADD COLUMN IF NOT EXISTS team_name      text;

-- Views in Abhängigkeitsreihenfolge neu aufbauen (Spalten ändern sich -> DROP+CREATE).
DROP VIEW IF EXISTS insights.vw_technician_service_profile;
DROP VIEW IF EXISTS insights.vw_symptom_teiltyp;
DROP VIEW IF EXISTS insights.vw_symptom_part_patterns;
DROP VIEW IF EXISTS insights.vw_service_visits;

CREATE VIEW insights.vw_service_visits AS
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
       -- zugewiesener Techniker (Radix) hat Vorrang; Fallback Arbeitszeit-Logger
       COALESCE(an.techniker_id, lb.employee_id) AS techniker_id,
       COALESCE(NULLIF(an.techniker_name, ''), NULLIF(ta.kuerzel, ''), NULLIF(ta.name, ''),
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
LEFT JOIN insights.technician_aliases ta ON ta.employee_id = COALESCE(an.techniker_id, lb.employee_id)
LEFT JOIN dev ON dev.manufacturer_serial = m.device_serial;

CREATE VIEW insights.vw_symptom_part_patterns AS
SELECT symptom,
       count(*) AS einsaetze,
       round(avg(teiltypen), 2) AS schnitt_teiltypen,
       round(avg(teile_positionen), 2) AS schnitt_positionen,
       count(*) FILTER (WHERE shotgun_verdacht) AS shotgun_einsaetze,
       round(100.0 * count(*) FILTER (WHERE shotgun_verdacht) / NULLIF(count(*), 0), 1) AS shotgun_pct,
       round(sum(material_eur)) AS material_eur,
       mode() WITHIN GROUP (ORDER BY teiltyp_liste) AS haeufigste_teilkombi,
       'insights'::text AS source_system
FROM insights.vw_service_visits
GROUP BY symptom ORDER BY einsaetze DESC;

CREATE VIEW insights.vw_symptom_teiltyp AS
SELECT v.symptom, insights.part_type(ce.description) AS teiltyp,
       count(*) AS positionen,
       count(DISTINCT v.radix_activity_id) AS einsaetze,
       round(sum(COALESCE(ce.total_eur, ce.unit_price * ce.quantity, 0))) AS material_eur,
       'insights'::text AS source_system
FROM insights.vw_service_visits v
JOIN insights.cost_events ce ON ce.radix_activity_id = v.radix_activity_id AND ce.cost_type = 'material'
GROUP BY v.symptom, insights.part_type(ce.description)
ORDER BY v.symptom, positionen DESC;

-- Techniker-Profil jetzt je ZUGEWIESENEM Techniker (Name) + Team.
CREATE VIEW insights.vw_technician_service_profile AS
SELECT techniker, techniker_id, max(team) AS team,
       count(*) AS einsaetze,
       round(avg(teiltypen), 2) AS schnitt_teiltypen,
       count(*) FILTER (WHERE shotgun_verdacht) AS shotgun_einsaetze,
       round(100.0 * count(*) FILTER (WHERE shotgun_verdacht) / NULLIF(count(*), 0), 1) AS shotgun_pct,
       count(*) FILTER (WHERE symptom = 'Wartung/Installation') AS wartungen,
       round(sum(material_eur)) AS material_eur,
       'insights'::text AS source_system
FROM insights.vw_service_visits
WHERE techniker_id IS NOT NULL
GROUP BY techniker, techniker_id
HAVING count(*) >= 10
ORDER BY shotgun_pct DESC NULLS LAST;
