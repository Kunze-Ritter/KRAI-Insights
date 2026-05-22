"""
Nightly ETL scheduler — keeps the Insights cache fresh from the read-only sources.

Opt-in: runs as the `scheduler` compose service (profile `scheduler`), separate
from the Streamlit app. Each step is isolated (one failure does not abort the
rest) and logged. Cadence (UTC) is overridable via env; sources stay read-only.

    python -m insights.etl.scheduler                 # run forever on the schedule
    python -m insights.etl.scheduler --once daily     # run the daily pipeline now
    python -m insights.etl.scheduler --once weekly     # run the weekly pipeline now
    python -m insights.etl.scheduler --once all        # run everything now

Cadence defaults: daily 02:00 UTC (core freshness), weekly Sun 03:00 UTC
(per-device contract/shipping crawls + the heavy cost crawl). Override with
SCHED_DAILY_HOUR / SCHED_WEEKLY_HOUR / SCHED_WEEKLY_DOW.
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable
from typing import Any

from insights.core.logging import get_logger
from insights.etl import load

logger = get_logger("scheduler")


def _run_step(name: str, fn: Callable[[], Any]) -> None:
    """Run one ETL step, isolating + logging failures so the pipeline continues."""
    start = time.monotonic()
    logger.info("step START: %s", name)
    try:
        result = fn()
        logger.info("step OK: %s (%.1fs) -> %s", name, time.monotonic() - start, result)
    except Exception:
        logger.exception("step FAILED: %s (%.1fs) — continuing", name, time.monotonic() - start)


def daily_refresh() -> None:
    """Freshness-critical loads, in dependency order (devices first)."""
    logger.info("=== daily refresh START ===")
    _run_step("fleetmgmt_devices", load.load_fleetmgmt_devices)
    _run_step("radix_enrich", load.enrich_devices_from_radix)
    _run_step("radix_customers", load.load_radix_customers)
    _run_step("model_catalog", load.seed_model_catalog)
    _run_step("snmp_predictions", load.load_snmp_predictions)
    _run_step("fleet_events", load.load_events)
    _run_step("vbm_lifecycle", load.load_vbm_lifecycle)
    _run_step("error_codes", load.load_error_codes)
    logger.info("=== daily refresh DONE ===")


def weekly_refresh() -> None:
    """Heavier per-device / per-customer Radix crawls."""
    logger.info("=== weekly refresh START ===")
    _run_step("contracts", load.enrich_contracts_from_radix)
    _run_step("shipping_addresses", load.load_shipping_addresses)
    _run_step("costs", load.crawl_costs)
    logger.info("=== weekly refresh DONE ===")


def _serve() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    daily_hour = int(os.getenv("SCHED_DAILY_HOUR", "2"))
    weekly_hour = int(os.getenv("SCHED_WEEKLY_HOUR", "3"))
    weekly_dow = os.getenv("SCHED_WEEKLY_DOW", "sun")

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
    if args.once in ("daily", "all"):
        daily_refresh()
    if args.once in ("weekly", "all"):
        weekly_refresh()
    if not args.once:
        _serve()
