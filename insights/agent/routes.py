"""
Agent route catalog — typed, deterministic queries over the vw_* views.

Each route is a small function the chat agent can call as a tool. The LLM only
picks the route + fills typed params; the SQL is deterministic and runs against
the read-only Insights views, so answers are trustworthy and carry a citation.
All user-facing text is German.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import text

from insights.core.db import insights_engine


@dataclass
class AnswerCard:
    """Result of a route: a short German summary + table + citation."""

    text: str
    data: pd.DataFrame | None = None
    citation: dict[str, Any] = field(default_factory=dict)


@dataclass
class Route:
    name: str
    description: str
    parameters: dict[str, Any]          # JSON-schema 'properties'
    required: list[str]
    handler: Callable[[dict[str, Any]], AnswerCard]


def _df(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    with insights_engine().connect() as conn:
        return pd.DataFrame(conn.execute(text(sql), params or {}).mappings().all())


def _cite(view: str, sql: str, trust: float = 1.0) -> dict[str, Any]:
    return {"quelle": view, "sql": sql, "vertrauen": trust, "source_system": "insights"}


# --- Routes -----------------------------------------------------------------
def r_device_lookup(args: dict[str, Any]) -> AnswerCard:
    q = (args.get("suche") or "").strip()
    sql = (
        "SELECT manufacturer_serial AS seriennummer, radix_device_number AS radix_id, "
        "customer_name AS kunde, customer_city AS ort, manufacturer_canonical AS hersteller, "
        "model_display AS modell, device_status AS status, telemetry_stale_days AS tage_ohne_meldung "
        "FROM insights.vw_device_lookup "
        "WHERE manufacturer_serial ILIKE :q OR radix_device_number = :exact "
        "OR customer_name ILIKE :q OR model_display ILIKE :q "
        "ORDER BY (device_status = 'live') DESC LIMIT 25"
    )
    df = _df(sql, {"q": f"%{q}%", "exact": q})
    if df.empty:
        return AnswerCard(text=f"Kein Gerät zu {q} gefunden.", citation=_cite("vw_device_lookup", sql))
    txt = f"{len(df)} Gerät(e) zu {q} gefunden."
    if len(df) == 1:
        d = df.iloc[0]
        txt = (f"Gerät {d['seriennummer']} (Radix-ID {d['radix_id']}): {d['hersteller']} {d['modell']}, "
               f"Kunde {d['kunde']} ({d['ort']}), Status {d['status']}.")
        if d["status"] in ("silent", "never_reported"):
            txt += " Achtung: Dieses Gerät meldet derzeit keine Daten — Prüfung vor Ort empfohlen."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_device_lookup", sql))


def r_oem_yield(args: dict[str, Any]) -> AnswerCard:
    colorant = (args.get("farbe") or "black").lower()
    model = (args.get("modell") or "").strip()
    sql = (
        "SELECT manufacturer_canonical AS hersteller, model_display AS modell, refills AS wechsel, "
        "avg_real_pages AS echte_seiten, oem_target_pages AS hersteller_soll, avg_pct_of_oem AS pct_vom_soll "
        "FROM insights.vw_toner_yield_vs_oem WHERE colorant = :c AND refills >= 30 "
        "AND (:m = '' OR model_display ILIKE :ml) ORDER BY avg_pct_of_oem DESC LIMIT 25"
    )
    df = _df(sql, {"c": colorant, "m": model, "ml": f"%{model}%"})
    txt = (f"Reale Tonerlaufzeit ({colorant}) vs. Hersteller-Soll — {len(df)} Modell(e). "
           "Werte über 100 Prozent bedeuten: Material hält länger als angegeben.")
    return AnswerCard(text=txt, data=df, citation=_cite("vw_toner_yield_vs_oem", sql))


def r_warranty_candidates(args: dict[str, Any]) -> AnswerCard:
    customer = (args.get("kunde") or "").strip()
    kind_in = (args.get("art") or "claim").lower()
    kind = "negotiation" if kind_in.startswith(("verhand", "negoti")) else "claim"
    sql = (
        "SELECT customer_name AS kunde, model_display AS modell, cartridge_serial AS material_seriennr, "
        "colorant AS farbe, age_days AS standzeit_tage, pages AS gelaufene_seiten, rated AS soll, "
        "pct_of_oem AS pct_vom_soll, removed_on AS gewechselt "
        "FROM insights.vw_warranty_assessment WHERE warranty_class = :k AND cartridge_serial IS NOT NULL "
        "AND (:c = '' OR customer_name ILIKE :cl) ORDER BY pct_of_oem ASC LIMIT 50"
    )
    df = _df(sql, {"k": kind, "c": customer, "cl": f"%{customer}%"})
    label = "Garantiefälle" if kind == "claim" else "Verhandlungs-Kandidaten"
    fuer = f" für {customer}" if customer else ""
    txt = f"{len(df)} {label} (serial-belegt){fuer}."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_warranty_assessment", sql))


def r_error_code(args: dict[str, Any]) -> AnswerCard:
    code = (args.get("code") or "").strip()
    sql = (
        "SELECT error_code AS code, manufacturer AS hersteller, error_description AS bedeutung, "
        "solution_technician_text AS loesung_technik, severity_level AS schwere "
        "FROM insights.error_code_ref WHERE error_code ILIKE :c ORDER BY confidence_score DESC NULLS LAST LIMIT 10"
    )
    df = _df(sql, {"c": f"%{code}%"})
    if df.empty:
        return AnswerCard(text=f"Kein Fehlercode {code} in der Wissens-Datenbank gefunden.",
                          citation=_cite("error_code_ref", sql))
    d = df.iloc[0]
    txt = f"Fehlercode {d['code']} ({d['hersteller']}): {d['bedeutung']}"
    if d["loesung_technik"]:
        txt += f" — Technik-Lösung: {str(d['loesung_technik'])[:300]}"
    return AnswerCard(text=txt, data=df, citation=_cite("error_code_ref", sql))


def r_cost_for_customer(args: dict[str, Any]) -> AnswerCard:
    customer = (args.get("kunde") or "").strip()
    sql = (
        "SELECT customer_name AS kunde, material_eur, billable_material_eur AS davon_berechenbar_eur, "
        "contract_material_eur AS davon_vertrag_eur, labor_hours AS arbeit_std "
        "FROM insights.vw_cost_by_customer WHERE customer_name ILIKE :cl "
        "ORDER BY material_eur DESC NULLS LAST LIMIT 25"
    )
    df = _df(sql, {"cl": f"%{customer}%"})
    txt = f"Kosten zu {customer}: {len(df)} Kunde(n)." if not df.empty else f"Keine Kosten zu {customer} gefunden."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_cost_by_customer", sql))


def r_expiring_contracts(args: dict[str, Any]) -> AnswerCard:
    sql = (
        "SELECT customer_name AS kunde, model_display AS modell, device_serial AS seriennummer, "
        "code AS vertrag_nr, contract_type AS vertragsart, valid_until AS laeuft_aus "
        "FROM insights.vw_contract_renewal_radar ORDER BY valid_until LIMIT 100"
    )
    df = _df(sql)
    txt = f"{len(df)} Vertrag/Verträge laufen in den nächsten 90 Tagen aus (ohne Auto-Verlängerung)."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_contract_renewal_radar", sql))


def r_out_of_contract(args: dict[str, Any]) -> AnswerCard:
    customer = (args.get("kunde") or "").strip()
    sql = (
        "SELECT customer_name AS kunde, model_display AS modell, device_serial AS seriennummer, "
        "manufacturer_canonical AS hersteller FROM insights.vw_out_of_contract_devices "
        "WHERE (:c = '' OR customer_name ILIKE :cl) ORDER BY customer_name LIMIT 100"
    )
    df = _df(sql, {"c": customer, "cl": f"%{customer}%"})
    txt = f"{len(df)} aktive(s) Gerät(e) ohne laufenden Vertrag (Vertriebs-Chance)."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_out_of_contract_devices", sql))


_GAR_DESC = "Garantiefaelle oder Verhandlungs-Kandidaten (Teile unter Soll-Laufzeit), serial-belegt."
_ART_DESC = "claim = Garantiefall, verhandlung = Kandidat"

REGISTRY: list[Route] = [
    Route("geraet_suchen", "Findet ein Gerät/Drucksystem anhand Seriennummer, Radix-ID, Kunde oder Modell.",
          {"suche": {"type": "string", "description": "Seriennummer, Radix-ID, Kundenname oder Modell"}}, ["suche"],
          r_device_lookup),
    Route("toner_standzeit", "Reale Tonerlaufzeit im Vergleich zur Hersteller-Angabe je Modell.",
          {"farbe": {"type": "string", "enum": ["black", "cyan", "magenta", "yellow"]},
           "modell": {"type": "string", "description": "optionaler Modell-Filter"}}, [],
          r_oem_yield),
    Route("garantie_kandidaten", _GAR_DESC,
          {"kunde": {"type": "string", "description": "optionaler Kunden-Filter"},
           "art": {"type": "string", "enum": ["claim", "verhandlung"], "description": _ART_DESC}}, [],
          r_warranty_candidates),
    Route("fehlercode", "Bedeutung und Technik-Lösung zu einem Service-Menü-Fehlercode.",
          {"code": {"type": "string", "description": "Fehlercode, z. B. C-D9-01 oder 200.03"}}, ["code"],
          r_error_code),
    Route("kosten_kunde", "Material- und Arbeitskosten je Kunde (berechenbar vs. Vertrag).",
          {"kunde": {"type": "string", "description": "Kundenname"}}, ["kunde"],
          r_cost_for_customer),
    Route("auslaufende_vertraege", "Verträge, die in den nächsten 90 Tagen ohne Auto-Verlängerung auslaufen.",
          {}, [], r_expiring_contracts),
    Route("geraete_ohne_vertrag", "Aktive Geräte ohne laufenden Vertrag (Up-Sell-Chance).",
          {"kunde": {"type": "string", "description": "optionaler Kunden-Filter"}}, [],
          r_out_of_contract),
]

BY_NAME: dict[str, Route] = {r.name: r for r in REGISTRY}


def to_ollama_tools() -> list[dict[str, Any]]:
    """Render the registry as Ollama /api/chat tool definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": r.name,
                "description": r.description,
                "parameters": {"type": "object", "properties": r.parameters, "required": r.required},
            },
        }
        for r in REGISTRY
    ]
