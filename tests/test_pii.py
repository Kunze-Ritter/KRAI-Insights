"""
DSGVO-Tests für die Pseudonymisierung von Kunden-Kontaktdaten in Freitext.

Policy (Nutzer-Entscheidung): Kunden-Kontaktnamen ("Herr Volk", "z.Hd. Frau Müller")
und E-Mails werden entfernt; der eigene Techniker-Name/Initialen bleiben (nützliche
Wissensbasis). Diese Regel ist DSGVO-kritisch und war bisher ungetestet — best-effort
über deutsche Service-Notizen, ein bloßer Nachname ohne Anrede kann durchrutschen
(bekannte Grenze, hier als xfail festgehalten, damit sie sichtbar bleibt).
"""

import pytest
from insights.core.pii import pseudonymize_contacts


@pytest.mark.parametrize(
    "text",
    [
        "Bitte z.Hd. Frau Müller senden",
        "Ansprechpartner Herrn Volk kontaktieren",
        "Rückruf an Herr Neininger erbeten",
        "Lieferung an Fam. Berger-Mai",
        "Frau Schmidt ist Ansprechpartnerin",
        "Hr. Weber war nicht erreichbar",
    ],
)
def test_salutation_names_are_pseudonymized(text: str) -> None:
    out = pseudonymize_contacts(text)
    assert "[Kontakt]" in out
    # Der eigentliche Name darf nicht mehr im Klartext stehen.
    for name in ("Müller", "Volk", "Neininger", "Berger", "Schmidt", "Weber"):
        if name in text:
            assert name not in out


def test_emails_are_pseudonymized() -> None:
    out = pseudonymize_contacts("Kontakt: max.mustermann@example.com für Rückfragen")
    assert "[email]" in out
    assert "@example.com" not in out


@pytest.mark.parametrize(
    "text,name",
    [
        ("Ansprechpartner: Sascha Scharf", "Scharf"),
        ("Ansprechpartnerin: Maria Vogel", "Vogel"),
        ("Kontaktperson: Hans Berger", "Berger"),
        ("Kontakt - Müller-Lüdenscheidt", "Müller"),
    ],
)
def test_label_based_contact_names_are_pseudonymized(text: str, name: str) -> None:
    out = pseudonymize_contacts(text)
    assert "[Kontakt]" in out
    assert name not in out


def test_company_label_is_kept() -> None:
    # Firmenname + Ort sind laut Policy erlaubt — NICHT pseudonymisieren.
    text = "Firmenname: Meisterdruck GmbH, Ort: Freiburg"
    out = pseudonymize_contacts(text)
    assert "Meisterdruck GmbH" in out
    assert "[Kontakt]" not in out


@pytest.mark.parametrize(
    "text",
    ["E-Mail:info@kunde.de", "mail an support@firma-xy.com bitte", "a.b+x@sub.domain.co.uk"],
)
def test_glued_and_unusual_emails_are_caught(text: str) -> None:
    out = pseudonymize_contacts(text)
    assert "@" not in out
    assert "[email]" in out


def test_email_and_contact_together() -> None:
    out = pseudonymize_contacts("z.Hd. Frau Müller (mueller@kunde.de) wegen Toner")
    assert "[Kontakt]" in out
    assert "[email]" in out
    assert "Müller" not in out
    assert "@kunde.de" not in out


def test_technician_initials_are_kept() -> None:
    # Eigene Techniker (Initialen / Kürzel ohne Kunden-Anrede) bleiben erhalten.
    text = "Gerät geprüft durch TH, Fehler behoben. Toner getauscht (Kürzel MK)."
    out = pseudonymize_contacts(text)
    assert "TH" in out
    assert "MK" in out
    assert "[Kontakt]" not in out


def test_plain_diagnostic_text_unchanged() -> None:
    text = "Fixiereinheit getauscht, Fehlercode C-2801 quittiert, Testdruck ok."
    assert pseudonymize_contacts(text) == text


@pytest.mark.parametrize("value", [None, ""])
def test_empty_input_passthrough(value) -> None:
    assert pseudonymize_contacts(value) == value


@pytest.mark.xfail(reason="Bekannte Grenze: bloßer Nachname ohne Anrede wird nicht erkannt", strict=False)
def test_bare_surname_without_salutation_known_gap() -> None:
    # Dokumentiert die best-effort-Grenze: ohne Anrede fehlt der Anker.
    out = pseudonymize_contacts("Neininger direkt anrufen")
    assert "[Kontakt]" in out
