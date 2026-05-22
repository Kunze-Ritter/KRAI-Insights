"""
Best-effort pseudonymisation of customer contact persons in free text.

Policy (user decision): keep the full diagnostic value AND our own technicians'
names/initials (useful: "who solved this before"), but remove THIRD-PARTY customer
contact-person names ("Herr Volk", "z.Hd. Frau Müller") and emails. This is
best-effort over German service notes — a bare surname without a salutation can
slip through; the diagnostic content is preserved.
"""

from __future__ import annotations

import re

# A (possibly hyphenated/two-part) capitalised German name following a salutation.
# No leading word-boundary on purpose: service notes sometimes glue words
# ("...melden nichtHerr Neininger..."), and the trailing "<space><Name>" is the
# real anchor, so a stray boundary just lets names slip through.
_NAME = r"[A-ZÄÖÜ][a-zäöüß]+(?:[-\s][A-ZÄÖÜ][a-zäöüß]+)?"
_CONTACT_RE = re.compile(
    rf"(?:z\.?\s*Hd\.?\s*)?(?:Herrn?|Frau|Hr\.?|Fr\.?|Familie|Fam\.?)\s+{_NAME}",
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def pseudonymize_contacts(text: str | None) -> str | None:
    """Replace customer contact names + emails with placeholders. Keeps technicians."""
    if not text:
        return text
    out = _EMAIL_RE.sub("[email]", text)
    out = _CONTACT_RE.sub("[Kontakt]", out)
    return out
