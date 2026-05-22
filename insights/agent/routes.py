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


def _eur(n: float | int) -> str:
    return f"{round(n):,}".replace(",", ".") + " €"


# --- Lagebericht / Garantie-Geld (priority: recoverable money) --------------
def r_lagebericht(args: dict[str, Any]) -> AnswerCard:
    sql = "SELECT * FROM insights.vw_lagebericht"
    df = _df(sql)
    if df.empty:
        return AnswerCard(text="Keine Kennzahlen verfügbar.", citation=_cite("vw_lagebericht", sql))
    r = df.iloc[0]
    claims = int(r["garantie_claims"] or 0)
    preis = int(r["toner_preis_median"] or 0)
    schaetz = claims * preis
    txt = (
        "Lagebericht (Stand jetzt):\n"
        f"• Garantie/Geld: {claims} serial-belegte Garantiefälle (Ø nur {int(r['claim_schnitt_pct'] or 0)} % der "
        f"Soll-Laufzeit erreicht) → geschätzt {_eur(schaetz)} reklamierbares Material "
        f"(grobe Schätzung, ~{preis} € je Einheit); zusätzlich {int(r['verhandlung_kandidaten'] or 0)} "
        "Verhandlungs-Kandidaten als Hebel.\n"
        f"• Abrechnungsrisiko: {int(r['stille_unter_vertrag'] or 0)} Geräte unter Vertrag melden keine Zähler "
        "(Abrechnung läuft auf Schätzwerten).\n"
        f"• Datenqualität: {int(r['kunden_abweichung'] or 0)} Geräte mit abweichender Kundenzuordnung "
        "(Fehlversand-/Abrechnungsrisiko).\n"
        f"• Service: {int(r['verbrauch_14d'] or 0)} Verbrauchsmaterialien in 14 Tagen fällig, "
        f"{int(r['problem_geraete'] or 0)} auffällige Geräte (Sensor-Spam/Störungen).\n"
        f"• Flotte: {int(r['geraete_live'] or 0)} aktive Geräte."
    )
    return AnswerCard(text=txt, data=df, citation=_cite("vw_lagebericht", sql))


def r_warranty_overview(args: dict[str, Any]) -> AnswerCard:
    sql = (
        "SELECT hersteller, garantiefaelle, claim_schnitt_pct AS schnitt_pct_vom_soll, verhandlung "
        "FROM insights.vw_warranty_by_manufacturer"
    )
    df = _df(sql)
    lb = _df("SELECT garantie_claims, claim_schnitt_pct, toner_preis_median FROM insights.vw_lagebericht")
    claims = int(lb.iloc[0]["garantie_claims"] or 0) if not lb.empty else 0
    preis = int(lb.iloc[0]["toner_preis_median"] or 0) if not lb.empty else 0
    pct = int(lb.iloc[0]["claim_schnitt_pct"] or 0) if not lb.empty else 0
    txt = (
        f"Garantie-Übersicht: {claims} serial-belegte Garantiefälle, im Schnitt nur {pct} % der "
        f"Soll-Laufzeit erreicht → geschätzt {_eur(claims * preis)} reklamierbares Material "
        f"(grobe Schätzung, ~{preis} € je Einheit). Verteilung nach Hersteller siehe Tabelle; "
        "die konkreten, einreichbaren Einzelfälle liefert die Funktion 'garantie_kandidaten'."
    )
    return AnswerCard(text=txt, data=df, citation=_cite("vw_warranty_by_manufacturer", sql))


