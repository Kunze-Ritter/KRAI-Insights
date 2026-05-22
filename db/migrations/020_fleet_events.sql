-- 020_fleet_events.sql
-- Service-quality layer from FleetMgmt ACCEVENTHISTORY (836k printer/SNMP alerts).
-- No PII (ClearedBy/EventNote/CecData excluded by the extractor). Open alert =
-- cleared_at IS NULL. Views focus on the last 365 days for actionable signal.
CREATE TABLE IF NOT EXISTS insights.fleet_events (
    source_pkid          bigint PRIMARY KEY,
    fleetmgmt_device_id  integer NOT NULL,
    severity             smallint,
    alert_code           integer,
    alert_group          integer,
    printer_error        integer,
    message              text,
    alert_description    text,
    page_count_at_event  integer,
    contract_id          integer,
    raised_at            timestamptz,
    cleared_at           timestamptz,
    source_system        varchar NOT NULL DEFAULT 'fleetmgmt',
    ingested_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fleet_events_device ON insights.fleet_events (fleetmgmt_device_id);
CREATE INDEX IF NOT EXISTS ix_fleet_events_raised ON insights.fleet_events (raised_at);
CREATE INDEX IF NOT EXISTS ix_fleet_events_code   ON insights.fleet_events (alert_code);
CREATE INDEX IF NOT EXISTS ix_fleet_events_open   ON insights.fleet_events (fleetmgmt_device_id) WHERE cleared_at IS NULL;

-- (a) Problem devices / sensor-spam: abnormal event volume in the last 365 days.
--     A flapping sensor or recurring fault produces hundreds–thousands of events.
--     >= 1000/yr (~3/day) = sensor_spam; >= 365/yr (~1/day) = erhoeht.
CREATE OR REPLACE VIEW insights.vw_problem_devices AS
WITH ev AS (
    SELECT
        e.fleetmgmt_device_id,
        count(*)                                              AS events_365d,
        count(*) FILTER (WHERE e.cleared_at IS NULL)          AS offen,
        count(DISTINCT e.alert_code)                          AS distinct_codes,
        max(e.raised_at)                                      AS last_event_at,
        mode() WITHIN GROUP (ORDER BY e.alert_code)           AS top_code
    FROM insights.fleet_events e
    WHERE e.raised_at >= now() - INTERVAL '365 days'
    GROUP BY e.fleetmgmt_device_id
)
SELECT
    d.customer_name, d.customer_city, d.manufacturer_serial AS device_serial,
    d.radix_device_number, d.manufacturer_canonical, d.model_display, d.device_status,
    ev.events_365d, ev.offen AS offene_alarme, ev.distinct_codes AS verschiedene_codes,
    ev.top_code AS haeufigster_code, ev.last_event_at AS letzter_alarm,
    CASE WHEN ev.events_365d >= 1000 THEN 'sensor_spam'
         WHEN ev.events_365d >= 365  THEN 'erhoeht'
         ELSE 'normal' END AS einstufung,
    'fleetmgmt'::varchar AS source_system
FROM ev
LEFT JOIN insights.devices_unified d ON d.fleetmgmt_device_id = ev.fleetmgmt_device_id
WHERE ev.events_365d >= 365
ORDER BY ev.events_365d DESC;

-- (b) Problem models: which models are noisiest per device (last 365 days).
--     Normalised by device count so a large fleet doesn't dominate; >= 5 devices.
CREATE OR REPLACE VIEW insights.vw_problem_models AS
WITH ev AS (
    SELECT d.manufacturer_canonical, d.model_display,
           count(DISTINCT d.fleetmgmt_device_id) AS geraete,
           count(*)                              AS events_365d
    FROM insights.fleet_events e
    JOIN insights.devices_unified d ON d.fleetmgmt_device_id = e.fleetmgmt_device_id
    WHERE e.raised_at >= now() - INTERVAL '365 days'
      AND d.model_display IS NOT NULL
    GROUP BY d.manufacturer_canonical, d.model_display
)
SELECT
    manufacturer_canonical AS hersteller, model_display AS modell,
    geraete, events_365d AS alarme_gesamt,
    round(events_365d::numeric / NULLIF(geraete, 0), 1) AS alarme_pro_geraet,
    'fleetmgmt'::varchar AS source_system
FROM ev
WHERE geraete >= 5
ORDER BY alarme_pro_geraet DESC;

-- (c) Top alert codes fleet-wide (last 365 days), with a representative text and
--     how many devices are affected -> systemic issues vs one noisy device.
CREATE OR REPLACE VIEW insights.vw_top_alert_codes AS
SELECT
    e.alert_code,
    mode() WITHIN GROUP (
        ORDER BY COALESCE(NULLIF(e.alert_description, ''), NULLIF(e.message, ''))
    ) AS bedeutung,
    count(*)                              AS alarme,
    count(DISTINCT e.fleetmgmt_device_id) AS betroffene_geraete,
    max(e.severity)                       AS max_severity,
    'fleetmgmt'::varchar AS source_system
FROM insights.fleet_events e
WHERE e.raised_at >= now() - INTERVAL '365 days'
GROUP BY e.alert_code
ORDER BY alarme DESC;

-- (d) Open events aging: unresolved alerts (cleared_at IS NULL), oldest first,
--     with the device + customer for follow-up.
CREATE OR REPLACE VIEW insights.vw_open_events_aging AS
SELECT
    d.customer_name, d.customer_city, d.manufacturer_serial AS device_serial,
    d.radix_device_number, d.manufacturer_canonical, d.model_display, d.device_status,
    e.alert_code, COALESCE(NULLIF(e.alert_description, ''), NULLIF(e.message, '')) AS bedeutung,
    e.severity, e.raised_at AS offen_seit,
    (now()::date - e.raised_at::date) AS offen_tage,
    'fleetmgmt'::varchar AS source_system
FROM insights.fleet_events e
LEFT JOIN insights.devices_unified d ON d.fleetmgmt_device_id = e.fleetmgmt_device_id
WHERE e.cleared_at IS NULL
ORDER BY e.raised_at ASC;
