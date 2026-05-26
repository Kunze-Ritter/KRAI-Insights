-- 055_waste_box_forecast.sql
-- Proaktive Resttonerbehälter-Vorhersage über den SEITENZÄHLER statt den Füllstand-
-- Sensor. Hintergrund (user, 2026-05-26): Kopierer messen den Waste-Behälter schlecht
-- → 52 % aller Waste-Box-"Events" sind Rauschen (< 5.000 Seiten, kein echter Tausch),
-- bei Lexmark XC/CX, HP E87xx, Kyocera-Color 80–100 %. Folge: KR sieht den vollen
-- Behälter erst, wenn er voll ist → liefert zu spät.
--
-- Idee: Der Seitenzähler ist zuverlässig (anders als der Waste-Sensor). Wir schätzen
-- die Füllung über "Seiten seit letztem ECHTEN Box-Wechsel" vs. einer Modell-Referenz
-- (Seiten je Box). Referenz Y, in absteigender Verlässlichkeit:
--   1) Modell-realisiert: Median der ECHTEN Wechsel (pages_since_previous >= 5.000) je
--      Modell, >= 5 Stichproben (verlässlich v. a. für KM bizhub).
--   2) OEM-Soll Waste je Hersteller (part_lifetime_oem, aktuell nur Lexmark).
--   3) Flotten-Median der echten Wechsel (Notnagel).
--
-- mess_qualitaet:
--   'verlässlich'  – Gerät hat einen echten letzten Wechsel → echte Prognose (pct/Tage).
--   'unsicher'     – kein verlässlicher Wechsel (Sensor-Rauschen) → nur Referenz Y als
--                    Richtwert für FIXE Liefer-Kadenz; keine Punkt-Prognose.
--
-- Nur Live-Geräte, die überhaupt Waste-Boxen nutzen (Waste-Event vorhanden).

