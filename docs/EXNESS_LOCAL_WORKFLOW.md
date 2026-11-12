# Exness demo: reproducible blocked-calendar workflow

This PR supplies an exact, schema-valid **review candidate**, not an active or
broker-certified calendar. Research found unresolved phase/holiday/maintenance
information; the safe current result is **BLOCKED / FAIL**. The original weekly
boundaries are not altered to make tests or M5 validation pass. See
[research and sources](EXNESS_SESSION_RESEARCH.md).

## Files and trust boundary

- `config/profiles/exness-xauusd-observed-winter-2026-11.json`: strict v1 XAUUSD/UTC
  candidate with the user's exact supplied display times and fixed coverage.
- The adjacent `.review.json`: access date, official URLs, applicability,
  uncertainties and SHA-256 of the exact candidate bytes.
- `iat/exness_profile.py`: consistency checks, offline inspection and safe local
  installation. `.gitattributes` preserves LF bytes across Git/ZIP/Windows.
- `IAT_UNVERIFIED:` in the existing source field compiles to immutable assurance
  holds. This is a **deny-only marker**, not authentication. Removing it or
  relabeling a source does not establish verification. The installer never does
  that, and no activation/force-ready switch is provided.

The existing generic trusted-host calendar interface is preserved. This change
is not a new universal broker-authentication system. For marked candidates, the
library and API reject analysis even if calendars are passed directly as objects.
The demo diagnostic emits all hold codes and M5 incompatibility before importing
or initializing MT5; it does not reuse the user-reported connection state as a
successful test. Output is redacted through the existing evidence schema.

## Update reviewed source first

The local root supplied for this task is:

```text
E:\IAT2\Trading-ai-feat-iat2-windows-demo\Trading-ai-feat-iat2-windows-demo
```

Review/update the source in that folder to branch `feat/iat2-exness-calendar`
without merging PRs. A ZIP extraction does not update automatically; if this is
not a Git checkout, review the new branch's files before updating local source.
No source or configuration on E: has been changed by Codex Cloud.

Use the user's existing **Python 3.11.9 x64** environment. After activating it,
run from PowerShell:

```powershell
Set-Location 'E:\IAT2\Trading-ai-feat-iat2-windows-demo\Trading-ai-feat-iat2-windows-demo'
$Python311 = (Get-Command python).Source
& $Python311 --version
& $Python311 -m pip --isolated --disable-pip-version-check install `
  --index-url https://pypi.org/simple --only-binary=:all: -r .\requirements.txt
```

This reuses the environment and installs required wheels, including Windows IANA
tzdata. It does not download a Python installer, enable trading, ask for login
inputs, or run remote scripts. Review local script signing/execution policy using
your normal process; no policy bypass is provided.

## Inspect and install

Optional offline inspection (no MT5 dependency/access):

```powershell
& $Python311 .\diagnostics\install_exness_calendar.py --inspect
$LASTEXITCODE
```

Exit **2** means inspection succeeded but readiness is BLOCKED. It is not a broker
PASS. The output separates schema validity, runtime readiness, original M5
alignment failure, fixed coverage/expiry, and theoretical M5 grid capacity.

Install the reviewed artifact:

```powershell
.\diagnostics\Install-IATExnessCalendar.ps1 -PythonExe $Python311
$LASTEXITCODE
```

The default destination is exactly:

```text
E:\IAT2\Trading-ai-feat-iat2-windows-demo\Trading-ai-feat-iat2-windows-demo\config\local\exness-xauusd-observed-2026-11.json
```

Successful installation also exits **2** because the installed file remains
blocked. Exit 1 means refusal/error. The helper validates the candidate and staged
bytes through the strict runtime loader, preserves the checksum, and never
contacts MT5. New files are validated in staging and published atomically without replacing
an existing target, including one created concurrently. Interrupted staging
does not publish an approved configuration.
The local destination is Git-ignored.

If that destination already exists, PowerShell asks for explicit replacement
confirmation. Declining, unavailable/noninteractive confirmation, a changed
current-file digest, or a publication error preserves the existing configuration.
`-WhatIf` performs no write. The Python helper also refuses existing files by
default. There is no silent overwrite or blanket `-Force`; confirmed replacement
flags apply only to storage, never to removing assurance holds.

## Run the existing read-only demo diagnostic

Keep terminal Algo Trading disabled and external Python API trading disabled.
Keep the intended demo terminal connected with XAUUSD visible; these are local
preconditions, not evidence the cloud can assert. Then run:

```powershell
$Candidate = Join-Path (Get-Location) 'config\local\exness-xauusd-observed-2026-11.json'
$Evidence = Join-Path (Get-Location) 'evidence'
.\diagnostics\Run-IATDemoValidation.ps1 `
  -PythonExe $Python311 `
  -SessionConfig $Candidate `
  -ReportDirectory $Evidence
$LASTEXITCODE
```

