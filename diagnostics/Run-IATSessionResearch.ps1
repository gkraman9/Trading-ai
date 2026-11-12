# Research only. No installation, credentials, account switching or trade APIs.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SessionConfig,
    [string]$PythonExe='python',
    [string]$ReportDirectory=(Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'IAT\session-research'),
    [string]$Observations,
    [string]$BrokerMetadata,
    [string]$TerminalPath,
    [switch]$CaptureDemo
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
try {
    $version=(& $PythonExe -c 'import sys,struct; print(sys.version_info[0],sys.version_info[1],8*struct.calcsize(chr(80)))' 2>$null | Out-String).Trim()
    if($LASTEXITCODE -ne 0 -or $version -ne '3 11 64'){throw 'Existing Python 3.11 x64 required'}
    [IO.Directory]::CreateDirectory($ReportDirectory) | Out-Null
    $name='iat-session-research-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')+'-'+[Guid]::NewGuid().ToString('N')+'.json'
    $path=Join-Path $ReportDirectory $name
    $arguments=@((Join-Path $PSScriptRoot 'session_v2_research.py'),'--config',$SessionConfig,'--report-path',$path)
    if($CaptureDemo){$arguments+=@('--capture-demo')}
    if($Observations){$arguments+=@('--observations',$Observations)}
    if($BrokerMetadata){$arguments+=@('--broker-metadata',$BrokerMetadata)}
    if($TerminalPath){$arguments+=@('--terminal-path',$TerminalPath)}
    & $PythonExe @arguments *> $null
    $result=$LASTEXITCODE
    if(-not(Test-Path -LiteralPath $path)){throw 'No evidence published'}
    $report=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    if($report.status -notin @('PASS','WARN','FAIL','BLOCKED') -or $result -notin @(0,1,2,3)){throw 'Invalid evidence result'}
    Write-Output ('Status: '+$report.status)
    Write-Output ('Evidence file: '+$name)
    exit $result
} catch {
    Write-Output 'FAIL: SESSION_RESEARCH_RUNNER_FAILED'
    exit 1
}