CREATE OR REPLACE VIEW insights.vw_waste_box_forecast AS
WITH wb AS (   -- alle Waste-Box-Lifecycle-Events
    SELECT v.fleetmgmt_device_id AS dev, v.occurred_at, v.page_count_at_event, v.pages_since_previous
    FROM insights.vw_vbm_lifecycle v
    WHERE v.marker_name ILIKE '%waste%' OR v.marker_name ILIKE '%resttoner%'
       OR v.marker_name ILIKE '%auffang%'
),
clean AS (     -- nur plausible ECHTE Wechsel
    SELECT * FROM wb WHERE pages_since_previous >= 5000
),
model_ref AS ( -- realisierter Median je Modell (>= 5 echte Stichproben)
    SELECT d.model_display,
           round(percentile_cont(0.5) WITHIN GROUP (ORDER BY c.pages_since_previous)) AS med
    FROM clean c JOIN insights.devices_unified d ON d.fleetmgmt_device_id = c.dev
    GROUP BY 1 HAVING count(*) >= 5
),
oem_ref AS (   -- OEM-Soll Waste je Hersteller
    SELECT manufacturer,
           round(percentile_cont(0.5) WITHIN GROUP (ORDER BY nominal_lifetime_pages)) AS med
    FROM insights.part_lifetime_oem WHERE part_category = 'waste' GROUP BY 1
),
fleet_ref AS ( SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pages_since_previous)) AS med FROM clean ),
last_swap AS ( -- letzter ECHTER Wechsel je Gerät
    SELECT DISTINCT ON (dev) dev, occurred_at::date AS letzter_wechsel, page_count_at_event AS seiten_beim_wechsel
    FROM clean ORDER BY dev, occurred_at DESC
),
counter AS (   -- aktueller Zählerstand + Tagesrate der letzten ~120 Tage
    SELECT fleetmgmt_device_id AS dev,
           max(page_count) AS akt_seiten,
           round((max(page_count) FILTER (WHERE day >= CURRENT_DATE - 120)
                  - min(page_count) FILTER (WHERE day >= CURRENT_DATE - 120))::numeric
                 / NULLIF(max(day) FILTER (WHERE day >= CURRENT_DATE - 120)
                          - min(day) FILTER (WHERE day >= CURRENT_DATE - 120), 0), 1) AS seiten_pro_tag
    FROM insights.device_counter_daily GROUP BY 1
),
calc AS (
    SELECT
        d.customer_name, d.customer_city, d.manufacturer_canonical, d.model_display,
        d.manufacturer_serial AS device_serial, d.radix_device_number,
        ls.letzter_wechsel, ct.akt_seiten, ct.seiten_pro_tag,
        CASE WHEN ls.seiten_beim_wechsel IS NOT NULL
             THEN ct.akt_seiten - ls.seiten_beim_wechsel END AS seiten_seit_wechsel,
        COALESCE(mr.med, om.med, fr.med)::int AS referenz_seiten,
        CASE WHEN mr.med IS NOT NULL THEN 'Modell-realisiert'
             WHEN om.med IS NOT NULL THEN 'OEM-Soll'
             ELSE 'Flotten-Median' END AS referenz_basis,
        (ls.dev IS NOT NULL) AS hat_echten_wechsel
    FROM (SELECT DISTINCT dev FROM wb) dl
    JOIN insights.devices_unified d ON d.fleetmgmt_device_id = dl.dev
    LEFT JOIN model_ref mr ON mr.model_display = d.model_display
    LEFT JOIN oem_ref   om ON d.manufacturer_canonical ILIKE om.manufacturer || '%'
    CROSS JOIN fleet_ref fr
    LEFT JOIN last_swap ls ON ls.dev = dl.dev
    LEFT JOIN counter   ct ON ct.dev = dl.dev
    WHERE d.device_status = 'live'
)
SELECT
    customer_name, customer_city, manufacturer_canonical, model_display,
    device_serial, radix_device_number,
    letzter_wechsel, akt_seiten, seiten_pro_tag, seiten_seit_wechsel,
    referenz_seiten, referenz_basis,
    CASE WHEN seiten_seit_wechsel IS NOT NULL AND referenz_seiten > 0
         THEN round(100.0 * seiten_seit_wechsel / referenz_seiten) END AS pct_voll,
    -- Tage bis voll nur, wenn wir verlässlich innerhalb der aktuellen Box sind
    CASE WHEN hat_echten_wechsel AND seiten_seit_wechsel IS NOT NULL
              AND seiten_seit_wechsel <= 1.2 * referenz_seiten AND seiten_pro_tag > 0
         THEN round((referenz_seiten - seiten_seit_wechsel) / seiten_pro_tag) END AS tage_bis_voll,
    -- Messqualität: nur innerhalb der aktuellen Box ist die Punkt-Prognose verlässlich;
    -- liegt seiten_seit_wechsel deutlich über der Referenz, wurden Wechsel nicht erfasst
    -- (Sensor-Rauschen dazwischen) → unsicher, nur Referenz Y als fixe Kadenz nutzen.
    CASE
        WHEN NOT hat_echten_wechsel THEN 'unsicher (Sensor-Rauschen)'
        WHEN seiten_seit_wechsel > 1.2 * referenz_seiten THEN 'unsicher (Wechsel nicht erfasst)'
        ELSE 'verlässlich'
    END AS mess_qualitaet,
    CASE
        WHEN NOT hat_echten_wechsel OR seiten_seit_wechsel IS NULL
             OR referenz_seiten <= 0 OR seiten_seit_wechsel > 1.2 * referenz_seiten
            THEN 'sensor_unzuverlaessig'
        WHEN seiten_seit_wechsel >= 0.8 * referenz_seiten THEN 'faellig'
        WHEN seiten_seit_wechsel >= 0.6 * referenz_seiten THEN 'bald'
        ELSE 'ok'
    END AS dringlichkeit
FROM calc;
