-- 012_device_contracts.sql
-- Contracts per device from Radix (/api/serialnumber/contracts): validity dates +
-- type + auto-renewal. FleetMgmt lacks this (charge columns empty), so contract
-- status comes from Radix. No prices, no PII. devices_unified.contract_active /
-- contract_end are derived from this table.
CREATE TABLE IF NOT EXISTS insights.device_contracts (
    id                    BIGSERIAL PRIMARY KEY,
    radix_contract_id     VARCHAR(40) NOT NULL,
    device_id             UUID REFERENCES insights.devices_unified(id),
    radix_serialnumber_id VARCHAR(40),
    radix_customer_id     VARCHAR(40),
    code                  VARCHAR(100),         -- e.g. "KVE - 2022 - 5670"
    contract_type         VARCHAR(200),         -- description, e.g. "Fremdmiete Full Service"
    valid_from            DATE,
    valid_until           DATE,
    is_auto_renewal       BOOLEAN,
    is_done               BOOLEAN,
    source_system         VARCHAR(20) NOT NULL DEFAULT 'radix',
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (radix_contract_id, radix_serialnumber_id)
);
CREATE INDEX IF NOT EXISTS ix_device_contracts_device ON insights.device_contracts (device_id);
CREATE INDEX IF NOT EXISTS ix_device_contracts_until ON insights.device_contracts (valid_until);

-- Contracts ending soon and not auto-renewing (proactive renewal worklist).
CREATE OR REPLACE VIEW insights.vw_contract_renewal_radar AS
SELECT
    d.customer_name,
    d.customer_city,
    d.manufacturer_serial AS device_serial,
    d.radix_device_number,
    d.manufacturer_canonical,
    d.model_display,
    c.code,
    c.contract_type,
    c.valid_until,
    c.is_auto_renewal,
    'radix'::varchar AS source_system
FROM insights.device_contracts c
JOIN insights.devices_unified d ON d.id = c.device_id
WHERE c.valid_until >= current_date
  AND c.valid_until <= current_date + INTERVAL '90 days'
  AND COALESCE(c.is_auto_renewal, FALSE) = FALSE;

-- Active devices without a current contract (up-sell candidates).
CREATE OR REPLACE VIEW insights.vw_out_of_contract_devices AS
SELECT
    customer_name,
    customer_city,
    manufacturer_serial AS device_serial,
    radix_device_number,
    manufacturer_canonical,
    model_display,
    device_status,
    'fleetmgmt+radix'::varchar AS source_system
FROM insights.devices_unified
WHERE device_status = 'live' AND COALESCE(contract_active, FALSE) = FALSE;
