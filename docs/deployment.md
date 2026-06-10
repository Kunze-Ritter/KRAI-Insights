# Deployment — Dashboard für Kollegen verfügbar machen

Ziel: das Streamlit-Dashboard sicher für KR-Mitarbeiter erreichbar machen — **mit SSO
(Entra ID), ohne offenen Port, ohne die Daten aus dem Haus zu geben.**

## Warum dieser Weg (und nicht CF Pages / Supabase)

Das Dashboard ist eine **Streamlit-App** = ein laufender Python-Server (WebSockets),
kein statisches Frontend. **Cloudflare Pages** kann das nicht hosten, **Supabase** hostet
keine App (nur Postgres). Stattdessen bleibt die App in **Docker auf einer internen
Maschine**, und **Cloudflare Tunnel + Access** stellt sie sicher + per SSO bereit:

```
Kollege ──(SSO: Entra ID)──▶ Cloudflare Access ──▶ Cloudflare Tunnel ──▶ [intern: Docker app:8501]
```

- **Kein offener Port:** Der App-Port ist per Default nur an `127.0.0.1` gebunden; der
  Tunnel erreicht die App über das Docker-Netz (`http://app:8501`).
- **SSO am Rand:** Cloudflare Access erzwingt den Login (Entra ID / Microsoft 365), bevor
  jemand die App sieht — das geteilte `DASHBOARD_PASSWORD` wird damit überflüssig.
- **Daten bleiben intern:** Postgres + ETL laufen weiter auf eurer Infra (DSGVO).

## Voraussetzungen

- Eine **interne Maschine/VM**, die dauerhaft läuft, Docker hat und den Stack fährt
  (`docker compose up -d insights-postgres app`) — idealerweise dieselbe, auf der schon
  DB + ETL laufen, mit Zugang zu den Quellen (FleetMgmt, KRAI-PG, Radix).
- Eine **Cloudflare-Domain** (im CF-Account) + **Cloudflare Zero Trust** aktiviert (der
  kostenlose Plan reicht für kleine Teams).

## Schritt 1 — App-Bindung härten

Per Default bindet `docker-compose.yml` den App-Port an `127.0.0.1` (siehe `APP_BIND_HOST`
in `.env`). Damit ist die App **nicht im LAN** sichtbar, nur lokal + über den Tunnel.
Für direkten LAN-Zugriff in der Übergangszeit: `APP_BIND_HOST=0.0.0.0` in `.env`.

## Schritt 2 — Tunnel in Cloudflare anlegen

1. **Zero Trust → Networks → Tunnels → Create a tunnel** (Typ: *Cloudflared*).
2. Tunnel benennen (z. B. `krai-insights`), **Token kopieren**.
3. **Public Hostname** hinzufügen:
   - Subdomain/Domain wählen, z. B. `insights.kunze-ritter.de`.
   - **Service: `HTTP`** → URL **`app:8501`** (der Docker-Servicename; `cloudflared` läuft
     im selben Netz und löst ihn auf).
4. Token in `.env` eintragen: `CLOUDFLARE_TUNNEL_TOKEN=<token>`.

## Schritt 3 — Tunnel starten

```powershell
docker compose --profile tunnel up -d cloudflared
docker logs krai-insights-cloudflared    # sollte "Registered tunnel connection" zeigen
```

Die App ist jetzt unter der gewählten Subdomain erreichbar — aber noch ohne Login-Schutz.

## Schritt 4 — SSO erzwingen (Cloudflare Access)

> **Empfohlen (UI-unabhängig):** Die Zero-Trust-UI wird laufend umgebaut; die
> **Access-Application + Policy** lassen sich robust **per API** anlegen —
> `scripts/cf_access_setup.py`. Das hat sich live bewährt (die UI-Schritte führten
> versehentlich zu *gar keiner* Access-App, sodass die Domain offen war).
>
> ```powershell
> # .env: CF_API_TOKEN ("Access: Apps and Policies: Edit") + CF_ACCOUNT_ID
> python scripts/cf_access_setup.py --check                                   # read-only Status
> python scripts/cf_access_setup.py --domain insights.kunze-ritter.com `
>     --allow-domain kunze-ritter.de                                          # App + Allow-Policy
> # Gegentest: curl -sI https://insights.kunze-ritter.com  -> 302 zu cloudflareaccess.com
> ```
> Idempotent; `--allow-domain`/`--allow-email` sind mehrfach möglich.

### Login-Methode (Entra ID) — optional zusätzlich

1. **Zero Trust → Settings → Authentication → Login methods → Add → Azure AD**
   (Entra ID): App-Registrierung im Azure-Portal anlegen (Client-ID/Secret/Tenant),
   Redirect-URL aus Cloudflare eintragen. (Microsoft-Anleitung: „Cloudflare Zero Trust
   Azure AD integration".)
2. **Zero Trust → Access → Applications → Add an application → Self-hosted:**
   - Domain = `insights.kunze-ritter.de`.
   - **Policy:** Allow, z. B. *Emails ending in `@kunze-ritter.de`* oder bestimmte
     Entra-Gruppen.
3. Fertig: Aufruf der Subdomain leitet erst durch den Microsoft-Login.

Danach kann das interne `DASHBOARD_PASSWORD` leer bleiben (Access schützt bereits) — oder
als zweite Schicht gesetzt bleiben.

## Schritt 5 (optional) — Eingeloggten Nutzer in der App nutzen

Cloudflare Access reicht ein signiertes JWT im Header `Cf-Access-Jwt-Assertion` (und die
E-Mail in `Cf-Access-Authenticated-User-Email`) durch. Streamlit kann das später lesen
(z. B. Name anzeigen oder Rollen steuern) — aktuell nicht nötig, aber der Hook ist da.

## Betriebshinweise

- **Nie `docker compose down -v`** (löscht die DB-Volumes — siehe Compose-Warnung).
- Updates: `git pull` auf dem Host (Live-Mount) → `docker compose up -d app` (recreate,
  damit `.env`/Code neu geladen werden). Der Tunnel läuft unverändert weiter.
- Backups: `INSIGHTS_BACKUP_ENABLED=1` aktiviert das nächtliche `pg_dump` (siehe
  `docs/betrieb_sicherheit.md`).
- Der **nightly Scheduler** (`--profile scheduler`) und der **Tunnel** (`--profile tunnel`)
  sind unabhängige Opt-in-Services; beide können parallel laufen.

## Alternative (nur falls kein interner Dauer-Host)

Container auf eine kleine Cloud-VM (oder Azure Container Apps) + dieselbe CF-Access-Logik;
dann muss die VM die internen Quellen (FleetMgmt/KRAI-PG/Radix) erreichen — via
Site-to-Site-VPN oder einen zweiten Tunnel. Mehr Bewegliche Teile; nur wenn nötig.
