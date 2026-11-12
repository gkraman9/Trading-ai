# Read-only local runner. Uses an existing 64-bit Python 3.11; no login inputs.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SessionConfig,
    [string]$PythonExe = 'python',
    [string]$ReportDirectory = (Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'IAT\validation-evidence'),
    [string]$BrokerMetadata,
    [string]$TerminalPath,
    [switch]$InstallOptionalDependencies
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$runName = 'iat-demo-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N') + '.json'
$reportPath = Join-Path $ReportDirectory $runName
$failureCode = 'RUNNER_PREFLIGHT_FAILED'

function Write-PreflightFailure([string]$Code) {
    # Never overwrite a diagnostic's reserved failure or any earlier run.
    if (Test-Path -LiteralPath $reportPath) { return }
    [IO.Directory]::CreateDirectory($ReportDirectory) | Out-Null
    $temporary = Join-Path $ReportDirectory ('.iat-runner-' + [Guid]::NewGuid().ToString('N'))
    $body = @{ report_version = 1; scope = 'RUNNER_PREFLIGHT'; status = 'FAIL'; code = $Code;
        timestamp_utc = [DateTime]::UtcNow.ToString('o'); signal = 'WAIT'; execution_allowed = $false } | ConvertTo-Json
    try {
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($body)
        $stream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        [IO.File]::Move($temporary, $reportPath)
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

try {
    if ($env:OS -ne 'Windows_NT') { $failureCode = 'WINDOWS_REQUIRED'; throw 'preflight' }
    $preflight = (& $PythonExe -c 'import sys,struct; print(sys.version_info[0],sys.version_info[1],8*struct.calcsize(chr(80)))' 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'preflight' }
    if ($preflight -ne '3 11 64') {
        $failureCode = 'PYTHON_311_X64_REQUIRED'; throw 'preflight'
    }
    if (-not (Test-Path -LiteralPath $SessionConfig -PathType Leaf)) {
        $failureCode = 'CONFIG_FILE_UNAVAILABLE'; throw 'preflight'
    }
    [IO.Directory]::CreateDirectory($ReportDirectory) | Out-Null
    if ($InstallOptionalDependencies) {
        # Only official PyPI wheels. No shell downloads, setup scripts, custom
        # indexes, upgrade flag, credential arguments or execution-policy changes.
        $requirements = Join-Path (Split-Path $PSScriptRoot -Parent) 'requirements.txt'
        $failureCode = 'DEPENDENCY_INSTALLATION_FAILED'
        & $PythonExe -m pip --isolated --disable-pip-version-check install --index-url https://pypi.org/simple --only-binary=:all: -r $requirements MetaTrader5 *> $null
        if ($LASTEXITCODE -ne 0) { $failureCode = 'DEPENDENCY_INSTALLATION_FAILED'; throw 'preflight' }
    }
    $failureCode = 'VALIDATION_RUN_FAILED'
    $diagnostic = Join-Path $PSScriptRoot 'mt5_readonly_check.py'
    $arguments = @($diagnostic, '--config', $SessionConfig, '--report-path', $reportPath)
    if ($TerminalPath) { $arguments += @('--terminal-path', $TerminalPath) }
    if ($BrokerMetadata) { $arguments += @('--broker-metadata', $BrokerMetadata) }
    # Discard all child stdout/stderr, including native-library messages. Only
    # the allowlisted evidence file and fixed status summary are exposed.
    & $PythonExe @arguments *> $null
    $result = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        $failureCode = 'EVIDENCE_NOT_PUBLISHED'; throw 'preflight'
    }
    $saved = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($saved.status -notin @('PASS', 'WARN', 'FAIL') -or $result -notin @(0, 1, 2)) {
        $failureCode = 'EVIDENCE_STATUS_INVALID'; throw 'preflight'
    }
    Write-Output ('Status: ' + $saved.status)
    # Print a basename only, never personal paths or configuration contents.
    Write-Output ('Evidence file: ' + $runName)
    exit $result
} catch {
    try { Write-PreflightFailure $failureCode } catch { }
    Write-Output ('FAIL: ' + $failureCode)
    exit 1
}
