# Live AI reasoning and dashboard v2

Base: PR #33 corrected commit `25d7d3746aa6b1f52174049d0925938b9ef551c9`.
This feature adds a readable presentation and optional commentary provider to the
existing read-only observer. Existing strategy definitions, confluence weights,
session gates, scenario selection and historical qualification are unchanged.
The operator's reported v1 screenshot establishes one observed display only;
it does not establish continuous Windows MT5 stability or strategy performance.

## Windows update and normal startup — no model key required

Stop the old server with Ctrl+C. In the actual checkout, run these commands **one
at a time, top to bottom**, without copying `PS`, `>>` or trailing backslashes:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git status --short
# Preserve/resolve any local edits before switching. No reset or force checkout.
git fetch origin refs/heads/feat/iat2-live-reasoning-dashboard-v2
git switch --no-track -c local/iat2-live-reasoning-v2 FETCH_HEAD
```

This avoids the operator's earlier single-branch remote-tracking failure and
preserves the old local branch. If the new local name already exists, use a new
local name. No PR merge/rebase is performed. Dependencies are unchanged; if this
is a new environment, explicitly install the trusted project requirements and
optional Windows package with `py -3.11 -m pip install -r requirements.txt MetaTrader5`.
The application does not install or download dependencies automatically.

Start MT5 on the already-authorized demo terminal, make exact **XAUUSD** visible
in Market Watch, and keep **Algo Trading OFF** and **external Python API trading
disabled**. The observer checks demo `trade_mode`, never reads/prints account or
server identifiers, and never changes these permissions.

```powershell
$logs = Join-Path 'E:\IAT2\IAT2-LiveLogs' ([Guid]::NewGuid().ToString('N'))
py -3.11 .\diagnostics\run_live_intelligence.py --log-directory $logs --interval 10 --port 8765
```

Leave that window running. In a second window, or manually in your browser:

```powershell
Start-Process 'http://127.0.0.1:8765/'
```

The dashboard works completely without an LLM/API key. Model status is DISABLED
and every commentary section uses deterministic statements grounded in the
received evidence. A new private log directory outside Git is required on every
restart. Data acquisition remains the v1 read-only 500-M1/100-M5 position-one path.
Its verified-session requirement for formal scenarios remains intact, and strict
unverified gaps can still produce DATA_UNAVAILABLE.

## What changed in the dashboard

* Overview: actual Bid and timestamp, M1/M5 structure, alignment, formal regime,
  freshness, session eligibility, research assessment and operational WAIT.
* Interactive closed OHLC chart: M1/M5 switching, zoom, earlier/latest windows,
  hover/focus OHLC, click-to-inspect candle evidence and actual level overlays.
  It uses received closed candles only. Axis ticks are display scales, not prices
  added to the dataset. UI prices are displayed to at most six decimal places;
  exact calculation/source values remain in evidence and technical JSON.
* Human structure summaries: confirmed HH/HL/LH/LL/equal swings, BOS and CHoCH
  explanations, existing events, momentum and volatility. No new classification
  thresholds or indicators are introduced.
* Actual support/resistance, supply/demand and liquidity levels: timeframe, status,
  range/price and source references. The table presents at most 40 nearest-to-Bid
  rows, with invalidated levels optionally included. This is a display filter,
  not a strategy rule. The complete collection remains in technical JSON.
* Bullish/bearish evidence panels: supporting and opposing observations are
  separate. When the existing scenario engine has not evaluated a direction,
  the panel says NOT ASSESSED and supplies no invented formal conditions.
  Existing assumptions and invalidation conditions appear only when available.
* WAIT explanations distinguish session restrictions, missing confirmed swings,
  mixed structures, stale feeds, disconnected data and integrity/safety failures.
* Technical JSON is expandable rather than the primary presentation. Evidence
  links resolve original canonical IDs and original values in the inspector.
* The operational signal always stays WAIT and the execution-disabled indicator
  is permanent. Descriptive bullish/bearish evidence is not an executable signal.

An unverified session cannot be converted into a formally eligible scenario by
presentation or AI. With no verified current calendar, source observations can
still be useful while the research assessment remains WAIT. Formal market regime
stays UNKNOWN when the existing formal context is unavailable; a mixed alignment
is not silently reclassified as a trend or range. A screenshot is not source
certification, and no win rate, confidence probability or profitability is shown.

## Optional actual OpenAI provider

No suitable existing hosted provider was present; v1 had only an injected
presentation hook. V2 implements a fixed HTTPS OpenAI Chat Completions adapter,
using the existing `requests` dependency. It is never enabled automatically.

Only when the operator explicitly opts in:

```powershell
# Do not paste an API key into chat, source code, command arguments or Git.
$apiSecure = Read-Host 'OpenAI API key (optional)' -AsSecureString
$env:IAT_OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $apiSecure).Password
$logs = Join-Path 'E:\IAT2\IAT2-LiveLogs' ([Guid]::NewGuid().ToString('N'))
py -3.11 .\diagnostics\run_live_intelligence.py --log-directory $logs --interval 10 --port 8765 --enable-llm --llm-model 'gpt-4.1-mini' --llm-min-seconds 60
# Run these cleanup commands after stopping the server with Ctrl+C:
$env:IAT_OPENAI_API_KEY = $null
Remove-Variable apiSecure -ErrorAction SilentlyContinue
```

The model name above is an example structured-output model; access depends on the
operator's OpenAI account. `IAT_REASONING_MODEL` may alternatively provide the
model name. There is no model/key configuration endpoint in the browser. Requests
may incur the operator's provider charges. No real provider request was performed
in Cloud; CI uses mocked HTTP responses and no actual credentials.

The adapter sends only the XAUUSD symbol, a seven-claim approved wording packet, its bundle hash and
canonical evidence references. It sends no raw candle history, raw private logs,
account fields, server identifiers, broker credentials or observed Bid prices.
It does not send the whole live snapshot. No provider response body or prompt is
written to the journals. The authorization header/key is held in memory only.

The model chooses ordering and an approved wording variant for **every** claim,
including WAIT, opposing-direction status and safety. It cannot generate free
prose, price levels, new evidence or new scenario decisions. This constrained
editor design provides an enforceable grounding check; arbitrary model-written
market claims are intentionally unsupported. The wire response uses strict JSON
Schema, followed by stricter local checks for exact bundle/claim coverage, unique
claims, approved wording IDs and exact evidence-reference lists. Unsupported
fields (including confidence, prices or execution), omitted safety claims,
fabricated references, contradictory text and malformed/refused/truncated
responses are rejected. The visible text is reconstructed from validated local
statements, never from unvalidated model prose.

Transport behavior:

* Fixed `https://api.openai.com/v1/chat/completions`; no redirects or environment
  proxies/netrc credentials. Normal TLS verification remains enabled.
