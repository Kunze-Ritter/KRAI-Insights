"""
VBM-Crawler-Extractor — liest das JSON-Output des Schwester-Repos KRAI-Crawler-VBM.

Der VBM-Crawler (`C:\\Github\\KRAI-Crawler-VBM`) schreibt fuer jedes auf den
Hersteller-Websites gefundene Verbrauchsmaterial eine JSON-Datei nach
`output/<vendor>/supplies/*.json` plus eine konsolidierte
`output/supplies-master.json`. Das Schema ist im README des Crawler-Repos
dokumentiert.

Dieser Extractor ist **read-only** auf das Crawler-Output-Verzeichnis - wir
schreiben dort nichts.

Ergaenzt damit die bestehende KM-Excel-Quelle (krai_pm.part_lifetimes), ohne sie
zu beruehren. Quellen werden ueber die `source`-Spalte unterscheidbar gemacht
("km_excel_*" vs "vbm_crawler:lexmark_v0.1").
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from insights.core.config import get_settings
from insights.core.logging import get_logger

logger = get_logger(__name__)


# Mapping vom Crawler-supplyType auf KM/Insights-part_category.
# Werte links: was unser Crawler `detectSupplyType` liefert.
# Werte rechts: was 037/038 fuer das teiltyp-Mapping erwartet.
_SUPPLY_TYPE_TO_CATEGORY: dict[str, str] = {
    "toner": "toner",
    "ink": "toner",                # fuer die OEM-Soll-Analyse aequivalent
    "drum": "drum",                # reine Trommel / Fotoleiter (photoconductor)
    "imaging_unit": "imaging_unit",  # Drum + Developer in EINEM Bauteil (eigener Teiltyp)
    "imaging_kit": "imaging_unit",
    "developer": "developing_unit_bw",
    "fuser": "fuser",
    "transfer_belt": "transfer_belt",
    "transfer_kit": "transfer_belt",
    "maintenance_kit": "fuser",    # naechste Verwandte im KM-Schema
    "adf_kit": "adf",              # ADF/ADZ-Dokumenteneinzug-Wartung -> Teiltyp Scanner/ADF
    "waste_container": "waste",
    "staple_cartridge": "staple",
    "other": "other",
}

# Mapping vom Crawler-color auf KM's color_channel-Kuerzel.
_COLOR_TO_CHANNEL: dict[str, str | None] = {
    "black": "bw",
    "cyan": "c",
    "magenta": "m",
    "yellow": "y",
    "tricolor": "col",
    "photo_black": "pbw",
    "gray": "gy",
    "unknown": None,
}


def _resolve_output_dir() -> Path:
    """Wo liegt das KRAI-Crawler-VBM `output/`-Verzeichnis?

    Bevorzugt `VBM_CRAWLER_OUTPUT_DIR` aus `.env`. Faellt zurueck auf den
    Sibling-Layout-Default (`../KRAI-Crawler-VBM/output/`), wie der Repo-Setup
    auf dem Dev-Rechner ist.
    """
    settings = get_settings()
    configured = (getattr(settings, "vbm_crawler_output_dir", "") or "").strip()
    if configured:
        return Path(configured)
    return (
        Path(__file__).resolve().parents[2].parent
        / "KRAI-Crawler-VBM"
        / "output"
    )


def _load_master() -> list[dict[str, Any]]:
    out = _resolve_output_dir()
    master = out / "supplies-master.json"
    if not master.exists():
        logger.warning(
            "VBM-Crawler-Master nicht gefunden (%s). Lauf "
            "`npm run aggregate` im Crawler-Repo oder setze VBM_CRAWLER_OUTPUT_DIR.",
            master,
        )
        return []
    return json.loads(master.read_text(encoding="utf-8"))


def fetch_vbm_crawler_lifetimes() -> Iterator[dict[str, Any]]:
    """Yieldet pro Crawler-Supply eine Zeile fuer `insights.part_lifetime_oem`.

    Eintraege ohne `yieldPages` (Heftklammern, manche Waste-Behaelter) werden
    uebersprungen - ohne Reichweite ist die Zeile fuer die OEM-Soll-Analyse
    nutzlos.
    """
    yielded = 0
    skipped_no_yield = 0
    for s in _load_master():
        if not s.get("yieldPages"):
            skipped_no_yield += 1
            continue
        cat = _SUPPLY_TYPE_TO_CATEGORY.get(s.get("supplyType", ""), "other")
        col = _COLOR_TO_CHANNEL.get(s.get("color", "unknown"))
        yield {
            "manufacturer": s.get("vendorLabel"),
            "part_category": cat,
            "part_number": s["supplyCode"],
            "nominal_lifetime_pages": int(s["yieldPages"]),
            "color_channel": col,
            "model_family": None,  # m:n via part_compatibility
            "source": f"vbm_crawler:{s['vendor']}_v0.1",
            "supply_color": s.get("color"),
            "yield_variant": s.get("yieldVariant"),
            "iso_standard": s.get("isoStandard"),
            "source_url": s.get("sourceUrl"),
        }
        yielded += 1
    logger.info(
        "VBM-Crawler liefert %d Reichweiten (uebersprungen ohne Yield: %d)",
        yielded,
        skipped_no_yield,
    )


def fetch_vbm_crawler_compatibility() -> Iterator[dict[str, Any]]:
    """Yieldet pro (Supply, kompatibler Drucker) eine Zeile fuer
    `insights.part_compatibility`.

    Dedupliziert das (manufacturer, part_number, printer_model)-Tripel beim Lesen,
    damit unsere UNIQUE-Constraint nicht durch reine Crawler-Duplikate (z. B.
    Bild- + Text-Link auf dieselbe Drucker-Seite) gestolpert wird - in der Theorie
    schon vom Crawler selbst dedupliziert, aber wir vertrauen nicht blind.
    """
    seen: set[tuple[str, str, str]] = set()
    yielded = 0
    for s in _load_master():
        col = _COLOR_TO_CHANNEL.get(s.get("color", "unknown"))
        mfr = s.get("vendorLabel") or ""
        pn = s.get("supplyCode") or ""
        for p in s.get("compatiblePrinters", []) or []:
            model = (p.get("model") or "").strip()
            if not model or not mfr or not pn:
                continue
            key = (mfr, pn, model)
            if key in seen:
                continue
            seen.add(key)
            yield {
                "manufacturer": mfr,
                "part_number": pn,
                "color_channel": col,
                "printer_model": model,
                "vendor_printer_id": p.get("vendorPrinterId"),
                "printer_url": p.get("url"),
                "source": f"vbm_crawler:{s['vendor']}_v0.1",
            }
            yielded += 1
    logger.info("VBM-Crawler liefert %d Kompatibilitaets-Zeilen", yielded)
