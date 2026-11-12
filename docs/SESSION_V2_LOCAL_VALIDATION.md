# Session v2 local research and evidence procedure

No actual local terminal has been tested in Codex Cloud. All broker/account
interactions in automated tests are mocked. Keep Algo Trading and external
Python trading disabled, use only the already authorized demo account, and do
not enter credentials in source/configuration/CLI arguments. No account switching
or orders are implemented.

## Update local source before running anything

The supplied folder predates PR #6 and must be reviewed/updated to
`feat/iat2-session-engine-v2` first. A ZIP extraction does not automatically update.
Do not assume that branch names in an existing folder prove its contents. No file
on the local E: drive was changed by the cloud session; no PR needs merging.

Use the existing Python 3.11.9 x64 environment, activate it and run:

```powershell
Set-Location 'E:\IAT2\Trading-ai-feat-iat2-windows-demo\Trading-ai-feat-iat2-windows-demo'
$Python311 = (Get-Command python).Source
& $Python311 --version
Test-Path '.\diagnostics\session_v2_research.py'
& $Python311 -m pip --isolated --disable-pip-version-check install `
  --index-url https://pypi.org/simple --only-binary=:all: -r .\requirements.txt
```

If the file check is false, stop and update reviewed source. Dependencies include
Windows IANA tzdata. The new research runner installs nothing, does not change
execution policy, and uses only reviewed repository scripts. Follow normal local
signing/review procedures if PowerShell policy blocks them.

## Default Exness candidate: BLOCKED without terminal access

```powershell
$Candidate = '.\config\profiles\exness-xauusd-v2.candidate.json'
$Evidence = Join-Path (Get-Location) 'evidence'
.\diagnostics\Run-IATSessionResearch.ps1 `
  -PythonExe $Python311 -SessionConfig $Candidate -ReportDirectory $Evidence
$LASTEXITCODE
```

Expected: **3 / BLOCKED**. The report records exact quote/phase geometry,
configuration fingerprint, dated coverage, outstanding requirements and null
missing counts where no observations exist. It does not invent observed candles.
The original v1 installer/profile remains separate and blocked; this command
reads the reviewed v2 source and overwrites no user configuration.

Even requesting capture does not bypass assurance:

```powershell
.\diagnostics\Run-IATSessionResearch.ps1 `
  -PythonExe $Python311 -SessionConfig $Candidate -ReportDirectory $Evidence -CaptureDemo
```

Expected again: BLOCKED **before importing/initializing MT5**. A connected demo
account with disabled execution does not resolve conflicting session evidence,
unknown holidays/maintenance or unverified finality. No force/skip-approval flag
exists. A freshly reviewed future v2 profile is required for eligible collection.

The existing ordinary demo runner also accepts the v2 config, retains WAIT and
execution false, and reports FAIL (exit 1) with additive `session_v2` state while
holds remain. Research's BLOCKED status intentionally distinguishes readiness
from failed observed data; neither means broker validation succeeded.

## Offline observation comparison

A private timestamp-only file has exactly `version:1` and `frames`, whose M1/M5
values are arrays of `{timestamp, finalized}`. Timestamps are aware ISO values;
finalized is boolean or null. They are assertions from that file, not proof.
There are no OHLC prices or credential fields in this observation format.

The following is an **explicitly synthetic shape example**, never an actual
terminal capture:

```json
{"version":1,"frames":{"M1":[{"timestamp":"2026-11-12T23:00:00Z","finalized":null}],"M5":[{"timestamp":"2026-11-12T21:55:00Z","finalized":null}]}}
```

```powershell
.\diagnostics\Run-IATSessionResearch.ps1 `
  -PythonExe $Python311 -SessionConfig $Candidate -ReportDirectory $Evidence `
  -Observations 'C:\IAT\private-evidence\observed-timestamps.json'
