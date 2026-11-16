# Offline, read-only source intake. No installation, network, MT5 or order APIs.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$M5Csv,
    [string]$M1Csv,
    [string]$ImportSpec,
    [Parameter(Mandatory=$true)][string]$StartUtc,
    [Parameter(Mandatory=$true)][string]$EndUtc,
    [Parameter(Mandatory=$true)][string]$EvaluationStartUtc,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$PythonExe='python',
    [switch]$DryRun
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
try {
    $version=(& $PythonExe -c 'import sys; print(sys.version_info[0],sys.version_info[1])' 2>$null | Out-String).Trim()
    if($LASTEXITCODE -ne 0 -or $version -ne '3 11'){throw 'Existing Python 3.11 required'}
    if(Test-Path -LiteralPath $OutputDirectory){throw 'Use a new output directory'}
    $mode='prepare'
    if($DryRun){$mode='inspect'}
    $arguments=@((Join-Path $PSScriptRoot 'prepare_real_data_pilot.py'),$mode,'--m5',$M5Csv,'--start-utc',$StartUtc,'--end-utc',$EndUtc,'--evaluation-start-utc',$EvaluationStartUtc,'--output-directory',$OutputDirectory)
    if($M1Csv){$arguments+=@('--m1',$M1Csv)}
    if($ImportSpec){$arguments+=@('--spec',$ImportSpec)}
    & $PythonExe @arguments
    $result=$LASTEXITCODE
    if($result -notin @(0,3)){throw 'Preparation did not finish'}
    if(-not(Test-Path -LiteralPath (Join-Path $OutputDirectory 'preparation-manifest.json'))){throw 'No completed preparation manifest'}
    Write-Output 'Source files remain unchanged. Review the private readiness report. Exit 3 is expected until independent qualification.'
    exit $result
} catch {
    Write-Output 'BLOCKED: use existing Python 3.11, readable CSVs, explicit UTC bounds and a fresh private output directory. Check reports before retrying; do not modify sources to force a pass.'
    exit 3
}
