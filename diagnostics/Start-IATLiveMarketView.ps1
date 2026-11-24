# Uses the existing read-only observer; does not launch B.2/B.3 or enable AI.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = '',
    [ValidateRange(1024,65535)][int]$Port = 8768,
    [ValidateRange(2,60)][int]$Interval = 10,
    [string]$LogParent = '',
    [string]$SessionConfig = '',
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
try {
    $root = (Resolve-Path -LiteralPath $ProjectRoot).Path
    $runner = Join-Path $root 'diagnostics\run_live_intelligence.py'
    if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw 'Runner missing. Fetch and check out the integration PR branch first.' }
    $pythonArgs = @()
    if ($PythonExe) { $python = (Resolve-Path -LiteralPath $PythonExe).Path }
    else { $python = (Get-Command py -ErrorAction Stop).Source; $pythonArgs = @('-3.11') }
    & $python @pythonArgs -c 'import sys; assert sys.version_info[:2] == (3,11); import flask, jsonschema, tzdata'
    if ($LASTEXITCODE -ne 0) { throw 'Install requirements with py -3.11 -m pip install -r requirements.txt, then retry.' }
    if ($SessionConfig) {
        $SessionConfig = (Resolve-Path -LiteralPath $SessionConfig).Path
        Push-Location -LiteralPath $root
        try { & $python @pythonArgs -c 'import sys; from iat.session_config import load_session_config; load_session_config(sys.argv[1])' $SessionConfig }
        finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { throw 'Session configuration rejected. Use reviewed evidence; never change approval flags to force acceptance.' }
    }
    if ($ValidateOnly) {
        Write-Output 'VALIDATE_ONLY: runner, Python and dependencies checked. No terminal, network, journal, or service started. WAIT; execution disabled.'
        exit 0
    }
    & $python @pythonArgs -c 'import MetaTrader5'  # Import only; no terminal attachment here.
    if ($LASTEXITCODE -ne 0) { throw 'Install the official optional package with py -3.11 -m pip install MetaTrader5, then retry.' }
    $inUse = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($inUse.Count -gt 0) { throw "Port $Port is occupied. Stop the old dashboard in its own window with Ctrl+C, or choose -Port. No process was stopped." }
    if (-not $LogParent) { $LogParent = Join-Path (Split-Path -Parent $root) 'IAT3-LiveLogs' }
    $parent = [IO.Path]::GetFullPath($LogParent)
    $prefix = $root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if ($parent -eq $root -or $parent.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Choose -LogParent outside the project to keep observations private.' }
    $log = Join-Path $parent ([Guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $log) { throw 'Journal already exists; rerun to allocate a new directory.' }
    $argsForRunner = @($runner, '--log-directory', $log, '--interval', "$Interval", '--port', "$Port")
    if ($SessionConfig) { $argsForRunner += @('--session-config', $SessionConfig) }
    Write-Output "New private journal: $log"
    Write-Output "Dashboard: http://127.0.0.1:$Port ; DEMO and disabled terminal/API permissions required."
    Write-Output 'Formal V3 live provenance is restricted. Descriptive observations remain unqualified. AI disabled; WAIT; execution disabled.'
    & $python @pythonArgs @argsForRunner
    exit $LASTEXITCODE
}
catch {
    # No provider/account exception text; these errors come only from local setup.
    Write-Error $_
    exit 1
}
