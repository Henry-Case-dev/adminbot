$env:PYTHONIOENCODING = 'utf-8'
Set-Location C:\Code\Python\adminbot
$py = ".venv\Scripts\python.exe"
$log = "plans\features\asap5-final-fixes\full_pytest_t5270.log"
"FULL PYTEST T-5270 START $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File $log -Encoding utf8

$all = Get-ChildItem tests\test_*.py | Sort-Object Name
$segs = @(
    @{ name = "G1[a-e]"; lo = 'a'; hi = 'e' },
    @{ name = "G2[f-m]"; lo = 'f'; hi = 'm' },
    @{ name = "G3[n-z]"; lo = 'n'; hi = 'z' }
)
$totalPass = 0; $totalFail = 0; $failedFiles = @()
foreach ($s in $segs) {
    $files = @($all | Where-Object {
        $c = $_.Name.Substring(5, 1)
        return ($c -ge $s.lo -and $c -le $s.hi)
    } | ForEach-Object { $_.FullName })
    "=== SEGMENT $($s.name): $($files.Count) files START $(Get-Date -Format 'HH:mm:ss') ===" | Out-File $log -Append -Encoding utf8
    $out = & $py -m pytest @files -q --tb=no -p no:cacheprovider 2>&1
    $out | Out-File $log -Append -Encoding utf8
    $summary = ($out | Select-Object -Last 3) -join " "
    "=== SEGMENT $($s.name) SUMMARY: $summary ===" | Out-File $log -Append -Encoding utf8
    if ($summary -match '(\d+) passed') { $totalPass += [int]$Matches[1] }
    if ($summary -match '(\d+) failed') { $totalFail += [int]$Matches[1] }
    $out | Where-Object { $_ -match '^FAILED' } | ForEach-Object { $failedFiles += $_ }
}
"=== TOTAL: passed=$totalPass failed=$totalFail ===" | Out-File $log -Append -Encoding utf8
$failedFiles | ForEach-Object { $_ | Out-File $log -Append -Encoding utf8 }
"FULL PYTEST T-5270 END $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File $log -Append -Encoding utf8