* Connect timeout up to 3 seconds, read timeout 8 seconds, streamed-body budget
  checked against 8 seconds, decoded response cap 64 KiB and output token cap.
  The isolated commentary thread never waits on the MT5 worker or blocks the
  HTTP dashboard. There is no automatic network retry.
* One provider request in flight; global minimum request interval defaults to
  60 seconds and is configurable from 30 to 3600 seconds. Successful and failed
  results are cached for up to 64 closed-evidence bundles. Failure is not retried
  repeatedly for unchanged evidence.
* Bid/acquisition-only updates do not cause new requests. Changed closed-candle
  evidence, gates or analytical configuration invalidates the commentary key.
  A result from a different bundle is never applied to a current snapshot.

DISABLED means no provider is configured. UNAVAILABLE means pending/rate-limited,
missing configuration, timeout, provider error or validation failure; deterministic
commentary remains available. ACTIVE is shown only after a successful, validated
provider request for the same evidence bundle. Cached success is explicitly
labeled cached and retains its commentary timestamp. An error response never
claims ACTIVE. The model cannot alter facts, source/evidence IDs, prices,
eligibility, operational state or execution flags.

## Snapshot compatibility and separate private journals

`/live/v1/snapshot` remains the original snapshot with the original `snapshot_id`
hash contract. V2 uses an additive `/live/v2/snapshot` envelope containing:

* `deterministic_snapshot`: the unchanged v1 object;
* `readable`: evidence-grounded presentation, linked by `source_snapshot_id`;
* `commentary`: separate deterministic/validated-provider text, status, timestamp,
  validation result, cache flag and evidence references;
