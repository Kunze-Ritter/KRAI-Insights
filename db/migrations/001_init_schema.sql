-- 001_init_schema.sql
-- Foundation: the `insights` schema + required extensions.
-- Analytics tables (devices_unified, vbm_lifecycle_events, warranty_claims,
-- cost_events, profitability_snapshots) follow in 002-005 (insights_schema todo).

CREATE SCHEMA IF NOT EXISTS insights;

-- gen_random_uuid() for UUID primary keys used across the analytics tables.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
