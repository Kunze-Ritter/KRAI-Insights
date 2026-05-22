-- 008_model_backfill_view.sql
-- The OEM-model-code backfill list: each canonical model with the OEM code
-- (Radix article.model) observed on its devices + how many devices carry it.
-- This is the list to feed into krai_core.products.article_code (currently empty).
CREATE OR REPLACE VIEW insights.vw_model_code_backfill AS
SELECT
    mc.manufacturer,
    mc.model_number,
    mc.manufacturer_model_code,
    count(d.id) AS device_count,
    'fleetmgmt+radix'::varchar AS source_system
FROM insights.model_catalog mc
LEFT JOIN insights.devices_unified d ON d.model_id = mc.id
WHERE mc.manufacturer_model_code IS NOT NULL
GROUP BY mc.manufacturer, mc.model_number, mc.manufacturer_model_code
ORDER BY count(d.id) DESC;
