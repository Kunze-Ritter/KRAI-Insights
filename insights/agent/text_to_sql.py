"""
Guarded free-text -> SQL fallback for questions no route covers.

Defence in depth, because we execute model-generated SQL:
  1. sqlglot parse — exactly ONE statement, and it must be a SELECT.
  2. Static check — no DML/DDL/command nodes; every real table is an
     ``insights.vw_*`` view (CTE names exempt); no denylisted functions.
  3. Execution — read-only transaction + statement_timeout + a hard LIMIT,
     with ``search_path`` pinned to ``insights``.
Answers from this path carry a lower trust score than catalog routes.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import pandas as pd
import sqlglot
from sqlalchemy import text
from sqlglot import exp

from insights.agent.routes import AnswerCard
from insights.core.db import insights_engine
from insights.core.logging import get_logger

logger = get_logger(__name__)

_RESULT_LIMIT = 200
_TIMEOUT_MS = 5000

# Functions that can read files, sleep, or reach out of the database.
_DENY_FUNCS = {
    "pg_sleep", "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export", "lo_get", "lo_put", "dblink", "dblink_exec",
    "query_to_xml", "copy", "pg_logical_emit_message", "set_config", "current_setting",
}
# Statement node types that must never appear.
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create,
    exp.Alter, exp.Command, exp.Set, exp.Grant, exp.Copy,
)


@lru_cache(maxsize=1)
def schema_hint() -> str:
    """Compact 'view(col, col, ...)' listing of all insights vw_* views for the prompt."""
    sql = (
        "SELECT table_name, string_agg(column_name, ', ' ORDER BY ordinal_position) AS cols "
        "FROM information_schema.columns "
        "WHERE table_schema = 'insights' AND table_name LIKE 'vw\\_%' "
        "GROUP BY table_name ORDER BY table_name"
    )
    with insights_engine().connect() as conn:
        rows = conn.execute(text(sql)).all()
    return "\n".join(f"{r[0]}({r[1]})" for r in rows)


@lru_cache(maxsize=1)
def _allowed_views() -> frozenset[str]:
    with insights_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT table_name FROM information_schema.views WHERE table_schema='insights'")
        ).all()
    return frozenset(r[0] for r in rows)


def validate(sql: str) -> tuple[bool, str]:
    """Return (ok, reason). Enforces single read-only SELECT over insights.vw_* only."""
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        return False, "leeres SQL"
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except Exception as exc:
        return False, f"SQL nicht parsebar: {exc}"
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return False, "nur genau ein Statement erlaubt"
    stmt = statements[0]
    if not isinstance(stmt, exp.Select):
        return False, "nur SELECT erlaubt"
    if stmt.find(*_FORBIDDEN_NODES) is not None:
        return False, "verändernde Anweisung (DML/DDL) nicht erlaubt"

    cte_names = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}
    allowed = _allowed_views()
    for tbl in stmt.find_all(exp.Table):
        name = (tbl.name or "").lower()
        if name in cte_names:
            continue
        db = (tbl.db or "").lower()
        if db and db != "insights":
            return False, f"nur Schema insights erlaubt (gefunden: {tbl.db})"
        if not name.startswith("vw_") or name not in allowed:
            return False, f"nur freigegebene vw_*-Views erlaubt (gefunden: {tbl.name})"

    for fn in stmt.find_all(exp.Func, exp.Anonymous):
        fname = (fn.name or fn.sql_name() or "").lower()
        if fname in _DENY_FUNCS:
            return False, f"Funktion nicht erlaubt: {fname}"
    return True, "ok"


def run_safe(sql: str) -> pd.DataFrame:
    """Run a pre-validated SELECT read-only, timeout-bounded, and LIMIT-capped."""
    inner = sql.strip().rstrip(";").strip()
    wrapped = f"SELECT * FROM (\n{inner}\n) AS _q LIMIT {_RESULT_LIMIT}"
    with insights_engine().connect() as conn:
        with conn.begin():
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = '{_TIMEOUT_MS}'")
            conn.exec_driver_sql("SET LOCAL search_path = insights")
            return pd.DataFrame(conn.execute(text(wrapped)).mappings().all())


_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)

SQL_SYSTEM = (
    "Du bist ein SQL-Generator für PostgreSQL. Beantworte die Frage mit GENAU EINEM "
    "SELECT-Statement, ausschließlich gegen die unten gelisteten Views im Schema insights. "
    "Nutze nur diese Views und nur die genannten Spalten. KEINE INSERT/UPDATE/DELETE/DDL, "
    "kein Semikolon, keine Erklärung — gib NUR das SQL aus.\n\nVerfügbare Views:\n{schema}"
)


def _extract_sql(content: str) -> str:
    m = _FENCE.search(content or "")
    return (m.group(1) if m else (content or "")).strip()


async def generate_and_run(question: str, client: Any) -> AnswerCard | None:
    """Generate SQL via the LLM, validate + run it. Returns None if it can't be used safely."""
    try:
        message = await client.chat(
            [
                {"role": "system", "content": SQL_SYSTEM.format(schema=schema_hint())},
                {"role": "user", "content": question},
            ]
        )
    except Exception as exc:
        logger.warning("text-to-sql generation failed: %s", exc)
        return None

    sql = _extract_sql(message.get("content", ""))
    ok, reason = validate(sql)
    if not ok:
        logger.info("text-to-sql rejected (%s): %s", reason, sql[:200])
        return None
    try:
        df = run_safe(sql)
    except Exception as exc:
        logger.warning("text-to-sql execution failed: %s", exc)
        return None
    txt = (f"Freitext-Auswertung (automatisch erzeugtes SQL, niedrigeres Vertrauen): "
           f"{len(df)} Zeile(n).")
    return AnswerCard(
        text=txt,
        data=df,
        citation={"quelle": "text-to-sql", "sql": sql, "vertrauen": 0.5, "source_system": "insights"},
    )
