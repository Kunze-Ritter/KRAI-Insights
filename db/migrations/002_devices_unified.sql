-- 002_devices_unified.sql
-- Core unified device registry + model crosswalk + match review queue.
--
-- Principles (per the approved plan):
--  * The Insights DB is a DERIVED, read-only cache — every row carries source
--    lineage (source_systems, ingested_at) and can be rebuilt from the sources.
--  * All timestamps are UTC (TIMESTAMPTZ). FleetMgmt runs on UTC; Radix sends Z.
--  * NO personal data (DSGVO): no email, person name, phone, credentials, IP.
--    Only company name + location (city) and a pseudonymous user id are kept.
--
-- Join spine: FleetMgmt ACCDEVICES.SerialNo == Radix serialnumber.numberManufactor.
-- Device->customer in FleetMgmt: ACCDEVICES.SubmitterId -> ACCUSERS.Id (verified;
-- ACCUSERS.Name is the company name, DeviceManagerId is the MSP, not the customer).

-- ---------------------------------------------------------------------------
-- Canonical model catalog (mirrors krai_core; captures the OEM model code so it
-- can later backfill krai_core.products.article_code).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insights.model_catalog (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manufacturer            VARCHAR(100),            -- canonical (e.g. "Konica Minolta")
    model_number            VARCHAR(200),            -- canonical model (e.g. "bizhub C450i")
    series                  VARCHAR(100),
    manufacturer_model_code VARCHAR(100),            -- OEM code (Radix article.model, e.g. AA7R021)
    krai_product_id         UUID,                    -- loose ref to krai_core.products.id (string-coupled)
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (manufacturer, model_number)
);

-- Observed model identifiers per source -> canonical model. Built semi-
-- automatically from serial-joined ground-truth (FleetMgmt name co-occurs with
-- the Radix OEM code on the same physical device).
CREATE TABLE IF NOT EXISTS insights.model_aliases (
    id            BIGSERIAL PRIMARY KEY,
    model_id      UUID REFERENCES insights.model_catalog(id) ON DELETE CASCADE,
    source_system VARCHAR(20) NOT NULL,              -- 'fleetmgmt' | 'radix' | 'krai'
    raw_value     VARCHAR(300) NOT NULL,             -- name/code as it appears in the source
    kind          VARCHAR(20) NOT NULL,              -- 'display_name' | 'oem_code' | 'searchtext'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_system, kind, raw_value)
);

-- ---------------------------------------------------------------------------
-- Master unified device record (the fusion spine).
-- Natural key = manufacturer_serial when present; serial-less FleetMgmt devices
-- fall back to fleetmgmt_device_id (both enforced via partial unique indexes).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insights.devices_unified (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manufacturer_serial     VARCHAR(100),
    -- identifiers (all three kept; agent can look up by any)
    radix_device_number     VARCHAR(50),             -- Radix serialnumber.number (staff search id)
    radix_serialnumber_id   VARCHAR(40),             -- Radix GUID handle for /serialnumber/* calls
    fleetmgmt_device_id     INTEGER,                 -- ACCDEVICES.Id
    fleetmgmt_user_id       INTEGER,                 -- ACCDEVICES.SubmitterId -> ACCUSERS.Id
    internal_id             VARCHAR(50),             -- extracted from ACCDEVICES.Location
    -- customer (company + location only; NO PII)
    customer_name           VARCHAR(200),
    customer_city           VARCHAR(100),
    customer_id_canonical    VARCHAR(100),
    radix_customer_id       VARCHAR(40),
    -- model
    manufacturer_canonical  VARCHAR(100),
    model_display           VARCHAR(200),            -- FleetMgmt ACCDEVICES.Model
    manufacturer_model_code VARCHAR(100),            -- Radix article.model (OEM code)
    model_id                UUID REFERENCES insights.model_catalog(id),
    series                  VARCHAR(100),
    -- lifecycle / warranty / contract (contract_* come from Radix)
    deployed_date           DATE,
    production_date         DATE,
    warranty_supplier       VARCHAR(100),
    contract_active         BOOLEAN,
    contract_end            DATE,
    -- status / telemetry (combined FleetMgmt LastDataTransferDate + Radix signal)
    last_data_transfer_at   TIMESTAMPTZ,
    last_counter_at         TIMESTAMPTZ,
    device_status           VARCHAR(20),             -- live|silent|never_reported|deactivated|deleted
    telemetry_stale_days    INTEGER,
    radix_no_signal_ticket  BOOLEAN NOT NULL DEFAULT FALSE,
    -- matching + lineage
    match_type              VARCHAR(20),             -- serial|internal_id|customer_map|unmatched
    match_confidence        NUMERIC(4,3),
    source_systems          VARCHAR(20)[] NOT NULL DEFAULT '{}',
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_unified_serial
    ON insights.devices_unified (manufacturer_serial)
    WHERE manufacturer_serial IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_unified_fleetmgmt_id
    ON insights.devices_unified (fleetmgmt_device_id)
    WHERE fleetmgmt_device_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_devices_unified_radix_number ON insights.devices_unified (radix_device_number);
CREATE INDEX IF NOT EXISTS ix_devices_unified_internal_id ON insights.devices_unified (internal_id);
CREATE INDEX IF NOT EXISTS ix_devices_unified_status ON insights.devices_unified (device_status);
CREATE INDEX IF NOT EXISTS ix_devices_unified_customer ON insights.devices_unified (customer_name);
CREATE INDEX IF NOT EXISTS ix_devices_unified_model ON insights.devices_unified (model_id);

-- ---------------------------------------------------------------------------
-- Devices that could not be confidently matched across systems (manual review).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insights.match_review_queue (
    id                  BIGSERIAL PRIMARY KEY,
    manufacturer_serial VARCHAR(100),
    fleetmgmt_device_id INTEGER,
    radix_serialnumber_id VARCHAR(40),
    reason              VARCHAR(50) NOT NULL,        -- conflict|unmatched|ambiguous_customer|...
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolved            BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_match_review_unresolved ON insights.match_review_queue (resolved) WHERE resolved = FALSE;
