# One offline research operation. No installs, network, MT5, service or execution calls.
[CmdletBinding()]
param(
    [string]$M1Csv='E:\IAT2\Data\XAUUSD_M1_Exness_20261111_20261113.csv',
    [string]$M5Csv='E:\IAT2\Data\XAUUSD_M5_Exness_20261111_20261113.csv',
    [string]$OriginalReport='E:\IAT2\Data\b2_historical_boundaries_20261123.json',
    [string]$CalendarPath=(Join-Path $PSScriptRoot '..\config\profiles\exness-xauusd-v2.candidate.json'),
    [string]$OutputDirectory=(Join-Path 'E:\IAT2\Data' ('boundary-evidence-' + [Guid]::NewGuid().ToString('N'))),
    [string]$PythonExe
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
try {
    if (-not $PythonExe) {
        $PythonExe=(& py -3.11 -c 'import sys; print(sys.executable)' 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $PythonExe) { throw 'Python 3.11 unavailable' }
    }
    $version=(& $PythonExe -c 'import sys; print(sys.version_info[0],sys.version_info[1])' 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $version -ne '3 11') { throw 'Existing Python 3.11 required' }
    if (Test-Path -LiteralPath $OutputDirectory) { throw 'Choose a NEW private output directory' }
    # Check all inputs here as well; the helper writes explicit missing-input evidence.
    foreach ($inputFile in @($M1Csv,$M5Csv,$OriginalReport,$CalendarPath)) {
        if (-not (Test-Path -LiteralPath $inputFile -PathType Leaf)) {
            Write-Output 'A required local input is unavailable; the evidence summary will remain BLOCKED.'
        }
    }
    $arguments=@((Join-Path $PSScriptRoot 'verify_boundary_evidence.py'),
        '--m1',$M1Csv,'--m5',$M5Csv,'--original-report',$OriginalReport,
        '--calendar',$CalendarPath,'--output-directory',$OutputDirectory)
    & $PythonExe @arguments
    $result=$LASTEXITCODE
    $summary=Join-Path $OutputDirectory 'evidence-summary.json'
    if ($result -notin @(2,3) -or -not (Test-Path -LiteralPath $summary -PathType Leaf)) {
        throw 'No completed evidence summary'
    }
    $r=Get-Content -LiteralPath $summary -Raw | ConvertFrom-Json
    if ($r.signal -ne 'WAIT' -or $r.execution_allowed -ne $false -or
        $r.qualification -ne 'DATA_NOT_QUALIFIED' -or $r.exness -ne 'BLOCKED' -or
        $r.historical_validation -ne 'PENDING' -or $r.historical_comparisons -ne 'NOT_RUN' -or
        $r.safety.execution_allowed -ne $false -or $r.safety.orders_requested -ne 0) {
        throw 'Evidence safety invariants failed'
    }
    if (($result -eq 2) -ne ($r.status -eq 'BLOCKED')) { throw 'Evidence exit/status mismatch' }
    Write-Output ('Private evidence summary: ' + $summary)
    Write-Output 'Exit 3 means completed research, not qualification. Exit 2 means BLOCKED; inspect the summary reason codes.'
    exit $result
} catch {
    Write-Output 'BLOCKED: use existing Python 3.11, the original readable files, and a NEW private output directory outside Git. No dependencies are installed. No existing file is overwritten.'
    exit 2
}
