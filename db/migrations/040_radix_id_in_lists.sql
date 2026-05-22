-- 040_radix_id_in_lists.sql
-- Surface the Radix device id (radix_device_number) in the lists that lacked it —
-- it's the number staff search by in Radix to verify/correct a device. Most views
-- already carry it; these three didn't. CREATE OR REPLACE appends the column.

-- Spare-part early failures: resolve via the device serial.
CREATE OR REPLACE VIEW insights.vw_part_early_failures AS
SELECT
    spe.customer_name, spe.manufacturer_canonical, spe.model_display, spe.device_serial,
    spe.teiltyp, spe.description, spe.einbau_datum, spe.naechster_tausch AS erneut_getauscht,
    spe.standzeit_tage, spe.standzeit_seiten, spe.diagnose, spe.invoicing_type,
    'radix+fleetmgmt'::varchar AS source_system,
    spe.oem_nominal_seiten, spe.pct_vom_oem,
    CASE WHEN spe.oem_nominal_seiten IS NOT NULL AND spe.standzeit_seiten IS NOT NULL
         THEN 'OEM-Soll (Seiten)' ELSE 'Zeit (1 Jahr)' END AS basis,
    (SELECT du.radix_device_number FROM insights.devices_unified du
       WHERE du.manufacturer_serial = spe.device_serial LIMIT 1) AS radix_device_number
FROM insights.vw_spare_part_events spe
WHERE spe.teiltyp NOT IN ('Toner', 'unbekannt')
  AND (
        (spe.oem_nominal_seiten IS NOT NULL AND spe.standzeit_seiten IS NOT NULL
            AND spe.standzeit_tage >= 7 AND spe.pct_vom_oem < 70)
     OR ((spe.oem_nominal_seiten IS NULL OR spe.standzeit_seiten IS NULL)
            AND spe.standzeit_tage BETWEEN 7 AND 365)
      )
ORDER BY spe.pct_vom_oem ASC NULLS LAST, spe.standzeit_tage ASC;

-- Teilewechsel-Validierung: device already joined, just expose radix_device_number.
DROP VIEW IF EXISTS insights.vw_vbm_validation;
CREATE VIEW insights.vw_vbm_validation AS
WITH cand AS (
    SELECT
        v.fleetmgmt_device_id, v.colorant, v.marker_name, v.cartridge_serial,
        v.occurred_at, v.classification, v.likely_false_report, v.pages_since_previous,
        d.manufacturer_serial AS device_serial, d.radix_device_number,
        d.radix_customer_id, d.customer_name, d.manufacturer_canonical, d.model_display
    FROM insights.vw_vbm_lifecycle v
    JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
    WHERE v.classification = 'real_new_cartridge' OR v.likely_false_report
)
SELECT
    cand.customer_name, cand.manufacturer_canonical, cand.model_display, cand.device_serial,
    cand.radix_device_number,
    cand.colorant, cand.marker_name, cand.cartridge_serial, cand.occurred_at::date AS event_date,
    cand.classification, cand.likely_false_report, cand.pages_since_previous,
    m.geraet_match, m.kunde_match,
    CASE
        WHEN m.geraet_match THEN 'radix_geraet'
        WHEN m.kunde_match THEN 'radix_kunde'
        WHEN cand.likely_false_report THEN 'verdacht_fake'
        ELSE 'nur_fleet'
    END AS validierung,
    'fleetmgmt+radix'::varchar AS source_system
FROM cand
LEFT JOIN LATERAL (
    SELECT
        EXISTS (
            SELECT 1 FROM insights.cost_events ce
            WHERE ce.cost_type = 'material' AND ce.device_serial = cand.device_serial
              AND ce.occurred_at BETWEEN cand.occurred_at - INTERVAL '21 days'
                                     AND cand.occurred_at + INTERVAL '21 days'
        ) AS geraet_match,
        EXISTS (
            SELECT 1 FROM insights.cost_events ce
            WHERE ce.cost_type = 'material'
              AND cand.radix_customer_id IS NOT NULL
              AND ce.radix_customer_id = cand.radix_customer_id
              AND ce.occurred_at BETWEEN cand.occurred_at - INTERVAL '21 days'
                                     AND cand.occurred_at + INTERVAL '21 days'
        ) AS kunde_match
) m ON TRUE;

-- Material-Einbau-Prüfung: resolve the booked device's Radix id.
CREATE OR REPLACE VIEW insights.vw_material_install_check AS
WITH radix_toner AS (
    SELECT
        ce.id, ce.radix_customer_id, ce.device_serial AS booked_serial,
        ce.occurred_at::date AS lieferdatum, ce.description, ce.article_code,
        CASE
            WHEN ce.description ILIKE '%schwarz%' OR ce.description ILIKE '%black%' THEN 'black'
            WHEN ce.description ILIKE '%cyan%' THEN 'cyan'
            WHEN ce.description ILIKE '%magenta%' THEN 'magenta'
            WHEN ce.description ILIKE '%gelb%' OR ce.description ILIKE '%yellow%' THEN 'yellow'
        END AS colorant
    FROM insights.cost_events ce
    WHERE ce.cost_type = 'material' AND ce.device_serial IS NOT NULL
      AND (ce.description ILIKE '%toner%' OR ce.description ILIKE '%patrone%' OR ce.description ILIKE '%cartridge%')
)
SELECT
    rt.radix_customer_id, rt.booked_serial, rt.colorant, rt.lieferdatum, rt.description,
    s.same_device, s.elsewhere_device,
    CASE
        WHEN s.same_device THEN 'korrekt'
        WHEN s.elsewhere_device THEN 'woanders_eingebaut'
        ELSE 'kein_einbau_gefunden'
    END AS einbau_status,
    'fleetmgmt+radix'::varchar AS source_system,
    (SELECT du.radix_device_number FROM insights.devices_unified du
       WHERE du.manufacturer_serial = rt.booked_serial LIMIT 1) AS radix_device_number
FROM radix_toner rt
LEFT JOIN LATERAL (
    SELECT
        EXISTS (
            SELECT 1 FROM insights.vbm_lifecycle_events v
            JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
            WHERE d.manufacturer_serial = rt.booked_serial AND v.colorant = rt.colorant
              AND v.occurred_at::date BETWEEN rt.lieferdatum - 30 AND rt.lieferdatum + 30
        ) AS same_device,
        EXISTS (
            SELECT 1 FROM insights.vbm_lifecycle_events v
            JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
            WHERE d.radix_customer_id = rt.radix_customer_id
              AND d.manufacturer_serial IS DISTINCT FROM rt.booked_serial
              AND v.colorant = rt.colorant
              AND v.occurred_at::date BETWEEN rt.lieferdatum - 30 AND rt.lieferdatum + 30
        ) AS elsewhere_device
) s ON TRUE
WHERE rt.colorant IS NOT NULL;
