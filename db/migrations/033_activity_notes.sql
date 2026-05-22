-- 033_activity_notes.sql
-- Diagnostic ticket/activity free-text from Radix — the "Ausführungsbeschreibung" /
-- call log: what was wrong, what fixed it, which technician. Kept for the
-- spare-part/warranty learning AND as a technician knowledge base.
-- PII policy (user decision): OWN technicians' names/initials are KEPT (useful);
-- THIRD-PARTY customer contact names + emails are pseudonymised on load
-- (insights.core.pii.pseudonymize_contacts -> "[Kontakt]" / "[email]").
CREATE TABLE IF NOT EXISTS insights.activity_notes (
    radix_activity_id VARCHAR(40) PRIMARY KEY,
    radix_ticket_id   VARCHAR(40),
    radix_customer_id VARCHAR(40),
    activity_date     DATE,
    activity_type     VARCHAR(60),
    state             VARCHAR(60),
    problem_text      TEXT,   -- ticketDescription (pseudonymised)
    technik_text      TEXT,   -- technicalDescription (pseudonymised)
    verlauf_text      TEXT,   -- customerDescription / call log (pseudonymised)
    source_system     VARCHAR NOT NULL DEFAULT 'radix',
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_activity_notes_ticket ON insights.activity_notes (radix_ticket_id);
CREATE INDEX IF NOT EXISTS ix_activity_notes_customer ON insights.activity_notes (radix_customer_id);

-- Notes joined to a device (via the activity's spare parts in cost_events) — the
-- searchable ticket history per device/model. One row per activity (first device).
CREATE OR REPLACE VIEW insights.vw_ticket_notes AS
SELECT DISTINCT ON (an.radix_activity_id)
    an.radix_activity_id, an.radix_ticket_id, an.activity_date, an.activity_type, an.state,
    ce.device_serial, d.manufacturer_canonical, d.model_display, d.customer_name,
    an.problem_text, an.technik_text, an.verlauf_text,
    'radix+fleetmgmt'::varchar AS source_system
FROM insights.activity_notes an
LEFT JOIN insights.cost_events ce ON ce.radix_activity_id = an.radix_activity_id
LEFT JOIN insights.devices_unified d ON d.manufacturer_serial = ce.device_serial
ORDER BY an.radix_activity_id, ce.device_serial NULLS LAST;
