# Radix APIs — Service vs. offizielle Core-API

Stand: 2026-05-22. Vergleich der beiden Radix/Infominds-APIs für die Frage, wo
kaufmännische Daten (Klickpreise, Arbeitssätze, Rechnungen) liegen.

| | Service-API (aktuell genutzt) | Offizielle Core-API |
|---|---|---|
| Titel | `IM.RxPlusService.Api` (v26.12.0) | `IM.Core.Api.Radix` (v2621.1.0) |
| Basis | `https://radix.kunze-ritter.de/IM.RxPlusService.Api` | `https://swtestingapi.acs.it/IM.Core.Api.Radix` (Test-Host) |
| Routen | 94 | 164 |
| Fokus | operativ: Geräte (serialnumber), Tickets, Aktivitäten, Zähler, Ersatzteile, Arbeitszeit | + kaufmännisch: Preise, Rechnungen, Aufträge, Angebote, Lieferscheine |
| Status | inoffiziell, in Nutzung | offiziell, **Kauf in Prüfung** |

## Nur in der offiziellen Core-API (`/api/v1/…`)

Ressourcen, die der Service-API fehlen: `prices`, `invoices`, `offers`, `orders`,
`purchaseOrders`, `deliveryNotes`, `salesReceipts`, `salesOpportunities`,
`projects`, `promotions`, `partLists`, `suppliers`, `contacts`,
`correspondenceAddresses`, `warehouse`; dazu reicheres `articles` (25 Routen) und
`serviceManagement` (15).

## Wo die für Profitabilität fehlenden Daten liegen

### Klickpreise → `/api/v1/prices`
Filter: `Id`, `ArtId`, `CustomerId`, `SupplierId`, `PriceKeyId`, `PromotionId`,
`ShippingAddressId`. Auch `/api/v1/prices/customerId/{id}` und
`/api/v1/articles/id/{id}/prices`.
Felder: `articleId`, **`customerId`**, `priceKey`, `priceKeyDescription`,
**`amount`** (Preis), `validFrom`, `validUntil`, `fromQuantity`, `unit`,
`discount1..5`, `vatIncluded`.
→ Klickpreise = Preis-Datensätze für die „Klick"-Artikel (S/W- und Farb-Klick),
kundenspezifisch. Ersetzt die manuelle `config/contract_pricing.yaml`.

### Arbeits-Stundensatz / echte Kosten → `/api/v1/invoices`
Filter: `Id`, `DokId`, `From`, `Until`, `DocumentType`.
Felder: `number`, `documentDate`, `customer`, `employee`, `amount`, `amountVat`,
`amountIncludingVat`, **`movements`** (Rechnungspositionen), `taxes`, `payment`.
→ Aus den Arbeits-Positionen (Stunden × Satz) ist der Stundensatz ableitbar; bzw.
der Satz liegt direkt als Artikel-Preis in `/api/v1/prices`. Ersetzt den manuellen
Stundensatz in `config/business_rules.yaml`.

## Konsequenz für krai-insights

- Mit der offiziellen API kommt die **Erlösseite (Klickpreise)** und die **echten
  Arbeitskosten/Rechnungen** automatisch — `profitability_snapshots` (Erlös −
  Material − Arbeit + Garantie-Rückhol-Wert) ohne manuelle Pflege.
- Bis dahin bleiben Klickpreise + Stundensatz manuelle Config (Hold bis nach Urlaub).
- Caveat: Swagger ist öffentlich (Test-Host); Live-Daten brauchen die gekaufte
  Lizenz/Credentials der produktiven Core-API.