```

File provenance is always FILE_UNVERIFIED; a file cannot assert that this harness
performed a real-terminal test. The Exness profile remains BLOCKED. Geometry can
still be classified for research with verification false. Partial/restricted/
unknown/unfinalized inputs never reach an ordinary strategy.

Each timeframe reports observed/full/partial/outside counts and a separate
unknown-verification count. Geometry counts and unknown confidence can overlap:
a nominal full quote interval may still have unverified phases. Boundary samples
are capped at 16 and contain only UTC geometry, states and finality status. Missing
full versus missing partial intervals are distinguished. Counts are provisional
against the configured schedule while assurance is blocked; they are not proof
of missing broker data. A bounded 20,000-interval comparison prevents unbounded
sparse-history scans; exceeding it fails with missing counts left null. There
are at most 5,000 observation rows per timeframe and 1 MiB per input file.

## Future independently eligible demo capture

Only after dated quote/trade, holidays, maintenance and full-bar finality evidence
is independently reviewed and all mandatory requirements are satisfied may a
separate reviewed profile be used for `-CaptureDemo`. Do not flip declarations
in the candidate or synthetic example simply to make capture run.

Capture reuses the existing terminal-connectivity, demo-mode, XAUUSD visibility/
asset metadata and disabled-trading gates. A restricted adapter exposes only
read-only methods plus binding initialization/shutdown. It records only the
actual returned candle timestamps, never prices/account objects. Both M1/M5 use
position 1, and the ordinary validator still checks the returned OHLC privately.
Partial or malformed history remains a failed ordinary request; capture does not
filter it into success. Partial finality remains unknown.

Standard MT5 usually lacks dated phase metadata. Optional `-BrokerMetadata`
accepts an independently reviewed local file following the phase metadata
contract in [the architecture document](SESSION_ENGINE_V2.md). A reviewed
read-only bridge may expose the same contract. Coarse weekly metadata does not
certify phases; no bridge is auto-downloaded. Use `-TerminalPath` only to select
the intended trusted installed terminal executable when needed. No login inputs
are accepted. IAT execution remains false even if broker FULL_TRADING permits it.

## Reports, statuses and redaction

| Exit | Status | Meaning |
| --- | --- | --- |
| 0 | PASS | Scoped live-demo research comparisons completed with no uncertainty; never independent broker certification. |
| 2 | WARN | Unverified file/synthetic provenance, unavailable/coarse broker metadata, or absent observations. |
| 1 | FAIL | Invalid observations/config, missing/full/partial/restricted/unfinalized ordinary data, clock/provider/safety/shutdown or publication error. |
| 3 | BLOCKED | Calendar evidence/coverage/expiry requirements remain unresolved; no live capture occurs. |

Critical malformed observations or broker mismatch fail even if a calendar is
otherwise blocked. Unknown calendar information never becomes PASS. Synthetic
provenance always warns, including when paired with a native provider. The
report always states `ordinary_strategy_inputs_emitted=false`, orders zero,
credentials false, independent broker certification false and execution false.

The new report kind is SESSION_V2_RESEARCH, separate from the compatible ordinary
report. It exposes only source kinds/counts and a canonical config hash, not raw
references/IDs, symbols/suffixes, server labels, account fields or provider error
text. Numeric timestamps/phase geometry are not account identifiers. Refer to
private configuration separately for provenance review. A hash identifies bytes/
declarations, not authenticity or permission to trade.

Reports reserve RUN_INCOMPLETE/FAIL at a new filename and publish atomically after
validation/shutdown; existing files are refused. Invalid config can produce a
small SESSION_RESEARCH_PREFLIGHT failure envelope with a typed reason. A filesystem
or runner preflight failure can leave no new report; always check exit status,
run_id and timestamps, never an older success file. Hidden temporary files are
not completed evidence. The PowerShell wrapper discards child stdout/stderr,
including native-library output, and prints only status and a new basename.

Inspect the latest redacted research report:

```powershell
$Latest = Get-ChildItem -LiteralPath $Evidence -Filter 'iat-session-research-*.json' |
  Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
$Report = Get-Content -LiteralPath $Latest.FullName -Raw | ConvertFrom-Json
$Report | Select-Object run_id, as_of_utc, status
$Report.session_v2
$Report.requirements
$Report.frames.M1
$Report.frames.M5
$Report.broker_comparison
$Report.safety
```

Do not print/share raw terminal/account/bridge objects or private configuration
references. No current user server identifier is embedded in published artifacts.

## Remaining evidence and unblocking conditions

Obtain authoritative dated ordinary-XAUUSD quote/trade phase schedules and
applicability, clarify the conflicting first 30 seconds, establish holidays and
maintenance for the full covered interval, and independently observe actual M1/M5
partial/full candle behavior and the full-bar finality contract. Current coverage
expires 2026-11-16 UTC; do not silently extend it. Support for seconds removes a
representation limit, not any evidence requirement.

After review, a separate profile needs current nonfuture provenance, explicit
verified declarations, no unresolved holds, valid coverage/expiry and a tested
provider contract. Ordinary inputs still reject all partial/restricted/unknown
bars; no permissive partial-bar strategy policy is introduced. No broker-certified
profile or actual-terminal success is claimed here. No PR is merged.
