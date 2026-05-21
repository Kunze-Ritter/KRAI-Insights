# Streamt die SQL-Datei zeilenweise und zählt CREATE TABLE / INSERT INTO statements.
# Schreibt KEINE Daten in RAM, nur Counters und Tabellennamen.
param(
    [string]$Path = "C:\Transferr\sql.sql"
)

$createPattern = 'CREATE TABLE \[dbo\]\.\[(?<name>[^\]]+)\]'
$insertPattern = 'INSERT \[dbo\]\.\[(?<name>[^\]]+)\]'

$tables       = @{}
$inserts      = @{}
$lineCount    = 0
$bytesRead    = 0
$startTime    = Get-Date
$lastReport   = Get-Date

# Read raw bytes to also get a reliable byte count for progress
$reader = [System.IO.StreamReader]::new($Path)
try {
    while ($null -ne ($line = $reader.ReadLine())) {
        $lineCount++

        if ($line -match $createPattern) {
            $tables[$Matches.name] = $true
        } elseif ($line.StartsWith('INSERT')) {
            if ($line -match $insertPattern) {
                $name = $Matches.name
                if ($inserts.ContainsKey($name)) {
                    $inserts[$name] += 1
                } else {
                    $inserts[$name] = 1
                }
            }
        }

        # Report progress every 5 seconds
        $now = Get-Date
        if (($now - $lastReport).TotalSeconds -ge 5) {
            $elapsed = ($now - $startTime).TotalSeconds
            $posMB = [math]::Round($reader.BaseStream.Position / 1MB, 0)
            $rate = if ($elapsed -gt 0) { [math]::Round($posMB / $elapsed, 1) } else { 0 }
            Write-Host ("[{0:hh\:mm\:ss}] {1} MB read | {2} lines | {3} tables | {4} INSERT lines | {5} MB/s" -f $elapsed, $posMB, $lineCount, $tables.Count, ($inserts.Values | Measure-Object -Sum).Sum, $rate)
            $lastReport = $now
        }
    }
}
finally {
    $reader.Close()
}

$elapsed = (Get-Date) - $startTime
Write-Host ""
Write-Host "=== DONE ==="
Write-Host ("Elapsed:        {0}" -f $elapsed)
Write-Host ("Total lines:    {0:N0}" -f $lineCount)
Write-Host ("Tables found:   {0:N0}" -f $tables.Count)
$totalInserts = ($inserts.Values | Measure-Object -Sum).Sum
Write-Host ("INSERT lines:   {0:N0}" -f $totalInserts)
Write-Host ""

# Top 30 tables by INSERT count
$outPath = "C:\Users\haast\Docker\KRAI-minimal\docs\fleetmgmt_table_stats.txt"
$lines = @()
$lines += "Fleet Management SQL Dump - Statistics"
$lines += "Generated: $(Get-Date)"
$lines += "Source:    $Path"
$lines += ""
$lines += "Total tables:        $($tables.Count)"
$lines += "Total INSERT lines:  $totalInserts"
$lines += ""
$lines += "Top 50 tables by INSERT row count:"
$lines += "----------------------------------"
$inserts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 50 |
    ForEach-Object { $lines += ("{0,12:N0}  {1}" -f $_.Value, $_.Key) }

$lines += ""
$lines += "All tables (alphabetical):"
$lines += "--------------------------"
$tables.Keys | Sort-Object | ForEach-Object {
    $cnt = if ($inserts.ContainsKey($_)) { $inserts[$_] } else { 0 }
    $lines += ("{0,12:N0}  {1}" -f $cnt, $_)
}

$lines | Out-File -FilePath $outPath -Encoding UTF8
Write-Host "Report written to: $outPath"
