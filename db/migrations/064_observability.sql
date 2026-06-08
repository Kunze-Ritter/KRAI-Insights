-- 064_observability.sql
-- Betriebs-Observability: Nightly-Laeufe sichtbar machen + Daten-Freshness pruefbar.
--
-- Problem: Der Nightly-Scheduler (insights/etl/scheduler.py) faengt jeden Schritt-Fehler
-- nur in stdout/Log ab. Ein fehlgeschlagener Lauf ist damit UNSICHTBAR, und veraltete
-- Daten sind im Dashboard nicht von frischen zu unterscheiden. Fuer ein Tool, das
-- Garantie-/Geld-Entscheidungen stuetzt, ist "stille Veraltung" das Hauptrisiko.
--
-- Loesung (drei Bausteine):
--   1) scheduler_runs  — Lauf-Protokoll: je Pipeline-Schritt eine Zeile (Start/Ende/Status/
--                        Ergebnis/Fehler). Geschrieben vom instrumentierten _run_step().
--   2) vw_table_freshness — je Kerntabelle der letzte Daten-Stand (max ingested_at/updated_at)
--                        + erwartete Kadenz + abgeleiteter Status frisch/veraltet/leer.
--   3) vw_etl_status   — der jeweils letzte Lauf je Pipeline (ok-/fehler-Schritte, Fehlerliste)
--                        fuer UI-Banner + Agent.

-- 1) Lauf-Protokoll des Schedulers. run_id buendelt die Schritte eines Pipeline-Laufs.
CREATE TABLE IF NOT EXISTS insights.scheduler_runs (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        uuid        NOT NULL,
    pipeline      text        NOT NULL,             -- daily / weekly
    step          text        NOT NULL,             -- Loader-Name (z. B. fleetmgmt_devices)
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text        NOT NULL DEFAULT 'running',  -- running / ok / failed
    result_json   jsonb,                            -- Rueckgabewert des Loaders (Counts/Dict)
    error         text                              -- Exception-Text bei status='failed'
);
CREATE INDEX IF NOT EXISTS ix_scheduler_runs_pipeline_started
    ON insights.scheduler_runs (pipeline, started_at DESC);
CREATE INDEX IF NOT EXISTS ix_scheduler_runs_run_id
    ON insights.scheduler_runs (run_id);

-- 2) Daten-Freshness je Kerntabelle. Schwellen: daily-Tabellen >36h = veraltet (ein
--    ausgefallener Nightly faellt sofort auf), weekly-Tabellen >8 Tage. Pro Tabelle die
--    passende Zeitstempel-Spalte (devices_unified hat updated_at, der Rest ingested_at).
CREATE OR REPLACE VIEW insights.vw_table_freshness AS
WITH raw AS (
    SELECT 'devices_unified'::text AS tabelle, 'daily'::text AS kadenz, 36 AS max_stunden,
           (SELECT max(updated_at) FROM insights.devices_unified) AS letzter_stand
    UNION ALL SELECT 'vbm_lifecycle_events', 'daily', 36,
           (SELECT max(ingested_at) FROM insights.vbm_lifecycle_events)
    UNION ALL SELECT 'snmp_predictions', 'daily', 36,
           (SELECT max(ingested_at) FROM insights.snmp_predictions)
    UNION ALL SELECT 'error_code_ref', 'daily', 36,
           (SELECT max(ingested_at) FROM insights.error_code_ref)
    UNION ALL SELECT 'model_toner_oem', 'daily', 36,
           (SELECT max(ingested_at) FROM insights.model_toner_oem)
    UNION ALL SELECT 'cost_events', 'weekly', 192,
           (SELECT max(ingested_at) FROM insights.cost_events)
    UNION ALL SELECT 'device_contracts', 'weekly', 192,
           (SELECT max(ingested_at) FROM insights.device_contracts)
)
SELECT tabelle,
       kadenz,
       letzter_stand,
       round((EXTRACT(EPOCH FROM (now() - letzter_stand)) / 3600.0)::numeric, 1) AS alter_stunden,
       max_stunden,
       CASE
           WHEN letzter_stand IS NULL THEN 'leer'
           WHEN now() - letzter_stand > make_interval(hours => max_stunden) THEN 'veraltet'
           ELSE 'frisch'
       END AS status,
       'insights'::text AS source_system
FROM raw;

-- 3) Letzter Lauf je Pipeline aus dem Protokoll. DISTINCT ON liefert die run_id des
--    juengsten Laufs (letzter gestarteter Schritt), danach ueber alle Schritte dieser
--    run_id aggregiert.
CREATE OR REPLACE VIEW insights.vw_etl_status AS
WITH latest AS (
    SELECT DISTINCT ON (pipeline) pipeline, run_id
    FROM insights.scheduler_runs
    ORDER BY pipeline, started_at DESC
)
SELECT l.pipeline,
       l.run_id,
       min(r.started_at) AS lauf_start,
       max(r.finished_at) AS lauf_ende,
       count(*) AS schritte,
       count(*) FILTER (WHERE r.status = 'ok') AS schritte_ok,
       count(*) FILTER (WHERE r.status = 'failed') AS schritte_fehler,
       count(*) FILTER (WHERE r.status = 'running') AS schritte_laufend,
       string_agg(r.step, ', ' ORDER BY r.started_at)
           FILTER (WHERE r.status = 'failed') AS fehler_schritte,
       'insights'::text AS source_system
FROM latest l
JOIN insights.scheduler_runs r ON r.run_id = l.run_id
GROUP BY l.pipeline, l.run_id;
