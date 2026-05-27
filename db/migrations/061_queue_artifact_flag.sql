-- 061_queue_artifact_flag.sql
-- Print-Server-/Queue-Artefakte flotten-weit kennzeichnen.
--
-- Befund: Manche Kunden werden NICHT geraeteweise, sondern ueber einen zentralen
-- Windows-Print-Server ueberwacht. Der DCA/CSP-Agent liest dort die Druck-Queues mit;
-- die Queues ohne SNMP-Antwort landen als "Geraete" mit dem QUEUE-NAMEN im IP-Feld
-- (kein Serial, kein Modell, kein Hersteller, kein MAC). Pro Kunde ein eigenes Schema:
--   BruderhausDiakonie  -> "PS30xxx"   (Print Server)
--   IMS_Gear            -> "mfdeNNNN"
--   Stadt_Freiburg      -> "konicasqNNNN" (Konica Secure Queue)
--   diverse Landratsaemter/Rolls-Royce -> "DN-NNNNNN"
-- Flotten-weit: 414 solcher identitaetsloser Eintraege (96 live, 318 still) - sie
-- blaehen die Live- und Lizenz-Zahlen auf, sind aber keine physischen Kopierer.
--
-- Robuster Erkenner (NICHT der String "PS", der ist kundenspezifisch):
--   printer_ip ist gesetzt, aber KEINE gueltige IPv4  (= ein Hostname/Queue-Name)
--   UND es gibt keine Hersteller-Seriennummer        (= keine echte Geraete-Identitaet)
-- Geraete, die nur zufaellig einen Hostnamen im IP-Feld haben, aber ein Serial tragen
-- (63 Stueck), bleiben echte Geraete und werden NICHT geflaggt.

-- 1) Generierte Spalte (STORED): immer korrekt, kein Loader-Eingriff noetig.
--    !~ nutzt textregexne (IMMUTABLE) -> als STORED-Generated-Column zulaessig.
ALTER TABLE insights.devices_unified
    ADD COLUMN IF NOT EXISTS is_queue_artifact boolean
    GENERATED ALWAYS AS (
        printer_ip IS NOT NULL
        AND printer_ip !~ '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'
        AND manufacturer_serial IS NULL
    ) STORED;

