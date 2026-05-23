"""
Regression tests for the warranty / spare-part formula invariants.

These run against the live Insights DB (read-only) and assert the rules that make
a claim submittable — so a future view change can't silently break them. If the
DB is unreachable (e.g. plain CI), the whole module is skipped.
"""

from __future__ import annotations

import pytest
from insights.core.db import insights_engine
from sqlalchemy import text

try:
    with insights_engine().connect() as _c:
        _c.execute(text("SELECT 1"))
    _DB_OK = True
except Exception:
    _DB_OK = False

pytestmark = pytest.mark.skipif(not _DB_OK, reason="Insights DB not reachable")


def _scalar(sql: str) -> int:
    with insights_engine().connect() as c:
        return c.execute(text(sql)).scalar() or 0


# --- Warranty claim invariants ---------------------------------------------
def test_no_claim_is_same_day():
    """A claim cycle must span > 0 days (same-day = artifact, migration 041)."""
    assert _scalar("SELECT count(*) FROM insights.vw_warranty_assessment "
                   "WHERE warranty_class='claim' AND age_days = 0") == 0


def test_claims_within_year_and_under_rated():
    """Every claim: <=365 days, >=100 pages, AND < 70% of rated TONER (coverage-adjusted).

    pct_of_oem is the coverage-adjusted toner yield (migration 043), NOT raw pages —
    a high-coverage customer printing fewer pages is not a warranty case.
    """
    bad = _scalar(
        "SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class='claim' "
        "AND NOT (age_days BETWEEN 1 AND 365 AND pages >= 100 AND rated > 0 AND pct_of_oem < 70)"
    )
    assert bad == 0


def test_negotiation_over_year_under_rated():
    bad = _scalar(
        "SELECT count(*) FROM insights.vw_warranty_assessment WHERE warranty_class='negotiation' "
        "AND NOT (age_days > 365 AND rated > 0 AND pct_of_oem < 70)"
    )
    assert bad == 0


def test_high_coverage_not_a_claim():
    """A cartridge that delivered >= 70% of rated toner (coverage-adjusted) is NOT a claim."""
    bad = _scalar(
        "SELECT count(*) FROM insights.vw_warranty_assessment "
        "WHERE warranty_class IN ('claim', 'negotiation') AND coverage_belegt AND pct_of_oem >= 70"
    )
    assert bad == 0


def test_fehlmeldung_is_flagged():
    """Everything classified 'fehlmeldung' must carry the false-report flag."""
    assert _scalar("SELECT count(*) FROM insights.vw_warranty_assessment "
                   "WHERE warranty_class='fehlmeldung' AND NOT likely_false_report") == 0


def test_lagebericht_single_row_nonnegative():
    with insights_engine().connect() as c:
        rows = c.execute(text("SELECT * FROM insights.vw_lagebericht")).mappings().all()
    assert len(rows) == 1
    r = rows[0]
    for col in ("garantie_claims", "garantie_claims_serial", "verhandlung_kandidaten",
                "ersatzteil_fruehausfaelle", "stille_unter_vertrag", "kunden_abweichung"):
        assert (r[col] or 0) >= 0


def test_residual_value_bounded_by_toner_claims():
    """Residual sum can't exceed the toner-claim count (each residual is <= 1)."""
    with insights_engine().connect() as c:
        r = c.execute(text("SELECT claim_restwert_summe, garantie_claims_toner "
                           "FROM insights.vw_lagebericht")).one()
    restwert, toner_claims = float(r[0] or 0), int(r[1] or 0)
    assert restwert <= toner_claims + 0.5


# --- Spare-part invariants --------------------------------------------------
def test_part_early_failures_min_age():
    """Early failures are real cycles (>= 7 days), never same-incident noise."""
    assert _scalar("SELECT count(*) FROM insights.vw_part_early_failures WHERE standzeit_tage < 7") == 0


def test_part_oem_based_under_threshold():
    """OEM-based early failures ran < 70% of the rated pages."""
    bad = _scalar(
        "SELECT count(*) FROM insights.vw_part_early_failures "
        "WHERE basis = 'OEM-Soll (Seiten)' AND NOT (pct_vom_oem < 70)"
    )
    assert bad == 0
