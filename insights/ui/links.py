"""Links to the GitHub documentation, used for dashboard tooltips/info."""

from __future__ import annotations

DOCS_BASE = "https://github.com/Kunze-Ritter/KRAI-Insights/blob/main/docs"


def doc(page: str, anchor: str = "") -> str:
    """Full GitHub URL to a doc page (optional #anchor)."""
    url = f"{DOCS_BASE}/{page}"
    return f"{url}#{anchor}" if anchor else url
