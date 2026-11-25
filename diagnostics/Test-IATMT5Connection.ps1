# Read-only, sequential interpreter/attachment comparison. Never starts dashboard/B.2/B.3.
[CmdletBinding()]
param(
    [string]$RunnerPythonExe = '',
    [string]$IndependentPythonExe = '',
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
try {
    if (-not $RunnerPythonExe) {
        $RunnerPythonExe = (& py -3.11 -c 'import sys; print(sys.executable)')
        if ($LASTEXITCODE -ne 0) { throw 'PYTHON_REQUIRED' }
    }
    if (-not $IndependentPythonExe) { $IndependentPythonExe = $RunnerPythonExe }
    $runner = (Resolve-Path -LiteralPath $RunnerPythonExe).Path
    $independent = (Resolve-Path -LiteralPath $IndependentPythonExe).Path
    $probe = Join-Path $PSScriptRoot 'mt5_connection_probe.py'
    $nonce = [Guid]::NewGuid().ToString('N')
    $probeArgs = @($probe, '--comparison-nonce', $nonce)
    if ($ValidateOnly) { $probeArgs += '--inspect-only' }
    $a = (& $runner @probeArgs | ConvertFrom-Json)
    if ($LASTEXITCODE -ne 0) { throw 'RUNNER_PROBE_FAILED' }
    $b = (& $independent @probeArgs | ConvertFrom-Json)
    if ($LASTEXITCODE -ne 0) { throw 'INDEPENDENT_PROBE_FAILED' }
    $sameTerminal = $null
    if ($a.attachment_token -and $b.attachment_token) { $sameTerminal = ($a.attachment_token -eq $b.attachment_token) }
    # Tokens are only for this comparison and are not emitted as machine identifiers.
    $a.PSObject.Properties.Remove('attachment_token')
    $b.PSObject.Properties.Remove('attachment_token')
    [ordered]@{
        comparison_version = 1
        validate_only = [bool]$ValidateOnly
        same_executable_path = [string]::Equals($runner,$independent,[StringComparison]::OrdinalIgnoreCase)
        same_python_binary = $(if ($null -eq $a.executable_sha256 -or $null -eq $b.executable_sha256) { $null } else { $a.executable_sha256 -eq $b.executable_sha256 })
        same_mt5_module_binary = $(if ($null -eq $a.mt5_module_sha256 -or $null -eq $b.mt5_module_sha256) { $null } else { $a.mt5_module_sha256 -eq $b.mt5_module_sha256 })
        same_mt5_package = $(if ($null -eq $a.mt5_package -or $null -eq $b.mt5_package) { $null } else { $a.mt5_package -eq $b.mt5_package })
        same_terminal_attachment = $sameTerminal
        runner_environment = $a
        independent_environment = $b
        historical_process_identity = 'UNVERIFIED_OPERATOR_MUST_SELECT_ACTUAL_INTERPRETERS'
        signal = 'WAIT'
        execution_allowed = $false
        exness = 'BLOCKED'
        qualification = 'DATA_NOT_QUALIFIED'
        historical_validation = 'PENDING'
        historical_comparisons = 'NOT_RUN'
        mode = 'READ_ONLY_SHADOW'
    } | ConvertTo-Json -Depth 12
    exit 0
}
catch {
    Write-Error 'COMPARISON_FAILED: verify both local Python executable selections and package installation privately. No exception text or local path is published. No service was started.'
    exit 1
}
