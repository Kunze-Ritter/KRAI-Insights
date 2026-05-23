-- 044_coverage_analytics.sql
-- Coverage analytics on top of the (now coverage-aware) warranty data:
--  (a) per-device + per-customer real print coverage (page-weighted) — customers
--      over 6% are billed below their actual toner use (click price assumes ~6%)
--      -> recalculation candidates + a useful service signal.
--  (b) developer-unit early failures vs the device's coverage — HP's tip: printing
--      above ~5% unbalances the toner/developer mix and kills developer units early.
-- Coverage uses valid CoveragePercentIs only (0.5..100), page-weighted.

CREATE OR REPLACE VIEW insights.vw_device_coverage AS
SELECT
    d.manufacturer_serial AS device_serial, d.radix_device_number, d.customer_name,
    d.customer_city, d.manufacturer_canonical, d.model_display,
    sum(v.pages_since_previous)                                                       AS gedruckte_seiten,
    round(sum(v.pages_since_previous::numeric * v.coverage_real_pct)
          / NULLIF(sum(v.pages_since_previous), 0), 1)                                AS avg_deckung_pct,
    'fleetmgmt'::varchar AS source_system
FROM insights.vw_vbm_lifecycle v
JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
WHERE v.coverage_real_pct > 0.5 AND v.coverage_real_pct <= 100 AND v.pages_since_previous > 0
GROUP BY d.manufacturer_serial, d.radix_device_number, d.customer_name, d.customer_city,
         d.manufacturer_canonical, d.model_display
HAVING sum(v.pages_since_previous) >= 500;

-- Per customer (page-weighted). >6% = above the click-price assumption -> recalc.
CREATE OR REPLACE VIEW insights.vw_coverage_by_customer AS
WITH cov AS (
    SELECT d.customer_name, d.customer_city,
           sum(v.pages_since_previous::numeric * v.coverage_real_pct) AS num,
           sum(v.pages_since_previous)                                AS seiten,
           count(DISTINCT d.fleetmgmt_device_id)                      AS geraete
    FROM insights.vw_vbm_lifecycle v
    JOIN insights.devices_unified d ON d.fleetmgmt_device_id = v.fleetmgmt_device_id
    WHERE v.coverage_real_pct > 0.5 AND v.coverage_real_pct <= 100 AND v.pages_since_previous > 0
      AND d.customer_name IS NOT NULL
    GROUP BY d.customer_name, d.customer_city
    HAVING sum(v.pages_since_previous) >= 1000
)
SELECT
    customer_name, customer_city, geraete, seiten AS gedruckte_seiten,
    round(num / seiten, 1)        AS avg_deckung_pct,
    (num / seiten > 6)            AS ueber_klickpreis_6pct,
    (num / seiten > 5)            AS ueber_iso_5pct,
    'fleetmgmt'::varchar AS source_system
FROM cov
ORDER BY avg_deckung_pct DESC;

-- Developer-unit early failures + the device's coverage. High coverage + early
-- failure = the HP-flagged toner/developer imbalance — for service/technicians.
CREATE OR REPLACE VIEW insights.vw_developer_unit_risk AS
SELECT
    pe.customer_name, pe.manufacturer_canonical, pe.model_display, pe.device_serial,
    pe.radix_device_number, pe.description AS entwicklereinheit,
    pe.einbau_datum, pe.erneut_getauscht, pe.standzeit_tage, pe.standzeit_seiten,
    dc.avg_deckung_pct, dc.gedruckte_seiten,
    (dc.avg_deckung_pct > 5) AS deckung_ueber_5pct,
    pe.diagnose,
    'radix+fleetmgmt'::varchar AS source_system
FROM insights.vw_part_early_failures pe
LEFT JOIN insights.vw_device_coverage dc ON dc.device_serial = pe.device_serial
WHERE pe.teiltyp = 'Entwickler'
ORDER BY dc.avg_deckung_pct DESC NULLS LAST, pe.standzeit_tage ASC;
