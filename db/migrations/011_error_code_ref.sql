-- 011_error_code_ref.sql
-- Materialised error-code reference from krai_intelligence.error_codes (extracted
-- from manufacturer service manuals). Powers the technician assistant: look up a
-- service-menu code -> meaning + technician solution + severity, then cross-ref the
-- part-lifetime history. Materialised here to avoid live cross-DB joins at query
-- time. Reference knowledge, no PII.
CREATE TABLE IF NOT EXISTS insights.error_code_ref (
    id                          UUID PRIMARY KEY,        -- = krai_intelligence.error_codes.id
    error_code                  VARCHAR(100),
    manufacturer                VARCHAR(100),            -- resolved from krai_core.manufacturers
    error_description           TEXT,
    solution_technician_text    TEXT,
    severity_level              VARCHAR(30),
    estimated_fix_time_minutes  INTEGER,
    requires_parts              BOOLEAN,
    page_number                 INTEGER,
    confidence_score            NUMERIC(6, 3),
    product_ids                 JSONB,
    source_system               VARCHAR(20) NOT NULL DEFAULT 'krai',
    ingested_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_error_code_ref_code ON insights.error_code_ref (error_code);
CREATE INDEX IF NOT EXISTS ix_error_code_ref_mfr ON insights.error_code_ref (manufacturer);
