-- 047_vbm_crawler_supplies.sql
-- Macht die OEM-Verbrauchsmaterial-Daten der externen VBM-Crawler (KRAI-Crawler-VBM)
-- in der Insights-DB nutzbar - parallel zur bestehenden KM-Excel-Quelle.
--
-- Hintergrund:
-- Bisher hatten wir part_lifetime_oem nur fuer Konica Minolta (aus einer Excel via
-- krai_pm.part_lifetimes). Mit dem neuen VBM-Crawler ziehen wir Toner-/Drum-/Developer-
-- Reichweiten direkt von den Hersteller-Websites (zunaechst Lexmark, danach HP/Canon/KM).
--
-- Was diese Migration tut:
--   1) Ergaenzt part_lifetime_oem um 4 optionale Spalten, die der Crawler nativ liefert,
--      ohne die bestehende KM-Befuellung zu brechen (alle neuen Spalten NULLable).
--   2) Legt einen natuerlichen UNIQUE-Schluessel (manufacturer, part_number) an,
--      damit der neue Loader sauber UPSERTen kann statt TRUNCATE+INSERT.
--   3) Legt insights.part_compatibility an - die m:n-Beziehung Supply <-> Drucker,
--      die bei KM noch kein Thema war (eine KM-Reichweite je Modell), aber bei Lexmark
--      etc. essenziell ist (1 Toner passt typischerweise in 5-20 Drucker).
--
-- Beide Tabellen tragen 'source' - der Loader loescht selektiv per
--   DELETE WHERE source LIKE 'vbm_crawler:%'
-- und ueberschreibt damit nur die eigenen Eintraege.

-- 1) part_lifetime_oem erweitern -------------------------------------------------
ALTER TABLE insights.part_lifetime_oem
    ADD COLUMN IF NOT EXISTS supply_color  VARCHAR(20),   -- original Crawler-Farbe (black/cyan/...)
    ADD COLUMN IF NOT EXISTS yield_variant VARCHAR(20),   -- standard/high/extra_high/unknown
    ADD COLUMN IF NOT EXISTS iso_standard  VARCHAR(40),   -- "ISO/IEC 19798" etc.
    ADD COLUMN IF NOT EXISTS source_url    TEXT;          -- Crawler-Quell-URL fuer Audit

-- UPSERT-Key NUR fuer VBM-Crawler-Eintraege. Die bestehenden KM-Excel-Daten
-- enthalten Duplikate auf (manufacturer, part_number) - aus der Excel uebernommen,
-- z. T. mit leeren part_numbers (~60 Eintraege "Konica Minolta, Inc." ohne PN).
-- Ein globaler UNIQUE-Index waere also retroaktiv nicht erfuellbar; ein
-- partieller Index nur ueber unsere Quelle entkoppelt beide Welten.
CREATE UNIQUE INDEX IF NOT EXISTS uq_part_lifetime_oem_vbm
    ON insights.part_lifetime_oem (manufacturer, part_number)
    WHERE source LIKE 'vbm_crawler:%';

-- 2) part_compatibility (m:n Supply <-> Drucker) --------------------------------
CREATE TABLE IF NOT EXISTS insights.part_compatibility (
    id                BIGSERIAL PRIMARY KEY,
    manufacturer      VARCHAR(100) NOT NULL,
    part_number       VARCHAR(80)  NOT NULL,
    color_channel     VARCHAR(20),
    printer_model     VARCHAR(200) NOT NULL,   -- z. B. "Lexmark CX950se"
    vendor_printer_id VARCHAR(50),             -- Vendor-interne ID (z. B. Lexmark PID)
    printer_url       TEXT,                    -- Detail-URL zur Drucker-Seite
    source            VARCHAR(60)  NOT NULL,
    ingested_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Idempotenz: gleiches (Hersteller, Teilenummer, Drucker)-Tripel nicht doppelt.
CREATE UNIQUE INDEX IF NOT EXISTS uq_part_compat_natural
    ON insights.part_compatibility (manufacturer, part_number, printer_model);

CREATE INDEX IF NOT EXISTS ix_part_compat_mfr_part
    ON insights.part_compatibility (manufacturer, part_number);
CREATE INDEX IF NOT EXISTS ix_part_compat_printer
    ON insights.part_compatibility (printer_model);

-- 3) Komfort-View: "welche Verbrauchsmaterialien passen zu Drucker X" ------------
CREATE OR REPLACE VIEW insights.vw_printer_supplies AS
SELECT
    pc.manufacturer,
    pc.printer_model,
    pc.vendor_printer_id,
    pc.printer_url,
    pl.part_category,
    pl.part_number,
    pl.nominal_lifetime_pages,
    pl.color_channel,
    pl.supply_color,
    pl.yield_variant,
    pl.iso_standard,
    pl.source_url,
    pl.source AS lifetime_source,
    'vbm_crawler'::varchar AS source_system
FROM insights.part_compatibility pc
JOIN insights.part_lifetime_oem pl
    ON pl.manufacturer = pc.manufacturer
   AND pl.part_number  = pc.part_number;
