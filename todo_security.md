# TODO — Security / Access / Deployment-Härtung

Kategorie-Backlog (siehe [`todo.md`](todo.md)). Stand: 2026-05-22.

## Vor Mitarbeiter-Freigabe (Pflicht)

- [ ] **App-Exposition absichern.** Aktuell bindet `docker-compose.yml` Streamlit an `0.0.0.0:8501` (Container) — im Dev/Docker hinter NAT **derzeit geringes Risiko**, aber **bevor die App für Mitarbeiter bereitgestellt wird**:
  - entweder Bindung auf `127.0.0.1:8501:8501`, oder
  - **Reverse-Proxy (nginx) + Basic-Auth** (Phase-5-Härtung) vorziehen.
  - **Trigger zum sofortigen Handeln:** falls der Docker-Host eine direkte öffentliche IP + offenen Port 8501 hat (Streamlit meldete als External URL `91.26.87.218:8501`).
- [ ] **Bereitstellungs-Konzept** für Mitarbeiter (internes Netz / VPN / SSO/Authentik) festlegen.

## Zugriff / Least Privilege

- [ ] **Dedizierter read-only KRAI-PG-Login.** `.env` nutzt aktuell `krai_user` (Voll-Zugriff). Eigene RO-Rolle anlegen (analog FleetMgmt `krai_readonly`).
- [ ] FleetMgmt nutzt bereits `krai_readonly` (db_datareader) ✅.

## Daten / Compliance

- [ ] **PII-Guard automatisieren** (Schema-Scan auf E-Mail/Name/Telefon/Passwort/IP als Test/CI-Check).
- [ ] **Audit-Trail** für Warranty-Claim-Einreichungen (manueller Trigger, nachvollziehbar) — Phase 3/4.
- [ ] **Secrets:** `.env` enthält Klartext-Credentials (gitignored). Für Prod Vault/Secret-Store erwägen.
- [ ] Bestätigen, dass kein Quell-Connector je DDL/DML/POST absetzt (nur SELECT/GET) — als Test verankern.

## Betrieb

- [ ] Nightly `pg_dump`-Backup der Insights-DB (Phase 5).
- [ ] **DANGER dokumentiert:** nie `docker compose down -v` (löscht FleetMgmt-Volume + insights_pgdata).
