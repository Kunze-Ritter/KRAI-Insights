"""
KRAI extractor — reads reference/enrichment data from the KRAI PostgreSQL source.

READ-ONLY. Primary value is the document-AI knowledge in `krai_intelligence`
(error codes from service manuals) + the `krai_core` product/manufacturer master.
`krai_pm` itself is mostly empty (warranty/lifecycle tables = 0 rows), so warranty
is synthesised in insights rather than imported from here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy import text

from insights.core.config import get_settings
from insights.core.db import krai_pg_engine
from insights.core.logging import get_logger

logger = get_logger(__name__)

_ERROR_CODES_SQL = """
SELECT
    ec.id,
    ec.error_code,
    m.name                       AS manufacturer,
    ec.error_description,
    ec.solution_technician_text,
    ec.severity_level,
    ec.estimated_fix_time_minutes,
    ec.requires_parts,
    ec.page_number,
    ec.confidence_score,
    ec.product_ids
FROM krai_intelligence.error_codes ec
LEFT JOIN krai_core.manufacturers m ON m.id = ec.manufacturer_id
"""


def fetch_error_codes(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield error-code reference rows (read-only) for the technician assistant.

    `product_ids` (a uuid array in KRAI) is serialised to a JSON string for the
    Insights `jsonb` column.
    """
    sql = _ERROR_CODES_SQL + (" LIMIT :lim" if limit else "")
    with krai_pg_engine().connect() as conn:
        for row in conn.execute(text(sql), {"lim": limit} if limit else {}).mappings():
            rec = dict(row)
            pids = rec.get("product_ids")
            rec["product_ids"] = json.dumps([str(x) for x in pids]) if pids else None
            yield rec


_PART_LIFETIMES_SQL = """
SELECT
    m.name                     AS manufacturer,
    pl.part_category,
    pl.part_number,
    pl.nominal_lifetime_pages,
    pl.color_channel,
    pl.metadata->>'model_family' AS model_family,
    pl.source
FROM krai_pm.part_lifetimes pl
LEFT JOIN krai_core.manufacturers m ON m.id = pl.manufacturer_id
WHERE pl.nominal_lifetime_pages IS NOT NULL
"""


def fetch_part_lifetimes(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield OEM nominal part lifetimes (pages) from krai_pm.part_lifetimes (read-only).

    These are manufacturer-rated lifetimes for toner AND spare parts (drum, fuser,
    transfer belt, rollers, …) — currently Konica Minolta (imported from a KM Excel).
    The basis for OEM-Soll vs. real spare-part lifetime (like toner yield).
    """
    sql = _PART_LIFETIMES_SQL + (" LIMIT :lim" if limit else "")
    with krai_pg_engine().connect() as conn:
        for row in conn.execute(text(sql), {"lim": limit} if limit else {}).mappings():
            yield dict(row)


def fetch_part_warranty_events(limit: int | None = None) -> Iterator[dict[str, Any]]:
    """Yield rows from krai_pm.part_warranty_events (read-only).

    TODO(extractors): finalise column selection and join to device_lifecycle for
    serials; feed insights.warranty_claims in Phase 3.
    """
    schema = get_settings().krai_pg_schema
    sql = f"SELECT * FROM {schema}.part_warranty_events"
    if limit:
        sql += " LIMIT :lim"
    with krai_pg_engine().connect() as conn:
        result = conn.execute(text(sql), {"lim": limit} if limit else {})
        for row in result.mappings():
            yield dict(row)


def ping() -> bool:
    """Lightweight connectivity check against the KRAI PostgreSQL source."""
    with krai_pg_engine().connect() as conn:
        return conn.execute(text("SELECT 1")).scalar() == 1
