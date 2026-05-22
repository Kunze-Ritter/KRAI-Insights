-- 022_customer_normalization.sql
-- Customer master from Radix (PII-safe: only company + location; email/phone/
-- salutation are dropped by the RadixCustomer Pydantic model on load) + a name
-- normalisation function + a FleetMgmt<->Radix per-device customer mismatch view.
--
-- Why: customer records are entered inconsistently (underscores, legal forms,
-- typos) and a device's customer can differ between the two systems (resold unit
-- or a wrong serial match) -> Toner mis-shipping. Normalisation unifies the
-- "same company, different spelling" case so the genuine mismatches stand out.

CREATE TABLE IF NOT EXISTS insights.radix_customers (
    radix_customer_id VARCHAR(40) PRIMARY KEY,
    number            INTEGER,
    name              VARCHAR(300),   -- description (company name)
    optional          VARCHAR(300),   -- secondary name line
    legalform         VARCHAR(60),
    street            VARCHAR(200),
    zip               VARCHAR(20),
    city              VARCHAR(120),   -- town
    country           VARCHAR(8),
    address_id        VARCHAR(40),
    inactive          BOOLEAN,
    source_system     VARCHAR NOT NULL DEFAULT 'radix',
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_radix_customers_name ON insights.radix_customers (lower(name));

-- Canonical key for a company name: lowercase, fold umlauts, drop punctuation,
-- strip common legal forms. "Marinus GmbH & Co. KG" / "Marinus_GmbH" -> "marinus".
CREATE OR REPLACE FUNCTION insights.norm_company_name(p text)
RETURNS text LANGUAGE plpgsql IMMUTABLE AS $fn$
DECLARE s text;
BEGIN
    IF p IS NULL THEN RETURN NULL; END IF;
    s := lower(p);
    s := replace(s, 'ä', 'ae'); s := replace(s, 'ö', 'oe'); s := replace(s, 'ü', 'ue');
    s := replace(s, 'ß', 'ss'); s := replace(s, '_', ' ');
    s := regexp_replace(s, '[^a-z0-9]+', ' ', 'g');
    s := regexp_replace(s, '\y(gmbh|mbh|ggmbh|ag|kg|kgaa|ohg|gbr|ek|ev|se|ug|co|inc|ltd|llc|partg|partgmbb)\y', ' ', 'g');
    s := btrim(regexp_replace(s, '\s+', ' ', 'g'));
    RETURN NULLIF(s, '');
END $fn$;

-- Per device (serial-joined): FleetMgmt customer vs the device's Radix customer.
--   uebereinstimmung — normalised names equal (same company, formatting only)
--   teilweise        — share a meaningful token (>=4 chars) -> probably the same
--   abweichung       — no overlap -> review (owner change OR a wrong serial match)
CREATE OR REPLACE VIEW insights.vw_customer_device_mismatch AS
WITH paired AS (
    SELECT
        d.manufacturer_serial AS device_serial, d.radix_device_number,
        d.manufacturer_canonical, d.model_display,
        d.customer_name AS fleet_kunde, d.customer_city AS fleet_ort,
        rc.name AS radix_kunde, rc.city AS radix_ort,
        insights.norm_company_name(d.customer_name) AS nf,
        insights.norm_company_name(rc.name)         AS nr,
        lower(btrim(COALESCE(d.customer_city, ''))) AS cf,
        lower(btrim(COALESCE(rc.city, '')))         AS cr
    FROM insights.devices_unified d
    JOIN insights.radix_customers rc ON rc.radix_customer_id = d.radix_customer_id
    WHERE d.customer_name IS NOT NULL AND rc.name IS NOT NULL
)
SELECT
    device_serial, radix_device_number, manufacturer_canonical, model_display,
    fleet_kunde, radix_kunde, fleet_ort, radix_ort,
    (cf = cr AND cf <> '') AS ort_gleich,
    CASE
        WHEN nf = nr THEN 'uebereinstimmung'
        WHEN nf IS NOT NULL AND nr IS NOT NULL AND EXISTS (
            SELECT 1 FROM unnest(string_to_array(nf, ' ')) t(w)
            WHERE length(w) >= 4 AND w = ANY(string_to_array(nr, ' '))
        ) THEN 'teilweise'
        ELSE 'abweichung'
    END AS abgleich,
    'fleetmgmt+radix'::varchar AS source_system
FROM paired
ORDER BY (CASE WHEN nf = nr THEN 2 ELSE 0 END), device_serial;
