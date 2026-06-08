"""
Nightly ETL scheduler — keeps the Insights cache fresh from the read-only sources.

Opt-in: runs as the `scheduler` compose service (profile `scheduler`), separate
from the Streamlit app. Each step is isolated (one failure does not abort the
rest), time-boxed, and logged. Every step is additionally recorded in
``insights.scheduler_runs`` so a failed/stale nightly is VISIBLE (UI banner via
``vw_etl_status`` / ``vw_table_freshness``, see migration 064) instead of only
buried in stdout. Cadence (UTC) is overridable via env; sources stay read-only.

    python -m insights.etl.scheduler                 # run forever on the schedule
    python -m insights.etl.scheduler --once daily     # run the daily pipeline now
    python -m insights.etl.scheduler --once weekly     # run the weekly pipeline now
    python -m insights.etl.scheduler --once all        # run everything now

Cadence defaults: daily 02:00 UTC (core freshness), weekly Sun 03:00 UTC
(per-device contract/shipping crawls + the heavy cost crawl). Override with
SCHED_DAILY_HOUR / SCHED_WEEKLY_HOUR / SCHED_WEEKLY_DOW.

Env (all optional):
    SCHED_STEP_TIMEOUT_SEC   per-step watchdog in seconds (default 3600); a hung
                             crawl is marked failed='timeout' so it cannot block
                             the rest of the night.
    SCHED_ALERT_WEBHOOK      if set, a failed pipeline POSTs a JSON summary here.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any
from urllib import request as urlrequest

from sqlalchemy import text

from insights.core.db import insights_engine
from insights.core.logging import get_logger
from insights.etl import load

logger = get_logger("scheduler")

_STEP_TIMEOUT_SEC = int(os.getenv("SCHED_STEP_TIMEOUT_SEC", "3600"))


def _record_start(run_id: str, pipeline: str, step: str) -> int | None:
    """Insert a 'running' row for this step; return its id (None if the log write fails)."""
    try:
        with insights_engine().begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO insights.scheduler_runs (run_id, pipeline, step, status) "
                    "VALUES (:r, :p, :s, 'running') RETURNING id"
                ),
                {"r": run_id, "p": pipeline, "s": step},
            ).first()
            return int(row[0]) if row else None
    except Exception:
        logger.exception("could not record step start: %s/%s", pipeline, step)
        return None


def _record_finish(row_id: int | None, status: str, result: Any = None, error: str | None = None) -> None:
    """Close out a step row with its final status + serialized result/error."""
    if row_id is None:
        return
    try:
        result_json = json.dumps(result, default=str) if result is not None else None
    except (TypeError, ValueError):
        result_json = json.dumps(str(result))
    try:
        with insights_engine().begin() as conn:
            conn.execute(
                text(
                    "UPDATE insights.scheduler_runs "
                    "SET status = :st, finished_at = now(), result_json = CAST(:rj AS jsonb), error = :err "
                    "WHERE id = :id"
                ),
                {"st": status, "rj": result_json, "err": error, "id": row_id},
            )
    except Exception:
        logger.exception("could not record step finish: id=%s", row_id)


def _run_step(run_id: str, pipeline: str, name: str, fn: Callable[[], Any]) -> bool:
    """Run one ETL step time-boxed + recorded; isolate failures so the pipeline continues.

    Returns True on success, False on failure/timeout. The step is protected by a
    watchdog (SCHED_STEP_TIMEOUT_SEC): on timeout we mark it failed and move on — a
    single hung Radix crawl must not block the rest of the nightly.
    """
    start = time.monotonic()
    logger.info("step START: %s", name)
    row_id = _record_start(run_id, pipeline, name)
    # NICHT `with ThreadPoolExecutor()` — dessen __exit__ ruft shutdown(wait=True) und würde
    # bei einem Timeout doch auf den hängenden Thread warten (Watchdog wirkungslos). Explizit
    # shutdown(wait=False), damit die Pipeline sofort weiterläuft; der verwaiste Thread läuft
    # im Hintergrund aus (in Python nicht abbrechbar), blockiert die Nacht aber nicht.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        result = pool.submit(fn).result(timeout=_STEP_TIMEOUT_SEC)
        logger.info("step OK: %s (%.1fs) -> %s", name, time.monotonic() - start, result)
        _record_finish(row_id, "ok", result=result)
        return True
    except FutureTimeout:
        logger.error("step TIMEOUT: %s (>%ds) — continuing", name, _STEP_TIMEOUT_SEC)
        _record_finish(row_id, "failed", error=f"timeout after {_STEP_TIMEOUT_SEC}s")
        return False
    except Exception as exc:
        logger.exception("step FAILED: %s (%.1fs) — continuing", name, time.monotonic() - start)
        _record_finish(row_id, "failed", error=str(exc))
        return False
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _alert_if_failed(pipeline: str, run_id: str, failed: list[str]) -> None:
    """Best-effort POST a failure summary to SCHED_ALERT_WEBHOOK (no-op if unset)."""
    if not failed:
        return
    webhook = os.getenv("SCHED_ALERT_WEBHOOK", "").strip()
    if not webhook:
        return
    payload = json.dumps({
        "text": f"⚠️ Insights-ETL: Pipeline '{pipeline}' mit {len(failed)} fehlgeschlagenen "
                f"Schritt(en): {', '.join(failed)}",
        "pipeline": pipeline,
        "run_id": run_id,
        "failed_steps": failed,
    }).encode("utf-8")
    try:
        req = urlrequest.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
        urlrequest.urlopen(req, timeout=15)  # operator-supplied internal webhook
        logger.info("failure alert posted for pipeline %s", pipeline)
    except Exception as exc:
        logger.warning("failure alert could not be posted: %s", exc)


def daily_refresh() -> None:
    """Freshness-critical loads, in dependency order (devices first)."""
    run_id = str(uuid.uuid4())
    logger.info("=== daily refresh START (run %s) ===", run_id)
    steps: list[tuple[str, Callable[[], Any]]] = [
        ("fleetmgmt_devices", load.load_fleetmgmt_devices),
        ("radix_enrich", load.enrich_devices_from_radix),
        ("radix_customers", load.load_radix_customers),
        ("model_catalog", load.seed_model_catalog),
        ("snmp_predictions", load.load_snmp_predictions),
        ("counter_daily", load.load_counter_daily),
        ("fleet_events", load.load_events),
        ("vbm_lifecycle", load.load_vbm_lifecycle),
        ("error_codes", load.load_error_codes),
        ("technician_aliases", load.load_technician_aliases),
        ("part_lifetimes_oem", load.load_part_lifetimes),
        # Modell-Toner-Soll NACH vbm_lifecycle + part_lifetimes neu materialisieren, sonst
        # veraltet der OEM-Soll-Backfill (Garantie/Yield, Migration 062/063) nach jedem Nightly.
        ("model_toner_oem", load.refresh_model_toner_oem),
    ]
    # Opt-in: nächtliches pg_dump-Backup (nur wenn aktiviert + pg_dump im Image vorhanden),
    # damit Deployments ohne postgresql-client nicht jede Nacht einen Fehlschritt melden.
    if os.getenv("INSIGHTS_BACKUP_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        from scripts.backup_insights_db import run_backup
        steps.append(("pg_dump_backup", run_backup))
    failed = [name for name, fn in steps if not _run_step(run_id, "daily", name, fn)]
    _alert_if_failed("daily", run_id, failed)
    logger.info("=== daily refresh DONE (run %s, %d Fehler) ===", run_id, len(failed))


def weekly_refresh() -> None:
    """Heavier per-device / per-customer Radix crawls."""
    run_id = str(uuid.uuid4())
    logger.info("=== weekly refresh START (run %s) ===", run_id)
    steps: list[tuple[str, Callable[[], Any]]] = [
        ("contracts", load.enrich_contracts_from_radix),
        ("shipping_addresses", load.load_shipping_addresses),
        ("costs", load.crawl_costs),
        ("ticket_notes", load.crawl_ticket_notes),
    ]
    failed = [name for name, fn in steps if not _run_step(run_id, "weekly", name, fn)]
    _alert_if_failed("weekly", run_id, failed)
    logger.info("=== weekly refresh DONE (run %s, %d Fehler) ===", run_id, len(failed))


def _serve() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    daily_hour = int(os.getenv("SCHED_DAILY_HOUR", "2"))
    weekly_hour = int(os.getenv("SCHED_WEEKLY_HOUR", "3"))
    weekly_dow = os.getenv("SCHED_WEEKLY_DOW", "sun")

    from scripts.env_check import check_env
    check_env()
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(daily_refresh, CronTrigger(hour=daily_hour, minute=0),
                  id="daily_refresh", max_instances=1, coalesce=True)
    sched.add_job(weekly_refresh, CronTrigger(day_of_week=weekly_dow, hour=weekly_hour, minute=0),
                  id="weekly_refresh", max_instances=1, coalesce=True)
    logger.info("scheduler up (UTC): daily %02d:00, weekly %s %02d:00", daily_hour, weekly_dow, weekly_hour)
    sched.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insights ETL scheduler")
    parser.add_argument("--once", choices=["daily", "weekly", "all"],
                        help="run a pipeline immediately and exit (no scheduling)")
    args = parser.parse_args()
    from scripts.env_check import check_env
    check_env()  # nicht-fatal: warnt vor leeren Quellen-Credentials, bevor das ETL still leer läuft
    if args.once in ("daily", "all"):
        daily_refresh()
    if args.once in ("weekly", "all"):
        weekly_refresh()
    if not args.once:
        _serve()