**Expected now: exit 1 / FAIL**, before MT5 import/initialization, with:

- `CALENDAR_SCHEDULE_CONFLICT`
- `CALENDAR_PHASES_UNREPRESENTABLE`
- `HOLIDAY_COVERAGE_UNKNOWN`
- `MAINTENANCE_COVERAGE_UNKNOWN`
- `SESSION_ALIGNMENT_INVALID` for M5
- additionally `SESSION_COVERAGE_UNKNOWN` after expiry/before coverage

No actual closed candles are fetched while these holds remain. Validated counts,
gaps and freshness remain null; `signal=WAIT`, `execution_allowed=false`, and
`binding_initialization_attempted=false`. This is a successful test of fail-closed
handling, **not** successful market-data/broker validation. Optional weekly
metadata, a matching screenshot, or a confirmed demo login cannot clear these
holds. Generic known closed sessions/weekly-only metadata may produce WARN in
other reviewed configurations; this candidate's missing assurance is a blocker.

The runner creates a new `iat-demo-*.json` and never overwrites prior reports.
Inspect the newest redacted report locally:

```powershell
$Latest = Get-ChildItem -LiteralPath $Evidence -Filter 'iat-demo-*.json' |
  Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
$Report = Get-Content -LiteralPath $Latest.FullName -Raw | ConvertFrom-Json
$Report | Select-Object run_id, started_at_utc, finished_at_utc, status
$Report.diagnostics | Select-Object code, severity, explanation
$Report.timeframes.M1
$Report.timeframes.M5
$Report.safety
```

Check this invocation's exit code, unique filename/run_id and UTC timestamps; a
previous report is never evidence of a new run. Do not print/share raw terminal,
account, server, configuration-provenance or bridge objects. The generated report
uses a symbol alias and fixed explanations; it contains no account or server ID.
Raw calendar/research files are separate from the shareable diagnostic report.

## M5 boundary policy and next milestone

The unchanged validator requires every session boundary in coverage to align to
the requested timeframe. `21:58 % 5 != 0` and `23:01 % 5 != 0`; consequently M5
fails even for a midday request. Structurally M1 aligns to the display minutes,
but minute alignment cannot establish the published half-minute phase semantics.

Do not move 21:58 to 21:55/22:00, change Sunday opening to 23:00/23:05, infer a
holiday closure, or filter/impute partial candles to obtain PASS. Terminal bar
behavior near partial sessions must be observed and reviewed separately. First
reconcile dated broker phases/holiday/maintenance evidence, then design a
versioned phase-capable calendar and independently validate partial-bar handling.
A separately reviewed future profile is required; this fixed candidate is never
automatically renewed or activated.

## Test evidence

The complete offline suite passes **195 tests** on Python **3.11.9** and **3.12.14**.
CI uses Linux and Windows with 3.11.9/3.12, including PowerShell installation,
unavailable replacement confirmation and blocked-report publication checks.
Regressions cover exact Sunday/weekday/Friday/Saturday boundaries, source/hash
consistency, missing holidays, second-level phase incompatibility, UTC versus US
DST, fixed expiry, no overwrite, atomic failure, library/API/diagnostic holds,
and redacted preflight with no terminal access. No local E-drive installation,
actual OHLC, real terminal or broker certification is claimed from these tests.
