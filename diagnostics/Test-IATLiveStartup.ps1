# Offline regression: actual Windows PowerShell 5.1 -File child processes.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PythonExe)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetDirectoryName($PSScriptRoot)
$script = Join-Path $PSScriptRoot 'Start-IATLiveMarketView.ps1'
$before = (Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash
$temp = Join-Path ([IO.Path]::GetTempPath()) ('IAT E1 startup regression ' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    Push-Location -LiteralPath $temp
    try {
        # Crucially: no ProjectRoot parameter; not dot-sourced, not & script.ps1.
        $result = & powershell.exe -NoProfile -NonInteractive -File $script -PythonExe $PythonExe -ValidateOnly 2>&1
        if ($LASTEXITCODE -ne 0 -or -not ($result -match 'VALIDATE_ONLY')) { throw 'Default project-root -File regression failed.' }
        $result = & powershell.exe -NoProfile -NonInteractive -File $script -PythonExe $PythonExe -ProjectRoot $root -ValidateOnly 2>&1
        if ($LASTEXITCODE -ne 0 -or -not ($result -match 'VALIDATE_ONLY')) { throw 'Explicit project-root override failed.' }
        if (@(Get-ChildItem -LiteralPath $temp -Force).Count -ne 0) { throw 'Validation-only unexpectedly wrote files.' }
    }
    finally { Pop-Location }
    if ((Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash -ne $before) { throw 'Startup source changed.' }
    Write-Output 'PASS: Windows PowerShell -File default root and explicit override; no SDK, service, journals or source changes.'
}
finally { Remove-Item -LiteralPath $temp -Recurse -Force }
