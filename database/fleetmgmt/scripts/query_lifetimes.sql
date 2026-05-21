-- ===================================================================
-- Lebensdauer-Analyse: Toner / Drum / Developer / Fuser / etc.
-- ===================================================================
SET NOCOUNT ON;
USE DevFleetMgmt;

PRINT '=== 1) Beispiele aus ACCMARKERCOVERAGE (Verbrauchsmaterial-Stammdaten mit erwarteter Reichweite) ===';
SELECT TOP 15
    mc.Manufacturer        AS Hersteller,
    mc.OriginalPartNo      AS OriginalNr,
    mc.PartNo              AS BestellNr,
    mc.Colorant            AS Farbe,
    mc.Name                AS Bezeichnung,
    mc.Pages               AS Reichweite_Seiten,
    mc.Percentage          AS bei_Coverage_pct,
    mc.Price               AS Preis,
    mc.IsPreferred
  FROM ACCMARKERCOVERAGE mc
 WHERE mc.Pages IS NOT NULL AND mc.Pages > 0
 ORDER BY mc.Pages DESC;

PRINT '';
PRINT '=== 2) Anzahl Verbrauchsmaterialien pro Komponenten-Typ (Colorant) ===';
SELECT
    Colorant                                    AS Komponente,
    COUNT(*)                                    AS Eintraege,
    SUM(CASE WHEN Pages > 0 THEN 1 ELSE 0 END)  AS mit_Reichweite,
    AVG(CAST(Pages AS float))                   AS Avg_Pages,
    MIN(Pages)                                  AS Min_Pages,
    MAX(Pages)                                  AS Max_Pages,
    AVG(Percentage)                             AS Avg_Coverage_pct
  FROM ACCMARKERCOVERAGE
 WHERE Colorant IS NOT NULL
 GROUP BY Colorant
 ORDER BY Eintraege DESC;

PRINT '';
PRINT '=== 3) ACCMARKERALERT: Eingestellte Lebensdauer-Schwellwerte pro Komponente (84 Alert-Profile) ===';
SELECT TOP 10
    Name                AS Profil,
    -- Toner-Schwellwerte
    BlackPages,    BlackDays,    BlackPercent,
    CyanPages,     CyanDays,     CyanPercent,
    -- Komponenten
    OpcPages,      OpcDays,      OpcPercent     AS Drum_Pct,
    DeveloperPages,DeveloperDays,DeveloperPercent,
    FuserPages,    FuserDays,    FuserPercent,
    TransferUnitPages, TransferUnitDays, TransferUnitPercent AS TU_Pct,
    MaintenancePages, MaintenanceDays, MaintenancePercent   AS Maint_Pct
  FROM ACCMARKERALERT
 WHERE BlackPages > 0 OR DeveloperPages > 0 OR FuserPages > 0;

PRINT '';
PRINT '=== 4) Wie viele Alert-Profile haben Schwellwerte fuer welche Komponente eingestellt? ===';
SELECT
    SUM(CASE WHEN BlackPages > 0    OR BlackDays > 0    OR BlackPercent > 0    THEN 1 ELSE 0 END) AS Toner_Black,
    SUM(CASE WHEN CyanPages > 0     OR CyanDays > 0     OR CyanPercent > 0     THEN 1 ELSE 0 END) AS Toner_Cyan,
    SUM(CASE WHEN MagentaPages > 0  OR MagentaDays > 0  OR MagentaPercent > 0  THEN 1 ELSE 0 END) AS Toner_Magenta,
    SUM(CASE WHEN YellowPages > 0   OR YellowDays > 0   OR YellowPercent > 0   THEN 1 ELSE 0 END) AS Toner_Yellow,
    SUM(CASE WHEN OpcPages > 0      OR OpcDays > 0      OR OpcPercent > 0      THEN 1 ELSE 0 END) AS Drum_OPC,
    SUM(CASE WHEN DeveloperPages > 0 OR DeveloperDays > 0 OR DeveloperPercent > 0 THEN 1 ELSE 0 END) AS Developer,
    SUM(CASE WHEN FuserPages > 0    OR FuserDays > 0    OR FuserPercent > 0    THEN 1 ELSE 0 END) AS Fuser,
    SUM(CASE WHEN TransferUnitPages > 0 OR TransferUnitDays > 0 OR TransferUnitPercent > 0 THEN 1 ELSE 0 END) AS TransferUnit,
    SUM(CASE WHEN MaintenancePages > 0 OR MaintenanceDays > 0 OR MaintenancePercent > 0 THEN 1 ELSE 0 END) AS Maintenance,
    SUM(CASE WHEN ReceptaclePages > 0 OR ReceptacleDays > 0 OR ReceptaclePercent > 0 THEN 1 ELSE 0 END) AS Restbehaelter
  FROM ACCMARKERALERT;

PRINT '';
PRINT '=== 5) Tatsaechliche vs. Erwartete Coverage (aus 176k+ Refill-Events) ===';
SELECT TOP 5
    Name                            AS Verbrauchsmaterial,
    Colorant                        AS Farbe,
    CoveragePercentTarget           AS Soll_Coverage,
    CoveragePercentIs               AS Ist_Coverage,
    CoveragePagesTarget             AS Soll_Seiten,
    lDiffPageCount                  AS Tatsaechlich_Gedruckte_Seiten,
    CoveragePercentIs - CoveragePercentTarget AS Abweichung_pct,
    Refilled                        AS Wechsel_Datum
  FROM ACCMARKERREFILL
 WHERE CoveragePercentTarget > 0 AND lDiffPageCount > 0
 ORDER BY Refilled DESC;

PRINT '';
PRINT '=== 6) Durchschnitt: Wieviel SEITEN halten Verbrauchsmaterialien tatsaechlich (alle Refills)? ===';
SELECT
    Colorant                            AS Komponente,
    COUNT(*)                            AS Wechsel_gesamt,
    AVG(CAST(lDiffPageCount AS float))  AS Avg_tatsaechl_Seiten,
    AVG(CoveragePagesTarget)            AS Avg_erwartete_Seiten,
    AVG(CoveragePercentTarget)          AS Avg_Soll_Coverage,
    AVG(CoveragePercentIs)              AS Avg_Ist_Coverage
  FROM ACCMARKERREFILL
 WHERE Colorant IS NOT NULL AND lDiffPageCount > 0
 GROUP BY Colorant
 ORDER BY Wechsel_gesamt DESC;