# --- Routes -----------------------------------------------------------------
def r_device_lookup(args: dict[str, Any]) -> AnswerCard:
    q = (args.get("suche") or "").strip()
    sql = (
        "SELECT manufacturer_serial AS seriennummer, radix_device_number AS radix_id, "
        "customer_name AS kunde, customer_city AS ort, manufacturer_canonical AS hersteller, "
        "model_display AS modell, device_status AS status, telemetry_stale_days AS tage_ohne_meldung, "
        "hostname, printer_ip AS ip_adresse, mac_address AS mac_adresse "
        "FROM insights.vw_device_lookup "
        "WHERE manufacturer_serial ILIKE :q OR radix_device_number = :exact "
        "OR customer_name ILIKE :q OR model_display ILIKE :q OR printer_ip ILIKE :q OR hostname ILIKE :q "
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
        if d["hostname"]:
            txt += f" Hostname {d['hostname']}."
        if d["ip_adresse"]:
            txt += f" IP {d['ip_adresse']}"
            if d["mac_adresse"]:
                txt += f" / MAC {d['mac_adresse']}"
            txt += "."
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


def r_vbm_validation(args: dict[str, Any]) -> AnswerCard:
    suche = (args.get("suche") or "").strip()
    nur_verdacht = args.get("nur_verdacht", True)
    where = ["validierung = 'verdacht_fake'"] if nur_verdacht else ["validierung <> 'radix_bestaetigt'"]
    params: dict[str, Any] = {}
    if suche:
        where.append("(device_serial ILIKE :s OR customer_name ILIKE :s)")
        params["s"] = f"%{suche}%"
    sql = (
        "SELECT customer_name AS kunde, model_display AS modell, device_serial AS seriennummer, "
        "colorant AS farbe, marker_name AS material, event_date AS datum, classification AS art, "
        "pages_since_previous AS seiten, validierung "
        f"FROM insights.vw_vbm_validation WHERE {' AND '.join(where)} ORDER BY event_date DESC LIMIT 100"
    )
    df = _df(sql, params)
    txt = (f"{len(df)} Teilewechsel mit Fake-Verdacht (FleetMgmt meldet Wechsel, "
           "aber kein passendes Radix-Material / nur Tür auf-zu).")
    return AnswerCard(text=txt, data=df, citation=_cite("vw_vbm_validation", sql))


def r_billing_risk(args: dict[str, Any]) -> AnswerCard:
    kunde = (args.get("kunde") or "").strip()
    sql = (
        "SELECT customer_name AS kunde, model_display AS modell, device_serial AS seriennummer, "
        "device_status AS status, telemetry_stale_days AS tage_ohne_meldung, contract_end AS vertrag_bis "
        "FROM insights.vw_billing_risk WHERE (:c = '' OR customer_name ILIKE :cl) "
        "ORDER BY telemetry_stale_days DESC NULLS LAST LIMIT 200"
    )
    df = _df(sql, {"c": kunde, "cl": f"%{kunde}%"})
    txt = f"{len(df)} Gerät(e) unter Vertrag ohne aktuelle Meldung (Abrechnung läuft auf Schätz-Zählern)."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_billing_risk", sql))


def r_consumables_due(args: dict[str, Any]) -> AnswerCard:
    tage = int(args.get("tage") or 14)
    kunde = (args.get("kunde") or "").strip()
    sql = (
        "SELECT customer_name AS kunde, model_display AS modell, device_serial AS seriennummer, "
        "colorant AS farbe, marker_name AS material, snmp_level AS fuellstand, "
        "remaining_days AS rest_tage, empty_date AS leer_am "
        "FROM insights.vw_consumables_due WHERE remaining_days <= :t "
        "AND (:c = '' OR customer_name ILIKE :cl) ORDER BY remaining_days ASC LIMIT 200"
    )
    df = _df(sql, {"t": tage, "c": kunde, "cl": f"%{kunde}%"})
    txt = f"{len(df)} Verbrauchsmaterial(ien)/Teil(e) werden in den nächsten {tage} Tagen fällig."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_consumables_due", sql))


def r_part_due(args: dict[str, Any]) -> AnswerCard:
    geraet = (args.get("geraet") or "").strip()
    sql = (
        "SELECT s.colorant AS farbe, s.marker_name AS material, s.snmp_level AS fuellstand, "
        "s.remaining_days AS rest_tage, s.empty_date AS leer_am, s.remaining_pages AS rest_seiten "
        "FROM insights.snmp_predictions s "
        "JOIN insights.devices_unified d ON d.fleetmgmt_device_id = s.fleetmgmt_device_id "
        "WHERE d.manufacturer_serial = :g OR d.radix_device_number = :g "
        "ORDER BY s.remaining_days ASC NULLS LAST LIMIT 50"
    )
    df = _df(sql, {"g": geraet})
    txt = (f"Restlaufzeiten für Gerät {geraet}: {len(df)} Materialien/Teile."
           if not df.empty else f"Keine Vorhersagedaten für {geraet}.")
    return AnswerCard(text=txt, data=df, citation=_cite("snmp_predictions", sql))


def r_material_install_check(args: dict[str, Any]) -> AnswerCard:
    status_in = (args.get("status") or "woanders").lower()
    suche = (args.get("suche") or "").strip()
    if status_in.startswith(("woander", "falsch")):
        status = "woanders_eingebaut"
    elif status_in.startswith(("kein", "lager", "offen")):
        status = "kein_einbau_gefunden"
    elif status_in.startswith(("korrekt", "richtig")):
        status = "korrekt"
    else:
        status = "woanders_eingebaut"
    where = ["einbau_status = :st"]
    params: dict[str, Any] = {"st": status}
    if suche:
        where.append("booked_serial ILIKE :s")
        params["s"] = f"%{suche}%"
    sql = (
        "SELECT booked_serial AS gebucht_auf_seriennr, colorant AS farbe, lieferdatum, "
        "description AS material, einbau_status "
        f"FROM insights.vw_material_install_check WHERE {' AND '.join(where)} "
        "ORDER BY lieferdatum DESC LIMIT 100"
    )
    df = _df(sql, params)
    if status == "woanders_eingebaut":
        txt = (f"{len(df)} Toner-Lieferung(en), die laut FleetMgmt auf einem ANDEREN Gerät desselben "
               "Kunden eingebaut wurden als in Radix gebucht — Hinweis auf Falschbuchung/Lagerumlage.")
    elif status == "kein_einbau_gefunden":
        txt = (f"{len(df)} Toner-Lieferung(en) ohne passenden FleetMgmt-Einbau "
               "(noch auf Lager, kundeneigen oder noch nicht verbaut).")
    else:
        txt = f"{len(df)} Toner-Lieferung(en) korrekt am gebuchten Gerät eingebaut."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_material_install_check", sql))


def r_customer_mismatch(args: dict[str, Any]) -> AnswerCard:
    stufe_in = (args.get("stufe") or "abweichung").lower()
    suche = (args.get("suche") or "").strip()
    if stufe_in.startswith(("teil", "wahrsch")):
        stufe = "teilweise"
    elif stufe_in.startswith(("ueberein", "überein", "gleich", "match")):
        stufe = "uebereinstimmung"
    else:
        stufe = "abweichung"
    where = ["abgleich = :st"]
    params: dict[str, Any] = {"st": stufe}
    if suche:
        where.append("(fleet_kunde ILIKE :s OR radix_kunde ILIKE :s OR device_serial ILIKE :s)")
        params["s"] = f"%{suche}%"
    sql = (
        "SELECT device_serial AS seriennummer, model_display AS modell, "
        "fleet_kunde AS kunde_fleet, radix_kunde AS kunde_radix, "
        "device_status AS status, last_report AS letzte_meldung, ip_subnetz, "
        "subnetz_passt_zu AS ip_bestaetigt, ort_gleich "
        f"FROM insights.vw_customer_device_mismatch WHERE {' AND '.join(where)} "
        "ORDER BY (subnetz_passt_zu IN ('fleet','radix')) DESC, (device_status='live') DESC, seriennummer LIMIT 200"
    )
    df = _df(sql, params)
    if stufe == "abweichung":
        txt = (f"{len(df)} Gerät(e), bei denen der Kunde in FleetMgmt und Radix nicht übereinstimmt "
               "(Risiko für Toner-Fehlversand/Falschabrechnung). Spalte ip_bestaetigt zeigt, welches System "
               "die aktuelle IP des Geräts stützt: fleet, radix oder beide/unklar — fleet/radix ist eindeutig.")
    elif stufe == "teilweise":
        txt = f"{len(df)} Gerät(e) mit ähnlichem, aber nicht identischem Kundennamen (wahrscheinlich gleich)."
    else:
        txt = f"{len(df)} Gerät(e) mit identischem Kunden (nach Normalisierung) in beiden Systemen."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_customer_device_mismatch", sql))


def r_shipping_addresses(args: dict[str, Any]) -> AnswerCard:
    kunde = (args.get("kunde") or "").strip()
    if not kunde:
        sql = (
            "SELECT kunde, kunde_ort, geraete, lieferadressen "
            "FROM insights.vw_customer_shipping ORDER BY lieferadressen DESC LIMIT 50"
        )
        df = _df(sql)
        txt = (f"Kunden mit den meisten Radix-Lieferadressen ({len(df)}). Viele Adressen = "
               "Lieferung muss je Standort sorgfältig zugeordnet werden.")
        return AnswerCard(text=txt, data=df, citation=_cite("vw_customer_shipping", sql))
    sql = (
        "SELECT rc.name AS kunde, s.description AS standort, s.street AS strasse, "
        "s.streetnumber AS hausnr, s.zip AS plz, s.city AS ort, s.is_default AS standard "
        "FROM insights.radix_shipping_addresses s "
        "JOIN insights.radix_customers rc ON rc.radix_customer_id = s.radix_customer_id "
        "WHERE rc.name ILIKE :q AND NOT COALESCE(s.inactive, FALSE) "
        "ORDER BY s.is_default DESC NULLS LAST, s.city, s.description LIMIT 200"
    )
    df = _df(sql, {"q": f"%{kunde}%"})
    if df.empty:
        return AnswerCard(text=f"Keine Lieferadressen zu {kunde} gefunden.",
                          citation=_cite("radix_shipping_addresses", sql))
    txt = f"{len(df)} Lieferadresse(n) für {kunde} (Radix) — wohin Toner/Teile geschickt werden."
    return AnswerCard(text=txt, data=df, citation=_cite("radix_shipping_addresses", sql))


def r_problem_devices(args: dict[str, Any]) -> AnswerCard:
    kunde = (args.get("kunde") or "").strip()
    nur_spam = args.get("nur_spam", False)
    where = ["einstufung = 'sensor_spam'"] if nur_spam else ["TRUE"]
    params: dict[str, Any] = {}
    if kunde:
        where.append("customer_name ILIKE :cl")
        params["cl"] = f"%{kunde}%"
    sql = (
        "SELECT customer_name AS kunde, model_display AS modell, device_serial AS seriennummer, "
        "events_365d AS alarme_jahr, offene_alarme, verschiedene_codes, einstufung, letzter_alarm "
        f"FROM insights.vw_problem_devices WHERE {' AND '.join(where)} LIMIT 100"
    )
    df = _df(sql, params)
    txt = (f"{len(df)} auffällige(s) Gerät(e) mit erhöhtem Alarm-Aufkommen "
           "(mögliche defekte Sensoren / wiederkehrende Störungen → Field-Service-Kandidat).")
    return AnswerCard(text=txt, data=df, citation=_cite("vw_problem_devices", sql))


def r_problem_models(args: dict[str, Any]) -> AnswerCard:
    sql = (
        "SELECT hersteller, modell, geraete, alarme_gesamt, alarme_pro_geraet "
        "FROM insights.vw_problem_models LIMIT 30"
    )
    df = _df(sql)
    txt = (f"{len(df)} Modell(e) nach Alarm-Aufkommen je Gerät (letzte 365 Tage, "
           "ab 5 Geräten) — hohe Werte = störanfälliges Modell.")
    return AnswerCard(text=txt, data=df, citation=_cite("vw_problem_models", sql))


def r_top_alert_codes(args: dict[str, Any]) -> AnswerCard:
    sql = (
        "SELECT alert_code AS code, bedeutung, alarme, betroffene_geraete, max_severity "
        "FROM insights.vw_top_alert_codes LIMIT 30"
    )
    df = _df(sql)
    txt = f"Häufigste Alarm-Codes der Flotte (letzte 365 Tage) — {len(df)} Codes."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_top_alert_codes", sql))


def r_open_events(args: dict[str, Any]) -> AnswerCard:
    kunde = (args.get("kunde") or "").strip()
    min_tage = int(args.get("min_tage") or 0)
    sql = (
        "SELECT customer_name AS kunde, model_display AS modell, device_serial AS seriennummer, "
        "alert_code AS code, bedeutung, offen_tage, offen_seit "
        "FROM insights.vw_open_events_aging WHERE offen_tage >= :mt "
        "AND (:c = '' OR customer_name ILIKE :cl) ORDER BY offen_tage DESC LIMIT 100"
    )
    df = _df(sql, {"mt": min_tage, "c": kunde, "cl": f"%{kunde}%"})
    txt = f"{len(df)} offene(r) Alarm(e) (noch nicht quittiert), älteste zuerst."
    return AnswerCard(text=txt, data=df, citation=_cite("vw_open_events_aging", sql))


_GAR_DESC = "Garantiefaelle oder Verhandlungs-Kandidaten (Teile unter Soll-Laufzeit), serial-belegt."
_ART_DESC = "claim = Garantiefall, verhandlung = Kandidat"

REGISTRY: list[Route] = [
    Route("lagebericht",
          "Gesamtüberblick / Lagebericht: die wichtigsten Kennzahlen auf einen Blick — "
          "Garantie-Rückholpotenzial (€), Abrechnungsrisiko, Datenqualität, Service. "
          "Nutze dies für Fragen wie 'Überblick', 'Was ist wichtig', 'Wo können wir Geld zurückholen'.",
          {}, [], r_lagebericht),
    Route("garantie_uebersicht",
          "Garantie-Auswertung: wie viele reklamierbare Garantiefälle, geschätzter Wert in Euro, "
          "und Verteilung nach Hersteller (wo die Reklamation lohnt).",
          {}, [], r_warranty_overview),
    Route("geraet_suchen",
          "Findet ein Gerät/Drucksystem anhand Seriennummer, Radix-ID, Kunde, Modell oder IP-Adresse "
          "(zeigt auch IP/MAC für den Service).",
          {"suche": {"type": "string", "description": "Seriennummer, Radix-ID, Kundenname, Modell oder IP-Adresse"}},
          ["suche"], r_device_lookup),
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
    Route("teilewechsel_validieren",
          "Prüft FleetMgmt-Teilewechsel gegen Radix: echter Tausch vs. Fake (Tür auf/zu, Wiedereinsetzen).",
          {"suche": {"type": "string", "description": "optionaler Geräte-Seriennummer- oder Kunden-Filter"}}, [],
          r_vbm_validation),
    Route("verbrauch_faellig",
          "Verbrauchsmaterial/Teile, die bald fällig sind (Toner bald leer, Teil bald zu wechseln).",
          {"tage": {"type": "integer", "description": "Horizont in Tagen (Standard 14)"},
           "kunde": {"type": "string", "description": "optionaler Kunden-Filter"}}, [],
          r_consumables_due),
    Route("restlaufzeit_geraet",
          "Aktuelle Restlaufzeiten (Tage/Seiten) aller Materialien/Teile eines Geräts.",
          {"geraet": {"type": "string", "description": "Geräte-Seriennummer oder Radix-ID"}}, ["geraet"],
          r_part_due),
    Route("abrechnungs_risiko",
          "Geräte unter Vertrag, die keine Daten mehr melden — Abrechnung auf Schätz-Zählern.",
          {"kunde": {"type": "string", "description": "optionaler Kunden-Filter"}}, [],
          r_billing_risk),
    Route("material_einbau_pruefen",
          "Prüft, wo ein in Radix gebuchter Toner laut FleetMgmt tatsächlich eingebaut wurde "
          "(richtiges Gerät, anderes Gerät desselben Kunden = Falschbuchung, oder kein Einbau).",
          {"status": {"type": "string", "enum": ["woanders", "kein_einbau", "korrekt"],
                      "description": "woanders = Falschbuchung (Standard), kein_einbau = ohne Einbau, korrekt"},
           "suche": {"type": "string", "description": "optionale gebuchte Geräte-Seriennummer"}}, [],
          r_material_install_check),
    Route("problem_geraete",
          "Geräte mit auffällig vielen Alarmen (defekte Sensoren / wiederkehrende Störungen, Field-Service).",
          {"kunde": {"type": "string", "description": "optionaler Kunden-Filter"},
           "nur_spam": {"type": "boolean", "description": "nur Sensor-Spam (>=1000 Alarme/Jahr)"}}, [],
          r_problem_devices),
    Route("problem_modelle",
          "Störanfälligste Geräte-Modelle nach Alarm-Aufkommen je Gerät (letzte 365 Tage).",
          {}, [], r_problem_models),
    Route("haeufige_alarme",
          "Häufigste Alarm-Codes der gesamten Flotte mit Bedeutung und Anzahl betroffener Geräte.",
          {}, [], r_top_alert_codes),
    Route("offene_alarme",
          "Offene (noch nicht quittierte) Alarme mit Standzeit — älteste zuerst.",
          {"kunde": {"type": "string", "description": "optionaler Kunden-Filter"},
           "min_tage": {"type": "integer", "description": "nur Alarme, die seit mind. N Tagen offen sind"}}, [],
          r_open_events),
    Route("kunden_abgleich",
          "Geräte, deren Kunde/Standort in FleetMgmt und Radix abweicht — Risiko für Toner-Fehlversand "
          "und Falschabrechnung (z. B. weiterverkaufte Geräte oder falsche Zuordnung).",
          {"stufe": {"type": "string", "enum": ["abweichung", "teilweise", "uebereinstimmung"],
                     "description": "abweichung = klarer Unterschied (Standard), teilweise = ähnlich, sonst gleich"},
           "suche": {"type": "string", "description": "optionaler Kunden- oder Seriennummer-Filter"}}, [],
          r_customer_mismatch),
    Route("lieferadressen",
          "Lieferadressen eines Kunden aus Radix (wohin Toner/Teile geschickt werden); "
          "ohne Kunde: Kunden mit den meisten Lieferadressen.",
          {"kunde": {"type": "string", "description": "Kundenname (optional)"}}, [],
          r_shipping_addresses),
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
