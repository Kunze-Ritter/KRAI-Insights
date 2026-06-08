-- 066_service_shotgun.sql
-- Service-Dashboard: „Shotgun-Reparatur" aufdecken — Techniker, die auf Verdacht viele
-- Teile (Trommel/Entwickler/Transfer/Fixierer …) auf einmal tauschen, statt gezielt.
--
-- Ziel (Nutzer): Muster finden, um Techniker zu schulen — wo wird zu früh getauscht,
-- wie viele Teile pro Einsatz, und gibt es ein Muster zwischen Fehlermeldung/Symptom
-- und den getauschten Teilen ("bei Streifen immer 3 Teile statt 1").
--
-- Datenbasis (alles vorhanden, 2026-06-08 geprüft):
--   * cost_events trägt radix_activity_id + radix_ticket_id → Teile je Einsatz gruppierbar.
--   * 97,9 % der Material-Einsätze haben eine Arbeitszeile mit employee_id → Techniker
--     (pseudonym) zuordenbar; Klartext-Kürzel optional über technician_aliases (Config).
--   * 100 % der Material-Einsätze haben Ticket-Freitext (Problem/Technik) → Symptom.
--
-- WICHTIGE NUANCE: Viele Tickets sind GEPLANTE Wartung/Installation ("Wartung durchführen",
-- "SD-Teile installieren", "Treiber installieren") — dort ist ein Teile-Kit KORREKT, kein
-- Shotgun. Der Symptom-Klassifikator trennt das ab; Shotgun-Verdacht zählt NUR Störungs-/
-- Reparatur-Einsätze. (Siehe docs/service.md.)

-- 1) Techniker-Aliase (Config-gepflegt: employee_id -> Kürzel/Name). Leer = Fallback auf id.
CREATE TABLE IF NOT EXISTS insights.technician_aliases (
    employee_id text PRIMARY KEY,
    kuerzel     text,
    name        text,
    source      text        NOT NULL DEFAULT 'config',
    ingested_at timestamptz NOT NULL DEFAULT now()
);

-- 2) Symptom-Klassifikator aus dem Ticket-Freitext (Problem + Technik zusammen).
--    Reihenfolge: erst die konkreten Stör-Symptome, dann generische Fehler-Sprache, dann
--    Wartung/Installation NUR wenn keinerlei Stör-Symptom vorkam (sonst würde ein echter
--    Fehler als "Wartung" versteckt). Heuristik über deutsche Service-Notizen.
CREATE OR REPLACE FUNCTION insights.service_symptom(t text) RETURNS text AS $$
  SELECT CASE
    WHEN t IS NULL OR btrim(t) = '' THEN 'Unbekannt'
    WHEN lower(t) ~ '(papierstau|papier.{0,10}stau|\ystau\y|einzug.{0,8}stau)' THEN 'Papierstau'
    WHEN lower(t) ~ '(streifen|schlier|strich|\ylinie|fleck|schatten|geist|bildqual|verschmutz|grau druck|punkte)' THEN 'Bildqualität'
    WHEN lower(t) ~ '(scann?er|\yscan\y|einzug|\yadf\y|dokumentenzuf|vorlage|duplex)' THEN 'Scanner/Einzug'
    WHEN lower(t) ~ '(geräusch|quietsch|klapper|lärm|schleif|knirsch)' THEN 'Geräusch'
    WHEN lower(t) ~ '(toner.{0,10}(leer|nachfüll|wechsel)|\ytoner\y|verbrauchsmat)' THEN 'Toner/Verbrauch'
    WHEN lower(t) ~ '(fehler|error|störung|fehlercode|\ycode\y|defekt|geht nicht|hängt|aufgehäng|kein druck|druckt nicht|reagiert nicht)' THEN 'Fehler/Störung'
    WHEN lower(t) ~ '(wartung|reinig|installier|treiber|einricht|umzug|aufbau|inbetriebnahme|\ysd[- ]?teile|e[- ]?teile.{0,10}(einbau|installier))' THEN 'Wartung/Installation'
    ELSE 'Sonstiges'
  END
$$ LANGUAGE sql IMMUTABLE;