-- 2) Headline-Live-Zahl bereinigen: Queue-Artefakte zaehlen nicht als Live-Geraet.
--    Definition wortgetreu aus der aktuellen View uebernommen (CTE-basiert seit 046);
--    GEAENDERT ist nur das geraete_live-Unterquery (Filter NOT is_queue_artifact).
CREATE OR REPLACE VIEW insights.vw_lagebericht AS
WITH gp AS (
    SELECT percentile_cont(0.1::double precision) WITHIN GROUP (ORDER BY (unit_price::double precision)) AS p10,
           percentile_cont(0.5::double precision) WITHIN GROUP (ORDER BY (unit_price::double precision)) AS med,
           percentile_cont(0.9::double precision) WITHIN GROUP (ORDER BY (unit_price::double precision)) AS p90
    FROM insights.cost_events
    WHERE cost_type::text = 'material'::text AND unit_price > 0::numeric
      AND (description ~~* '%toner%'::text OR description ~~* '%patrone%'::text OR description ~~* '%cartridge%'::text)
), resid AS (
    SELECT GREATEST(0::numeric, 1::numeric - LEAST(wa.pct_of_oem, 100::numeric) / 100.0) AS frac,
           COALESCE(CASE WHEN r.n >= 5 THEN r.median_eur ELSE NULL::double precision END, gp.med) AS price_eur
    FROM insights.vw_warranty_assessment wa
    CROSS JOIN gp
    LEFT JOIN insights.vw_toner_price_ref r ON r.mfr::text = wa.manufacturer_canonical::text
    WHERE wa.warranty_class = 'claim'::text AND wa.colorant IS NOT NULL AND wa.colorant::text <> ''::text
)
SELECT
    (SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim'::text) AS garantie_claims,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim'::text AND cartridge_serial IS NOT NULL) AS garantie_claims_serial,
    (SELECT round(avg(pct_of_oem)) FROM insights.vw_warranty_assessment WHERE warranty_class = 'claim'::text) AS claim_schnitt_pct,
    (SELECT round(sum(GREATEST(0::numeric, 1::numeric - LEAST(pct_of_oem, 100::numeric) / 100.0)), 1)
        FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim'::text AND colorant IS NOT NULL AND colorant::text <> ''::text) AS claim_restwert_summe,
    (SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class = 'negotiation'::text) AS verhandlung_kandidaten,
    (SELECT count(DISTINCT device_serial) FROM insights.vw_part_early_failures
        WHERE konfidenz = ANY (ARRAY['hoch'::text, 'mittel'::text])) AS ersatzteil_fruehausfaelle,
    (SELECT round(percentile_cont(0.5::double precision) WITHIN GROUP (ORDER BY (unit_price::double precision)))
        FROM insights.cost_events
        WHERE cost_type::text = 'material'::text AND unit_price > 0::numeric
          AND (description ~~* '%toner%'::text OR description ~~* '%patrone%'::text OR description ~~* '%cartridge%'::text)) AS toner_preis_median,
    (SELECT count(*) FROM insights.vw_billing_risk) AS stille_unter_vertrag,
    (SELECT count(*) FROM insights.vw_customer_device_mismatch WHERE abgleich = 'abweichung'::text) AS kunden_abweichung,
    (SELECT count(*) FROM insights.vw_consumables_due WHERE remaining_days <= 14) AS verbrauch_14d,
    (SELECT count(*) FROM insights.vw_problem_devices) AS problem_geraete,
    (SELECT count(*) FROM insights.devices_unified
        WHERE device_status::text = 'live'::text AND NOT COALESCE(is_queue_artifact, false)) AS geraete_live,
    'insights'::character varying AS source_system,
    (SELECT count(*) FROM insights.vw_warranty_assessment
        WHERE warranty_class = 'claim'::text AND colorant IS NOT NULL AND colorant::text <> ''::text) AS garantie_claims_toner,
    (SELECT round(sum(resid.frac::double precision * resid.price_eur)) FROM resid) AS claim_restwert_eur,
    (SELECT round(sum(resid.frac)::double precision * (SELECT gp.p10 FROM gp)) FROM resid) AS claim_restwert_eur_low,
    (SELECT round(sum(resid.frac)::double precision * (SELECT gp.p90 FROM gp)) FROM resid) AS claim_restwert_eur_high,
    (SELECT gp.p10 FROM gp) AS toner_preis_p10,
    (SELECT gp.p90 FROM gp) AS toner_preis_p90,
    (SELECT count(DISTINCT device_serial) FROM insights.vw_part_early_failures
        WHERE konfidenz = 'niedrig'::text) AS ersatzteil_fruehausfaelle_zeitbasiert;

-- 3) Lizenz-Verschwendung: Queue-Artefakte raus (318 still-Phantome wurden bisher als
--    "hoch"-Delisting-Kandidaten gelistet, obwohl es keine lizenzierten Geraete sind).
CREATE OR REPLACE VIEW insights.vw_lizenz_verschwendung AS
SELECT
    d.customer_name,
    d.customer_city,
    d.manufacturer_canonical,
    d.model_display,
    d.manufacturer_serial      AS device_serial,
    d.radix_device_number,
    d.device_status,
    d.last_data_transfer_at::date AS letzte_meldung,
    (CURRENT_DATE - d.last_data_transfer_at::date) AS tage_inaktiv,
    (d.radix_device_number IS NOT NULL) AS in_radix,
    COALESCE(d.contract_active, false)  AS aktiver_vertrag,
    CASE
        WHEN d.device_status = 'never_reported'
             OR (d.device_status = 'silent' AND d.last_data_transfer_at < now() - interval '365 days'
                 AND d.radix_device_number IS NULL)
             OR d.manufacturer_canonical IS NULL
            THEN 'hoch'
        WHEN d.last_data_transfer_at < now() - interval '180 days' THEN 'mittel'
        ELSE 'niedrig'
    END AS lizenz_risiko,
    NULLIF(trim(BOTH ' ,' FROM concat_ws(', ',
        CASE WHEN d.device_status = 'never_reported' THEN 'nie gemeldet' END,
        CASE WHEN d.device_status = 'silent' AND d.last_data_transfer_at IS NOT NULL
             THEN 'still seit ' || (CURRENT_DATE - d.last_data_transfer_at::date) || ' Tagen' END,
        CASE WHEN d.radix_device_number IS NULL THEN 'nicht in Radix' END,
        CASE WHEN d.manufacturer_canonical IS NULL THEN 'ohne Modell/Hersteller' END,
        CASE WHEN COALESCE(d.contract_active, false) = false THEN 'kein aktiver Vertrag' END
    )), '') AS grund
FROM insights.devices_unified d
WHERE d.device_status NOT IN ('deleted', 'deactivated')   -- noch CSP-lizenziert (= Status-Flag)
  AND NOT COALESCE(d.unmanaged, false)                    -- und NICHT bereits unmanaged gesetzt
  AND NOT COALESCE(d.is_queue_artifact, false)            -- und kein Print-Server-Queue-Artefakt
  AND d.device_status <> 'live';                          -- aber nicht aktiv = Verschwendungs-Verdacht

-- 4) Print-Server-Kunden: wo wird ueber einen zentralen Print-Server ueberwacht?
--    Nuetzlich fuer Service/Cleanup (Agent bei Vertragsende deinstallieren) und um zu
--    verstehen, warum manche Kunden "Phantom-Geraete" in der Flotte haben.
CREATE OR REPLACE VIEW insights.vw_print_server_kunden AS
SELECT
    d.customer_name,
    d.customer_city,
    count(*) FILTER (WHERE d.is_queue_artifact)                                  AS queue_artefakte,
    count(*) FILTER (WHERE NOT COALESCE(d.is_queue_artifact, false)
                     AND d.device_status = 'live')                               AS echte_live_geraete,
    -- haeufigstes Praefix-Schema der Queue-Namen (Buchstaben + optionaler Bindestrich,
    -- z. B. "PS", "mfde", "konica", "DN-") - der numerische Teil dahinter variiert je Queue.
    (SELECT substring(x.printer_ip FROM '^[A-Za-z]+[-]?')
     FROM insights.devices_unified x
     WHERE x.customer_name IS NOT DISTINCT FROM d.customer_name
       AND x.is_queue_artifact
     GROUP BY substring(x.printer_ip FROM '^[A-Za-z]+[-]?')
     ORDER BY count(*) DESC LIMIT 1)                                             AS namensschema,
    (array_agg(d.printer_ip ORDER BY d.printer_ip)
        FILTER (WHERE d.is_queue_artifact))[1]                                   AS beispiel_queue
FROM insights.devices_unified d
GROUP BY d.customer_name, d.customer_city
HAVING count(*) FILTER (WHERE d.is_queue_artifact) > 0
ORDER BY queue_artefakte DESC;
