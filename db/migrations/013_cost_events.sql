-- 013_cost_events.sql
-- Material and labour cost lines from Radix service activities. Material price
-- comes from the spare-part record (`price`); labour stores the duration (a €
-- rate is a config input, not in the payload). `invoicing_type` distinguishes
-- contract-covered ("VER - Vertrag") from billable ("AUF - Aufwand") work, and
-- `to_billed` flags billable labour — both central to cost / warranty analysis.
CREATE TABLE IF NOT EXISTS insights.cost_events (
    id                  BIGSERIAL PRIMARY KEY,
    source_id           VARCHAR(40) NOT NULL,   -- Radix sparepart.id / time.id
    cost_type           VARCHAR(10) NOT NULL,   -- 'material' | 'labor'
    radix_activity_id   VARCHAR(40),
    radix_ticket_id     VARCHAR(40),
    radix_customer_id   VARCHAR(40),
    device_serial       VARCHAR(100),           -- material: serialnumberNumberManufactorParent
    occurred_at         TIMESTAMPTZ,
    description         TEXT,
    article_code        VARCHAR(100),
    quantity            NUMERIC(12, 3),
    unit_price          NUMERIC(12, 3),         -- € per unit as charged on the activity
    total_eur           NUMERIC(14, 2),
    duration_minutes    NUMERIC(10, 2),         -- labour
    employee_id         VARCHAR(40),            -- pseudonymous; no name
    invoicing_type      VARCHAR(60),            -- "VER - Vertrag" | "AUF - Aufwand" | ...
    to_billed           BOOLEAN,
    source_system       VARCHAR(20) NOT NULL DEFAULT 'radix',
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, cost_type)
);
CREATE INDEX IF NOT EXISTS ix_cost_events_customer ON insights.cost_events (radix_customer_id);
CREATE INDEX IF NOT EXISTS ix_cost_events_serial ON insights.cost_events (device_serial) WHERE device_serial IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_cost_events_type ON insights.cost_events (cost_type);
CREATE INDEX IF NOT EXISTS ix_cost_events_activity ON insights.cost_events (radix_activity_id);