* the envelope's independent SHA-256 and unchanged safety flags.

Malformed snapshot hashes/safety fields are quarantined before presentation. The
old v1 `ai_model` field retains its legacy presentation-hook meaning; actual v2
provider status is `commentary.status`. No v1 identity is rehashed to include AI.
Existing DecisionLog, Strategy Replay Log and historical gates are untouched.

`raw-candles.jsonl` and `research.jsonl` preserve their v1 append-only contracts.
New `commentary.jsonl` is a separate, hash-chained append-only journal with source
snapshot ID, claim-bundle ID, commentary timestamp, approved text/evidence IDs,
provider/model status and validation result. It stores no secrets or raw prompts/
responses. Repeated identical view/status reads are deduplicated. Commentary is
produced/logged when a v2 dashboard/view is requested; market research polling
continues when the browser is closed, without making LLM calls merely to fill logs.
A commentary-log failure falls back without changing the deterministic snapshot.
All journals remain local outside the repository. Disk usage still needs operator
monitoring; files are never silently overwritten or deleted.

## Local stability verification — exact commands

While the server runs, use a second PowerShell window to sample the **v1 local
read-only endpoint**, which does not trigger commentary/provider requests:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
$checks = 'E:\IAT2\IAT2-LiveChecks'
New-Item -ItemType Directory -Force -Path $checks | Out-Null
$report = Join-Path $checks ('stability-' + [Guid]::NewGuid().ToString('N') + '.json')
py -3.11 .\diagnostics\check_live_stability.py --seconds 360 --interval 5 --port 8765 --report-path $report
Get-Content -LiteralPath $report -Raw
```

The report retains metadata, counts, timestamps, cutoffs, reason codes and snapshot
IDs, not the full histories, Bid values, account data or raw logs. The sampler
retains one previous quote internally and bounded summary records, rather than
accumulating full snapshots in RAM. It checks snapshot identities and disabled
flags, quote/time progress, M1/M5 closed-cutoff transitions, disconnect/reconnect,
chronology and stale-state clearing. A flat Bid is not itself a failure.

* Exit **0** / PASS: this scoped local sampling observed the required progress
  without blocked/invalid samples. This is not independent broker certification.
* Exit **3** / WARN: missing progress (for example no M5 close transition in a
  short interval) or blocked samples. A deliberate disconnect exercise can
  reasonably produce WARN with observed recovery.
* Exit **3** / FAIL: no connected samples, invalid snapshots or safety violations.
* Exit **1**: invalid destination/parameters or report publication failure;
  argparse may return 2 for command syntax. Existing reports are never replaced.

Run once during ordinary observation. Separately, disconnect/reconnect MT5
manually and confirm that stale quote, chart, levels and selected evidence clear
and then recover. Compare displayed Bid/UTC timestamps with the actual terminal.
Review the reason codes and complete at least one M1 and M5 close transition.
The observer's outer worker boundary now catches unexpected polling faults,
records a safe unavailable snapshot and continues polling, without echoing errors
that could contain private details.

## Automated evidence and remaining limits

Automated tests use clearly labeled synthetic MT5 transport, advancing clocks,
non-flat zone/liquidity data and mocked OpenAI HTTP. They verify repeated polling,
Bid/time updates, new closes, recovery, nested serialization, readable output,
reference/identity preservation, strict rejection/fallback, timeout/cache/rate
behavior, separate journals and zero order calls. Browser checks cover readable
panels, collapsed JSON, chart hover/zoom/timeframe selection, evidence links,
desktop/mobile layout and disconnect clearing/recovery. No real terminal or model
request is inferred from synthetic test success.

Actual Windows MT5 continuous stability and a real configured provider request
remain operator validations. The existing strict 100-M5 continuity window and
unverified Exness session coverage can still block formal scenarios. Historical
CSV acquisition/qualification remain pending. No model can resolve those evidence
gaps or certify a calendar. Operational WAIT; execution_allowed=false;
broker_access=false for execution; read-only market-data access explicitly
separate; orders_requested=0; profitability_tested=false; Exness BLOCKED;
DATA_NOT_QUALIFIED; historical validation PENDING; comparisons NOT_RUN. All PRs
remain unmerged. No live or demo order call is introduced.
