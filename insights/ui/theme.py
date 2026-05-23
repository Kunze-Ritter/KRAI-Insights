"""
Gemeinsames UI-Theme und Plotly-Diagramm-Helfer (cleaner shadcn/„bklit"-Look).

Eine Import-Fläche für alle Views:

    from insights.ui.theme import setup_page, render_chart, bar, scatter, donut, line

`setup_page(title, caption)` steht oben in jeder View: injiziert das CSS (KPI-Kacheln
als Karten, runde Ecken, dezentere Divider) und setzt einen einheitlichen Seitenkopf.
Die Chart-Helfer geben eine Plotly-Figur zurück; `render_chart()` zeichnet sie
einheitlich (transparenter Hintergrund, kein Modebar). Light/Dark wird über
`st.context.theme.type` erkannt — wir steuern die Diagramm-Farben selbst, damit die
semantischen Farben (Toner-CMYK, über/unter Soll) in beiden Modi stimmen.

Hinweis: `st.set_page_config` bleibt ausschließlich in `app.py` (darf nur einmal
aufgerufen werden) — `setup_page` ruft es bewusst NICHT auf.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

# --- Farbpalette (semantisch; Mitteltöne, die auf Hell UND Dunkel lesbar sind) ---
ACCENT = "#6366F1"   # Indigo — entspricht primaryColor in .streamlit/config.toml
POS = "#16A34A"      # gut / über Soll (grün)
NEG = "#DC2626"      # schlecht / unter Soll (rot)
WARN = "#F59E0B"     # Schwelle / Referenzlinie (amber)
MUTED = "#94A3B8"    # neutral (slate-400)
# Diskrete Sequenz für kategoriale Aufschlüsselungen.
SEQ = [ACCENT, "#06B6D4", "#F59E0B", "#10B981", "#EC4899", "#8B5CF6", "#64748B"]
# Toner-Farben realitätsnah (Material-Verlauf je Gerät). Schwarz aufgehellt zu zinc-600,
# Gelb abgedunkelt — sonst auf weißem Hintergrund nicht lesbar.
TONER = {"black": "#52525B", "cyan": "#06B6D4", "magenta": "#EC4899", "yellow": "#CA8A04"}

_FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif'

# --- CSS: klein halten, jeden Selektor kommentieren (interne Klassen sind fragil) ---
# Wir nutzen halbtransparente Neutraltöne statt fixer Hex-Werte, damit dieselbe Regel
# in Hell und Dunkel funktioniert (kein theme-var-Abhängigkeit nötig).
CSS = """
<style>
/* Mehr Luft im Hauptbereich, Inhalte nicht ganz an den Rand */
.block-container { padding-top: 2.6rem; padding-bottom: 4rem; max-width: 1400px; }

/* KPI-Metriken als Karten (data-testid ist über Releases am stabilsten) */
[data-testid="stMetric"] {
    background: rgba(128,128,140,0.07);
    border: 1px solid rgba(128,128,140,0.22);
    border-radius: 12px;
    padding: 14px 16px 12px 16px;
}
[data-testid="stMetricLabel"] { opacity: 0.72; }
[data-testid="stMetricValue"] { font-weight: 700; letter-spacing: -0.01em; }

/* Divider dezenter */
[data-testid="stMarkdownContainer"] hr, hr { opacity: 0.35; }

