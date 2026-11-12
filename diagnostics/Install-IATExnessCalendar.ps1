# Writes a structurally valid, explicitly BLOCKED review candidate; no MT5 calls.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$PythonExe = 'python',
    [string]$Destination = (Join-Path (Split-Path $PSScriptRoot -Parent) 'config\local\exness-xauusd-observed-2026-11.json')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
try {
    $preflight = (& $PythonExe -c 'import sys,struct; print(sys.version_info[0],sys.version_info[1],8*struct.calcsize(chr(80)))' 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $preflight -ne '3 11 64') { throw 'Python 3.11 x64 required' }
    if (-not $PSCmdlet.ShouldProcess('local Exness review candidate', 'Install schema-valid, runtime-blocked configuration')) { exit 0 }
    $arguments = @((Join-Path $PSScriptRoot 'install_exness_calendar.py'), '--destination', $Destination)
    if (Test-Path -LiteralPath $Destination) {
        if (-not $PSCmdlet.ShouldContinue('Replace the existing local configuration with the BLOCKED review candidate?', 'Confirm configuration replacement')) { exit 1 }
        $digest = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
        $arguments += @('--replace-confirmed', '--expected-current-sha256', $digest)
    }
    & $PythonExe @arguments
    exit $LASTEXITCODE
} catch {
    Write-Output 'FAIL: PROFILE_INSTALLATION_FAILED'
    exit 1
}
