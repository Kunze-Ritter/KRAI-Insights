# Betrieb & Sicherheit

Operative Härtung rund um das Insights-System. Ergänzt die Observability-Doku
(`observability.md`) um Konfiguration, Backup, Secrets und offene Betriebs-To-dos.

## 1. Konfigurations-Check beim Start

`scripts/env_check.py` prüft, ob die wichtigen `.env`-Werte gesetzt und plausibel sind,
bevor ein fehlender Wert erst tief im ETL als unklarer Fehler auffällt (leere
Quellen-Credentials → ETL läuft still leer; offenes Dashboard in Prod usw.).

- **App + Scheduler** rufen `check_env()` beim Start auf — **nicht-fatal**, nur Log-Warnungen
  (im offenen Dev-/Docker-Netz sind leere Passwörter ok).
- **Prod-Deploy / CI:** `python scripts/env_check.py --strict` → Exit 1 bei Problemen.

## 2. Nächtliches Backup

`scripts/backup_insights_db.py` erzeugt einen komprimierten `pg_dump` der Insights-DB und
hält ihn `INSIGHTS_BACKUP_RETENTION_DAYS` Tage (Standard 30) in `INSIGHTS_BACKUP_DIR`
(Standard `./backups`). Die DB ist zwar aus den Quellen rebuildbar, aber die Lauf-Historie
(`scheduler_runs`) und der ~16-min-Cost-Crawl nicht „mal eben" — der Dump erspart das.

- **Aktivieren** (als nächtlicher Scheduler-Schritt im `daily_refresh`): Umgebungsvariable
  `INSIGHTS_BACKUP_ENABLED=1` setzen. Standardmäßig **aus**, damit Deployments ohne
  `pg_dump` nicht jede Nacht einen Fehlschritt melden.
- **Voraussetzung:** `pg_dump` im Image (`apt-get install -y postgresql-client`). Fehlt es,
  bricht das Skript mit klarer Meldung ab (kein stiller Fehlschlag).
- Manuell: `docker exec krai-insights-app python scripts/backup_insights_db.py`.

## 3. Secrets

- **CI** (`.github/workflows/ci.yml`, Job `secret-scan`) und **pre-commit**
  (`.pre-commit-config.yaml`) führen **gitleaks** aus → versehentlich committete Credentials
  werden erkannt. Lokal aktivieren: `pip install pre-commit && pre-commit install`.
- `.env` ist gitignored und gehört nicht ins Repo. Für Prod langfristig ein Secret-Manager
  (Vault / Azure Key Vault) statt Klartext-`.env`.

## 4. PII-Schema-Scan

`python scripts/pii_schema_scan.py` prüft das `insights`-Schema auf Spaltennamen, die auf
personenbezogene Daten hindeuten (E-Mail, Telefon, Passwort/Token, Geburtsdatum,
Kontakt-Person, Personen-Client-IP). Firmenname/Ort und der drucker-eigene IP/MAC sind
laut Policy erlaubt und werden NICHT angeschlagen. Nach jeder Migration laufen lassen;
Exit ≠ 0 bei Fund. Siehe auch `tests/test_pii.py` (Pseudonymisierung von Freitext).

## 5. Offenes To-do: dedizierte KRAI-PG-Read-only-Rolle

Aktuell nutzt `.env` für die KRAI-PG-Quelle den Login `krai_user` (**Vollzugriff**). Die
Extraktoren sind zwar SELECT-only (Konvention), aber ein Bug oder die falsche Engine könnte
theoretisch schreiben. **Empfehlung an den KRAI-Admin:** eine dedizierte Rolle
`krai_readonly` anlegen (nur SELECT auf `krai_pm`, analog zum FleetMgmt-`krai_readonly`),
danach `.env` / `.env.example` darauf umstellen. Rein organisatorisch — keine Code-Änderung
nötig. (FleetMgmt und Insights sind hiervon nicht betroffen: FleetMgmt nutzt bereits einen
read-only Login, Insights ist unsere eigene DB.)
