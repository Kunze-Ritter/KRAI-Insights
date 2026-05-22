-- 023_customer_mismatch_ip_evidence.sql
-- Strengthen vw_customer_device_mismatch with telemetry + IP-subnet evidence.
-- When FleetMgmt and Radix disagree on a device's customer, the device's LIVE IP
-- is the real arbiter: a copier sitting in a customer's /24 subnet is physically
-- at that customer. We corroborate each side by checking whether OTHER devices of
-- the FleetMgmt customer vs. the Radix customer share the device's /24 -> the
-- dashboard shows which record to trust (and which to correct in FleetMgmt/CSP).
--   subnetz_passt_zu: fleet | radix | beide (shared/common subnet) | unklar | kein_ip
-- (column set changes -> drop + recreate.)
DROP VIEW IF EXISTS insights.vw_customer_device_mismatch;
CREATE VIEW insights.vw_customer_device_mismatch AS
WITH dev AS (
    SELECT
        d.id, d.manufacturer_serial, d.radix_device_number, d.manufacturer_canonical,
        d.model_display, d.customer_name, d.customer_city, d.radix_customer_id,
        d.device_status, d.telemetry_stale_days, d.last_data_transfer_at, d.printer_ip,
        CASE WHEN d.printer_ip ~ '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'
             THEN regexp_replace(d.printer_ip, '\.[0-9]+$', '') END AS sub24
    FROM insights.devices_unified d
),
-- (customer, /24) device counts: count>1 means another device corroborates.
fleet_cnt AS (
    SELECT customer_name, sub24, count(*) AS c FROM dev
    WHERE sub24 IS NOT NULL AND customer_name IS NOT NULL GROUP BY customer_name, sub24
),
radix_cnt AS (
    SELECT radix_customer_id, sub24, count(*) AS c FROM dev
    WHERE sub24 IS NOT NULL AND radix_customer_id IS NOT NULL GROUP BY radix_customer_id, sub24
),
paired AS (
    SELECT
        v.*, rc.name AS radix_kunde, rc.city AS radix_ort,
        insights.norm_company_name(v.customer_name) AS nf,
        insights.norm_company_name(rc.name)         AS nr,
        lower(btrim(COALESCE(v.customer_city, ''))) AS cf,
        lower(btrim(COALESCE(rc.city, '')))         AS cr
    FROM dev v
    JOIN insights.radix_customers rc ON rc.radix_customer_id = v.radix_customer_id
    WHERE v.customer_name IS NOT NULL AND rc.name IS NOT NULL
)
SELECT
    p.manufacturer_serial AS device_serial, p.radix_device_number,
    p.manufacturer_canonical, p.model_display,
    p.customer_name AS fleet_kunde, p.radix_kunde,
    p.customer_city AS fleet_ort, p.radix_ort,
    p.device_status, p.telemetry_stale_days,
    p.last_data_transfer_at::date AS last_report,
    p.printer_ip, p.sub24 AS ip_subnetz,
    (p.cf = p.cr AND p.cf <> '') AS ort_gleich,
    CASE
        WHEN p.nf = p.nr THEN 'uebereinstimmung'
        WHEN p.nf IS NOT NULL AND p.nr IS NOT NULL AND EXISTS (
            SELECT 1 FROM unnest(string_to_array(p.nf, ' ')) t(w)
            WHERE length(w) >= 4 AND w = ANY(string_to_array(p.nr, ' '))
        ) THEN 'teilweise'
        ELSE 'abweichung'
    END AS abgleich,
    CASE
        WHEN p.sub24 IS NULL THEN 'kein_ip'
        WHEN COALESCE(fc.c, 0) > 1 AND COALESCE(rxc.c, 0) > 1 THEN 'beide'
        WHEN COALESCE(rxc.c, 0) > 1 THEN 'radix'
        WHEN COALESCE(fc.c, 0) > 1 THEN 'fleet'
        ELSE 'unklar'
    END AS subnetz_passt_zu,
    'fleetmgmt+radix'::varchar AS source_system
FROM paired p
LEFT JOIN fleet_cnt fc  ON fc.customer_name = p.customer_name AND fc.sub24 = p.sub24
LEFT JOIN radix_cnt rxc ON rxc.radix_customer_id = p.radix_customer_id AND rxc.sub24 = p.sub24
ORDER BY (CASE WHEN p.nf = p.nr THEN 2 ELSE 0 END), p.manufacturer_serial;
