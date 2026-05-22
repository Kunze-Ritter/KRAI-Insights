-- 024_shipping_addresses.sql
-- Radix per-customer delivery addresses (where toner/parts ship to). PII-safe:
-- the RadixShippingAddress model drops the "z.Hd." care-of line + email/phone/
-- salutation on load; only the delivery location (label + street + city) is kept.
-- NOTE: the API does NOT expose a device's specific shippingAddressId, so this is
-- resolved per CUSTOMER, not per device. A customer with many addresses (e.g. a
-- city administration) is flagged so delivery routing gets extra care.
CREATE TABLE IF NOT EXISTS insights.radix_shipping_addresses (
    id                VARCHAR(40) PRIMARY KEY,
    radix_customer_id VARCHAR(40),
    address_id        VARCHAR(40),
    description       VARCHAR(300),   -- location/branch label
    street            VARCHAR(200),
    streetnumber      VARCHAR(40),
    zip               VARCHAR(20),
    city              VARCHAR(120),
    country           VARCHAR(8),
    is_default        BOOLEAN,
    inactive          BOOLEAN,
    source_system     VARCHAR NOT NULL DEFAULT 'radix',
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_radix_shipping_customer ON insights.radix_shipping_addresses (radix_customer_id);

-- Delivery-address summary per customer (joins the company name + device count).
CREATE OR REPLACE VIEW insights.vw_customer_shipping AS
WITH cnt AS (
    SELECT radix_customer_id,
           count(*)                                        AS lieferadressen,
           count(*) FILTER (WHERE NOT COALESCE(inactive, FALSE)) AS aktive_adressen
    FROM insights.radix_shipping_addresses
    GROUP BY radix_customer_id
),
dev AS (
    SELECT radix_customer_id, count(*) AS geraete
    FROM insights.devices_unified WHERE radix_customer_id IS NOT NULL
    GROUP BY radix_customer_id
)
SELECT
    rc.radix_customer_id, rc.name AS kunde, rc.city AS kunde_ort,
    COALESCE(cnt.lieferadressen, 0) AS lieferadressen,
    COALESCE(cnt.aktive_adressen, 0) AS aktive_lieferadressen,
    COALESCE(dev.geraete, 0) AS geraete,
    'radix'::varchar AS source_system
FROM insights.radix_customers rc
LEFT JOIN cnt ON cnt.radix_customer_id = rc.radix_customer_id
LEFT JOIN dev ON dev.radix_customer_id = rc.radix_customer_id
WHERE COALESCE(cnt.lieferadressen, 0) > 0;