/* Tabs etwas luftiger (Akzentfarbe der aktiven Tab kommt aus config.toml) */
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
</style>
"""


def inject_css() -> None:
    """Injiziert das gemeinsame CSS. Idempotent — billig bei jedem Rerun."""
    st.markdown(CSS, unsafe_allow_html=True)


def setup_page(title: str, caption: str | None = None) -> None:
    """Seiten-Setup: CSS + einheitlicher Kopf. Erster Streamlit-Aufruf jeder View.

    `title` enthält i. d. R. bereits ein Emoji (z. B. "📈 Deckung & Kalkulation").
    Weitere Hinweis-/Doku-Zeilen folgen in der View als zusätzliche `st.caption`.
    """
    inject_css()
    st.title(title)
    if caption:
        st.caption(caption)


def _is_dark() -> bool:
    """Aktives Theme erkennen (Nutzer kann zur Laufzeit umschalten). Fallback: hell."""
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def _style(fig, *, title: str | None = None, height: int | None = None):
    """Gemeinsames Layout: transparenter Hintergrund, Light/Dark-Basistemplate, schmale Ränder."""
    dark = _is_dark()
    fig.update_layout(
        template="plotly_dark" if dark else "plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_FONT, size=13),
        margin=dict(l=10, r=16, t=46 if title else 12, b=10),
        height=height,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title_text=""),
        hoverlabel=dict(font_size=12),
    )
    if title:
        fig.update_layout(title=dict(text=title, x=0, xanchor="left", font=dict(size=15)))
    fig.update_xaxes(zeroline=False)
    fig.update_yaxes(zeroline=False)
    return fig


def render_chart(fig, **kwargs) -> None:
    """Zeichnet eine Plotly-Figur einheitlich (volle Breite, kein Modebar).

    `theme=None`, damit unsere selbst gesetzten Farben erhalten bleiben (siehe Modulkopf).
    """
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False}, **kwargs)


def bar(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    orientation: str = "h",
    color: str | None = None,
    color_map: dict | None = None,
    sequence: list | None = None,
    single_color: str | None = None,
    ref: float | None = None,
    ref_label: str | None = None,
    barmode: str | None = None,
    top: int | None = None,
    order: str = "desc",
    sort: bool = True,
    title: str | None = None,
    labels: dict | None = None,
    hover_data: list | None = None,
):
    """Vorgestyltes Balkendiagramm.

    - `orientation="h"` (Default): Kategorie auf der y-Achse, Messwert auf x.
    - `top`/`order`: Top-N nach Messwert (desc = größte oben, asc = kleinste oben).
    - `sort=False`: Daten nicht umsortieren (z. B. bei vorab aggregierten/gemolzenen Frames).
    - `ref`: Referenzlinie auf der Messwert-Achse (6 %/100 %/5 % …).
    """
    measure = x if orientation == "h" else y
    data = df
    asc = order == "asc"
    if sort:
        data = df.sort_values(measure, ascending=asc, na_position="last")
        if top:
            data = data.head(top)

    extra: dict = {}
    if color:
        extra["color"] = color
        if color_map:
            extra["color_discrete_map"] = color_map
        else:
            extra["color_discrete_sequence"] = sequence or SEQ
    else:
        extra["color_discrete_sequence"] = [single_color or ACCENT]

    fig = px.bar(
        data, x=x, y=y, orientation=orientation,
        labels=labels or {}, hover_data=hover_data, **extra,
    )
    if barmode:
        fig.update_layout(barmode=barmode)
    if orientation == "h":
        # größter Balken oben (bzw. kleinster oben bei order="asc")
        fig.update_yaxes(categoryorder="total descending" if asc else "total ascending")
    if ref is not None:
        if orientation == "h":
            fig.add_vline(x=ref, line_dash="dash", line_color=WARN,
                          annotation_text=ref_label, annotation_position="top")
        else:
            fig.add_hline(y=ref, line_dash="dash", line_color=WARN,
                          annotation_text=ref_label, annotation_position="top left")
    return _style(fig, title=title)


def scatter(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    color: str | None = None,
    ref_x: float | None = None,
    ref_y: float | None = None,
    ref_label: str | None = None,
    log_x: bool = False,
    title: str | None = None,
    labels: dict | None = None,
    hover_data: list | None = None,
):
    """Vorgestyltes Streudiagramm mit optionalen Referenzlinien (für die Deckungs-Tabs)."""
    fig = px.scatter(
        df, x=x, y=y, color=color,
        color_discrete_sequence=SEQ if color else [ACCENT],
        log_x=log_x, labels=labels or {}, hover_data=hover_data, opacity=0.6,
    )
    fig.update_traces(marker=dict(size=8, line=dict(width=0)))
    if ref_y is not None:
        fig.add_hline(y=ref_y, line_dash="dash", line_color=WARN,
                      annotation_text=ref_label, annotation_position="top left")
    if ref_x is not None:
        fig.add_vline(x=ref_x, line_dash="dash", line_color=WARN,
                      annotation_text=ref_label, annotation_position="top")
    return _style(fig, title=title)


def donut(
    df: pd.DataFrame,
    *,
    names: str,
    values: str,
    title: str | None = None,
    color_map: dict | None = None,
    sequence: list | None = None,
):
    """Vorgestylter Donut (Anteile, z. B. Flottenstatus)."""
    fig = px.pie(
        df, names=names, values=values, hole=0.58,
        color=names if color_map else None,
        color_discrete_map=color_map,
        color_discrete_sequence=sequence or SEQ,
    )
    fig.update_traces(textposition="inside", textinfo="percent",
                      marker=dict(line=dict(width=1, color="rgba(0,0,0,0)")))
    return _style(fig, title=title, height=340)


def line(
    df: pd.DataFrame,
    *,
    x: str,
    y: str,
    color: str | None = None,
    color_map: dict | None = None,
    ref: float | None = None,
    ref_label: str | None = None,
    title: str | None = None,
    labels: dict | None = None,
    markers: bool = True,
):
    """Vorgestyltes Liniendiagramm (z. B. Material-Verlauf je Gerät über die Zeit)."""
    extra: dict = {}
    if color:
        extra["color"] = color
        if color_map:
            extra["color_discrete_map"] = color_map
        else:
            extra["color_discrete_sequence"] = SEQ
    fig = px.line(df, x=x, y=y, markers=markers, labels=labels or {}, **extra)
    if ref is not None:
        fig.add_hline(y=ref, line_dash="dash", line_color=WARN,
                      annotation_text=ref_label, annotation_position="top left")
    return _style(fig, title=title)
