-- 014_cost_views.sql
-- Cost summaries over cost_events. Material € is the charged price; labour is in
-- hours (a € rate is a config input). invoicing_type splits contract-covered
-- (VER), billable (AUF), warranty (GAR) and flat-rate (PAU) work.

-- Cost structure of the whole fleet by invoicing type.
CREATE OR REPLACE VIEW insights.vw_cost_by_invoicing AS
SELECT
    COALESCE(invoicing_type, '(ohne)') AS invoicing_type,
    cost_type,
    count(*)                                 AS lines,
    round(COALESCE(sum(total_eur), 0), 2)    AS material_eur,
    round(COALESCE(sum(duration_minutes), 0) / 60.0, 1) AS labor_hours,
    'radix'::varchar AS source_system
FROM insights.cost_events
GROUP BY COALESCE(invoicing_type, '(ohne)'), cost_type;

-- Cost per customer (material € + labour hours, billable vs contract split).
CREATE OR REPLACE VIEW insights.vw_cost_by_customer AS
WITH namen AS (
    SELECT DISTINCT ON (radix_customer_id) radix_customer_id, customer_name
    FROM insights.devices_unified
    WHERE radix_customer_id IS NOT NULL AND customer_name IS NOT NULL
    ORDER BY radix_customer_id, customer_name
)
SELECT
    n.customer_name,
    ce.radix_customer_id,
    round(COALESCE(sum(ce.total_eur) FILTER (WHERE ce.cost_type = 'material'), 0), 2)         AS material_eur,
    round(COALESCE(sum(ce.duration_minutes) FILTER (WHERE ce.cost_type = 'labor'), 0) / 60.0, 1) AS labor_hours,
    round(COALESCE(sum(ce.total_eur) FILTER (
        WHERE ce.cost_type = 'material' AND ce.invoicing_type LIKE 'AUF%'), 0), 2)            AS billable_material_eur,
    round(COALESCE(sum(ce.total_eur) FILTER (
        WHERE ce.cost_type = 'material' AND ce.invoicing_type LIKE 'VER%'), 0), 2)            AS contract_material_eur,
    count(*) FILTER (WHERE ce.cost_type = 'material')                                          AS material_lines,
    count(*) FILTER (WHERE ce.cost_type = 'labor')                                            AS labor_lines,
    'radix'::varchar AS source_system
FROM insights.cost_events ce
LEFT JOIN namen n ON n.radix_customer_id = ce.radix_customer_id
GROUP BY n.customer_name, ce.radix_customer_id;
