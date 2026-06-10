"""
Cloudflare Access (Zero Trust) per API einrichten/prüfen — robust gegen UI-Umbauten.

Legt für eine selbst-gehostete App (hinter dem CF-Tunnel) eine Access-Application + eine
Allow-Policy an, sodass nur berechtigte Nutzer (E-Mail-Domain oder Einzeladressen) nach
SSO/OTP-Login durchkommen. Idempotent: vorhandene App/Policy wird aktualisiert.

Credentials aus der Umgebung (oder .env, das dieses Skript einliest):
    CF_API_TOKEN    Account-Token mit Permission "Access: Apps and Policies: Edit"
    CF_ACCOUNT_ID   die Cloudflare Account-ID

    python scripts/cf_access_setup.py --check
        # nur anzeigen, was für die Domain existiert (read-only)
    python scripts/cf_access_setup.py --domain insights.kunze-ritter.com \
        --allow-domain kunze-ritter.de --allow-domain kunze-ritter.com
        # App + Allow-Policy anlegen/aktualisieren
    python scripts/cf_access_setup.py --domain insights.kunze-ritter.com \
        --allow-email t.haas@kunze-ritter.de
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_API = "https://api.cloudflare.com/client/v4"


def _load_env() -> None:
    """Minimal .env loader (nur fehlende Keys), damit CF_* nicht doppelt gesetzt werden müssen."""
    env = _REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _req(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"success": False, "errors": [{"message": f"HTTP {e.code}"}]}


def _die(msg: str) -> None:
    print(f"FEHLER: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="Cloudflare Access per API einrichten")
    p.add_argument("--domain", default="insights.kunze-ritter.com", help="Hostname der App")
    p.add_argument("--name", default="KRAI Insights", help="Anzeige-Name der Access-App")
    p.add_argument("--session", default="24h", help="Session-Dauer (z. B. 24h, 8h)")
    p.add_argument("--allow-domain", action="append", default=[], help="erlaubte E-Mail-Domain (mehrfach)")
    p.add_argument("--allow-email", action="append", default=[], help="erlaubte Einzel-E-Mail (mehrfach)")
    p.add_argument("--check", action="store_true", help="nur anzeigen (read-only)")
    args = p.parse_args()

    _load_env()
    token = os.environ.get("CF_API_TOKEN", "").strip()
    account = os.environ.get("CF_ACCOUNT_ID", "").strip()
    if not token or not account:
        _die("CF_API_TOKEN und CF_ACCOUNT_ID müssen gesetzt sein (in .env oder Umgebung).")

    base = f"/accounts/{account}/access/apps"
    apps = _req("GET", base, token)
    if not apps.get("success"):
        _die(f"Token/Account ungültig oder keine Access-Rechte: {apps.get('errors')}")
    existing = next((a for a in apps["result"] if a.get("domain") == args.domain), None)

    print(f"=== Access-Status für {args.domain} ===")
    if existing:
        pol = _req("GET", f"{base}/{existing['id']}/policies", token)
        print(f"  App vorhanden (id {existing['id']}, '{existing.get('name')}')")
        for pl in pol.get("result", []):
            print(f"    Policy '{pl.get('name')}' -> decision={pl.get('decision')} include={pl.get('include')}")
        if not pol.get("result"):
            print("    ⚠️  KEINE Policy -> App lässt aktuell niemanden/jeden je nach Default durch!")
    else:
        print("  KEINE Access-App für diese Domain (= ungeschützt, falls per Tunnel veröffentlicht).")

    if args.check:
        return
    if not args.allow_domain and not args.allow_email:
        _die("Zum Anlegen mind. --allow-domain oder --allow-email angeben.")

    include = [{"email_domain": {"domain": d}} for d in args.allow_domain]
    include += [{"email": {"email": e}} for e in args.allow_email]

    if existing:
        app_id = existing["id"]
    else:
        created = _req("POST", base, token, {
            "name": args.name, "domain": args.domain, "type": "self_hosted",
            "session_duration": args.session,
        })
        if not created.get("success"):
            _die(f"App konnte nicht angelegt werden: {created.get('errors')}")
        app_id = created["result"]["id"]
        print(f"  + Access-App angelegt (id {app_id})")

    # Allow-Policy anlegen oder die erste vorhandene aktualisieren.
    pols = _req("GET", f"{base}/{app_id}/policies", token).get("result", [])
    pbody = {"name": "Allow KR", "decision": "allow", "include": include}
    if pols:
        res = _req("PUT", f"{base}/{app_id}/policies/{pols[0]['id']}", token, pbody)
        verb = "aktualisiert"
    else:
        res = _req("POST", f"{base}/{app_id}/policies", token, pbody)
        verb = "angelegt"
    if not res.get("success"):
        _die(f"Policy fehlgeschlagen: {res.get('errors')}")
    print(f"  + Allow-Policy {verb}: include={include}")
    print("\nFertig. Gegentest:  curl -sI https://" + args.domain + "   (erwartet: 302 -> cloudflareaccess.com)")


if __name__ == "__main__":
    main()