-- 3) Service-Einsätze: ein Einsatz = radix_activity_id. Material-Teile aggregiert,
--    Techniker = employee_id der Arbeitszeile(n), Symptom aus dem Ticket-Text.
CREATE OR REPLACE VIEW insights.vw_service_visits AS
WITH dev AS (  -- ein Datensatz je Seriennummer (Serial ist nicht eindeutig -> Multiplikation vermeiden)
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
tech AS (
    SELECT radix_activity_id, mode() WITHIN GROUP (ORDER BY employee_id) AS employee_id,
           sum(duration_minutes) AS arbeit_min
    FROM insights.cost_events
    WHERE cost_type = 'labor' AND employee_id IS NOT NULL
    GROUP BY radix_activity_id
)
SELECT m.radix_activity_id, m.radix_ticket_id, m.occurred_at::date AS datum,
       m.device_serial, dev.manufacturer_canonical, dev.model_display,
       dev.customer_name, dev.customer_city,
       t.employee_id,
       COALESCE(NULLIF(ta.kuerzel, ''), NULLIF(ta.name, ''), t.employee_id) AS techniker,
       t.arbeit_min,
       m.teile_positionen, m.teile_stueck, m.teiltypen, m.teiltyp_liste, m.material_eur,
       insights.service_symptom(COALESCE(an.problem_text, '') || ' ' || COALESCE(an.technik_text, '')) AS symptom,
       an.problem_text, an.technik_text,
       (m.teiltypen >= 3
        AND insights.service_symptom(COALESCE(an.problem_text, '') || ' ' || COALESCE(an.technik_text, '')) <> 'Wartung/Installation'
       ) AS shotgun_verdacht,
       'insights'::text AS source_system
FROM mat m
LEFT JOIN tech t ON t.radix_activity_id = m.radix_activity_id
LEFT JOIN insights.technician_aliases ta ON ta.employee_id = t.employee_id
LEFT JOIN insights.activity_notes an ON an.radix_activity_id = m.radix_activity_id
LEFT JOIN dev ON dev.manufacturer_serial = m.device_serial;

-- 4) START-Fokus: Symptom -> Teil-Muster. Bei welchem Symptom werden wie viele (und welche)
--    Teiltypen getauscht; Shotgun-Quote je Symptom.
CREATE OR REPLACE VIEW insights.vw_symptom_part_patterns AS
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

-- 4b) Detail: Symptom x Teiltyp (welche Teile bei welchem Symptom, wie oft).
CREATE OR REPLACE VIEW insights.vw_symptom_teiltyp AS
SELECT v.symptom, insights.part_type(ce.description) AS teiltyp,
       count(*) AS positionen,
       count(DISTINCT v.radix_activity_id) AS einsaetze,
       round(sum(COALESCE(ce.total_eur, ce.unit_price * ce.quantity, 0))) AS material_eur,
       'insights'::text AS source_system
FROM insights.vw_service_visits v
JOIN insights.cost_events ce ON ce.radix_activity_id = v.radix_activity_id AND ce.cost_type = 'material'
GROUP BY v.symptom, insights.part_type(ce.description)
ORDER BY v.symptom, positionen DESC;

-- 5) Techniker-Profil: Shotgun-Quote, Ø Teiltypen, Material-€ je Techniker (Schulungs-Liste).
--    Nur Techniker mit >= 10 Einsätzen (Statistik). Wartungen separat ausgewiesen.
CREATE OR REPLACE VIEW insights.vw_technician_service_profile AS
SELECT techniker, employee_id,
       count(*) AS einsaetze,
       round(avg(teiltypen), 2) AS schnitt_teiltypen,
       count(*) FILTER (WHERE shotgun_verdacht) AS shotgun_einsaetze,
       round(100.0 * count(*) FILTER (WHERE shotgun_verdacht) / NULLIF(count(*), 0), 1) AS shotgun_pct,
       count(*) FILTER (WHERE symptom = 'Wartung/Installation') AS wartungen,
       round(sum(material_eur)) AS material_eur,
       'insights'::text AS source_system
FROM insights.vw_service_visits
WHERE employee_id IS NOT NULL
GROUP BY techniker, employee_id
HAVING count(*) >= 10
ORDER BY shotgun_pct DESC NULLS LAST;
