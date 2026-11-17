# IAT 2.0 live read-only intelligence and dashboard v1

**Start MT5 → Start IAT → Open dashboard → Observe.** No terminal credentials,
orders, demo orders, permission changes or historical qualification are involved.

## Development base and integration

This feature is based on exact PR #32 head
`6f5dae9bc531cf2bb6d7ee5da0e58ca52b0dbd49`, including corrected PR #31 and PR #29.
The new draft targets `feat/iat2-exness-historical-intake-v1`. No existing PR is
merged/rebased, and the historical CSV workflow is not assumed complete.
Its acquisition timestamp and dataset qualification remain unresolved.

The additive runner and dedicated Flask app do not modify `/analyze`, existing
research APIs, strategy rules, thresholds, session calendars or qualification gates.
The integration reuses `get_candle_snapshot`, `assess_candles`, `ClockGuard`, the
existing pure `frame_report`/context detectors, canonical evidence identities,
confluence, `context_at`, scenario assessment and scenario transitions.

There are two explicitly separate layers:

* **Descriptive observations:** validated closed, contiguous received candles can
  produce swings/HH/HL/LH/LL, BOS/CHoCH, patterns, zones, liquidity, momentum,
  volatility and diagnostic evidence weights through the existing pure detectors.
  This is not a forged eligible ContextReport. Without verified sessions these
  observations are labeled `DESCRIPTIVE_UNVERIFIED_SESSION`; confluence retains
  upstream blocked-quality limitations and never selects a hypothesis.
* **Session-gated scenario assessment:** the unchanged `VALIDATED_LIVE` context
  path requires an independently verified calendar. Its report feeds the unchanged
  scenario/transition modules. BUY_SCENARIO / SELL_SCENARIO are displayed only for
  an existing ASSESSED directional selection, never from descriptive scores or an
  LLM. ABSTAINED/BLOCKED contexts remain WAIT. Data failures produce
  DATA_UNAVAILABLE and quarantine old directions, quotes and charts.

The existing Exness candidate is not promoted or silently replaced with a weekly
schedule. A connected terminal can therefore show actual observations while the
assessment remains WAIT. Unknown sessions, insufficient confirmed structure,
opposing evidence and unchanged confluence thresholds can all require WAIT.

## Windows 10 / Python 3.11 commands

Use the actual project checkout at `E:\IAT2\IAT2-Latest`. Preserve local edits;
do not reset a dirty working tree. Fetch/switch the feature branch normally if it
is not already checked out:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git status --short
# Continue only after resolving/preserving any local edits.
git fetch origin feat/iat2-live-intelligence-dashboard-v1
git switch feat/iat2-live-intelligence-dashboard-v1
git pull --ff-only

py -3.11 --version
# Explicit operator installation from the existing project requirements/PyPI;
# the observer itself never downloads or installs anything.
py -3.11 -m pip install -r requirements.txt MetaTrader5
```

1. Open MT5 and connect to the already-authorized Exness **demo** terminal.
2. Make exact symbol **XAUUSD** visible in Market Watch manually.
3. Keep terminal **Algo Trading OFF** and **external Python API trading disabled**.
   The observer checks both and reads only `account_info().trade_mode` to confirm
   demo mode. It never reads account numbers/server names or changes settings.
4. In PowerShell, start the observer with a NEW log directory outside the repo:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
$logs = Join-Path 'E:\IAT2\IAT2-LiveLogs' ([Guid]::NewGuid().ToString('N'))
py -3.11 diagnostics/run_live_intelligence.py `
  --log-directory $logs --interval 10 --port 8765
```

5. Leave that window running. In a **second** PowerShell window, or manually in
   your browser, open the dashboard:

```powershell
Start-Process 'http://127.0.0.1:8765/'
```

Use Ctrl+C in the server window to stop. This shuts down the observer and closes
only the Python binding when the worker has stopped; it never closes positions
or alters the terminal's permissions. If attachment failed before MT5 was opened,
start MT5 then restart the runner with a new log directory. An unavailable package
or terminal produces DATA_UNAVAILABLE, never test prices. Startup failure is exit
1; CLI syntax error is 2; normal shutdown is 0.

`--interval` accepts integers **2–60 seconds**, default 10. Port defaults to 8765
and must be 1024–65535. The app always binds `127.0.0.1`, with debug/reloader OFF.
It has only GET dashboard/assets/settings/snapshot routes; no order, login,
configuration-write or trading endpoints. Remote clients and unexpected Host
headers are rejected. Multiple tabs read the same cached observation and cannot
trigger extra terminal reads. The background worker is separate from the HTTP
cache lock; a stalled MT5 request cannot hold the dashboard request lock.

You may add `--session-config` only for a legitimate current independently verified
calendar supported by the existing validator. A valid-but-unverified/expired
candidate still blocks the ordinary scenario gate; an invalid config blocks
startup. Do not reuse dated November 11–13 evidence as current session coverage,
edit assurance flags to force success, or assume the historical export and live
terminal feed are identical. No session config is needed merely to observe the
strictly validated descriptive subset; it is still WAIT without eligibility.

## What the dashboard displays

* Actual observed MT5 **Bid**, API quote timestamp, quote age, acquisition start/end,
  local OS acquisition time, per-frame closed cutoffs and candle ages.
* A closed M1 close-price line, M1/M5 structures, confirmed swings and events,
  candlestick patterns, momentum/volatility, support/resistance, supply/demand,
  pools/sweeps and canonical descriptive evidence references.
* Existing bullish/bearish/neutral hypothesis rankings, supporting/contradictory
  IDs, assumptions and invalidation criteria **when the ordinary gate passes**.
  Scores remain uncalibrated research heuristics, not probabilities or forecasts.
* A separate operational `signal=WAIT` and permanent execution-disabled banner.
  Research scenario labels are never broker signals or trade recommendations.
* Honest model status. The default is **DISABLED**, with deterministic explanations.

Missing bars/prices, stale ticks, malformed responses, unclosed bars, backward
clock movement, non-demo accounts, enabled trading permissions, incomplete warm-up,
M1/M5 OHLC mismatch or missing symbol visibility produce DATA_UNAVAILABLE. The
browser also clears previous data on failed/timed-out refreshes. Long refresh
settings do not extend the 30-second quote freshness limit. A stalled observer
is withheld rather than presenting an old assessment as current.

## MT5 timestamp, candle and source contracts

The existing provider uses position **1** for 500 M1 and 100 M5 bars. Position zero
(the forming candle) is never requested or analyzed. Live Bid is a separate
observation and may be newer than the last closed-candle assessment. The M1 close
sets the causal cutoff; later M5 closes are excluded from analysis, while raw
received rates remain in the source log. Both frames are rechecked at a common
UTC acquisition clock and again against the causal cutoff.

[MT5 Python documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py)
defines returned bar timestamps as UTC epoch values. This API contract is not a
claim that broker/server wall-clock displays use UTC. Original numeric epochs are
retained; broker wall-clock time is explicitly null/unavailable and never inferred
or converted. Quote epoch/millisecond inconsistencies, a quote more than two
seconds ahead of the local UTC clock, or older than 30 seconds are rejected.
Acquisition over 10 seconds is rejected. Local OS clock correctness is not
independently certified by these checks. Mismatched tick offsets are not silently
"fixed" by timezone conversion.

Continuity uses the unchanged calendar-free validator for descriptive source
quality. Unverified gaps cannot be classified as legitimate closures. Because
100 M5 bars span 8h20m, a daily break inside that window can block descriptive
analysis until a sufficient contiguous window is available. This version does not
invent bars or silently drop a gap to force the lookbacks to pass.

Overlapping complete groups of five M1 bars are compared with received M5 using
the unchanged intelligence epsilon. Native M5 is never regenerated or substituted.
The live snapshot is not evidence that the historical CSV export used the same
feed. Session assurance/finality remain subject to existing gates. A changed
eligible assessment at an identical closed cutoff is withheld as a detected
closed-evidence revision; repeats do not invent new transition events.

## Private append-only observation logs

The runner refuses existing log destinations, repository descendants and symlink
output ancestry. Each run needs a new private directory. It creates:

* `raw-candles.jsonl`: whitelisted API candle fields, original numeric epochs,
  position/count and a content hash. Identical successive candle bundles are not
  duplicated; updated bundles append a new record. Malformed nonnumeric values
  are represented as invalid-type markers rather than echoed private strings.
* `research.jsonl`: acquisition/quote timestamps, snapshot ID, source hash,
  cutoff timestamps, deterministic intelligence, scenario/transition, evidence
  references, reasons, quality and model status, and all execution-disabled flags.
  Entries link to the previous entry's SHA-256.

Writes append, flush and fsync; they never rewrite prior records. The single
observer is the only writer. File publication is not a transaction across both
logs. A logging error withholds the dashboard assessment with SHADOW_LOG_FAILED.
Do not edit active logs or reuse their directory on restart. Content hashes prove
internal identity, not broker authenticity. Logs contain market observations;
keep them private, outside Git, and do not upload them by default. Full research
records can grow quickly during long runs; monitor disk space, stop the observer
before archiving, and use a suitable bounded interval. There is no automatic
rotation/deletion or profitability analysis.

## AI boundary

Repository inspection found no suitable existing LLM provider architecture. No
hosted model, model name or API key is fabricated, and no new network client is
bundled. Pure deterministic reasoning is the working default.

Library users/tests may inject an optional presentation adapter. It receives only
the deterministic assessment, allowed evidence IDs and existing statements—no raw
terminal/account data. Its strict response may select only those existing
statements/IDs and must preserve the assessment. Free text, arbitrary fields,
new evidence and any changed WAIT/direction are rejected, with model status
UNAVAILABLE and deterministic fallback. ACTIVE means that injected presentation
adapter succeeded, not that a particular hosted LLM was independently verified.
There is no model configuration surface in the dashboard or CLI and no execution
capability in the adapter.

## Testing and actual-terminal validation still required

`tests/test_live_observer.py` uses explicitly SYNTHETIC mock transport. It covers
closed/partial/future candles, ambiguity, disconnects, stale/malformed data,
insufficient history, disagreement, model failures/conflicts, append-only logs,
worker startup, credential-free mocked Windows runner, dashboard safety/status,
clock changes and zero order calls. Linux/Windows CI runs 3.11/3.12 full suites.
Chromium desktop/mobile smoke checks used a clearly labeled synthetic server,
including disconnect clearing and reconnect; these are not broker validation.

On the actual Windows demo terminal, record these checks locally:

1. Start with the two trading permissions disabled, demo mode and XAUUSD visible.
2. Verify that an observed Bid/timestamp agrees with the terminal, that M1/M5
   cutoffs are closed, and that no forming bar enters the descriptive chart.
3. Inspect current quality/assurance reasons. WAIT without verified sessions is
   expected; do not change a gate to obtain BUY_SCENARIO/SELL_SCENARIO.
4. Disconnect the terminal temporarily. Confirm DATA_UNAVAILABLE and that old
   quotes/charts/directional assessments clear; reconnect and observe recovery.
5. Inspect local logs for timestamps, source hashes, evidence and disabled flags.
   Share only a separately reviewed/redacted summary if needed, never credentials.

Codex Cloud cannot perform this terminal test. Actual Windows live-feed validation
remains pending until the operator runs the observer and the evidence is reviewed.
Exness BLOCKED; DATA_NOT_QUALIFIED; historical validation PENDING; comparisons
NOT_RUN; operational WAIT; execution_allowed=false; broker_access=false for
execution; read-only market-data access explicitly authorized; orders_requested=0;
profitability_tested=false. No live/demo orders are submitted by this workflow.

## Recovery: LiquidityEvent JSON serialization failure

The initial live observer could pass nested `Zone`, `LiquidityPool` and
`LiquidityEvent` dataclasses directly from the pure context detectors into its
snapshot hash. Flat fixtures did not populate those collections; non-flat market
observations exposed `TypeError: Object of type LiquidityEvent is not JSON
serializable`. The hash was outside the processing exception boundary, so the
background worker could stop while Flask remained running.

The correction recursively converts dataclasses and tuples to structured JSON
objects/arrays before finite-value checks. It preserves fields, canonical IDs,
prices and chronology. Unsupported objects and nonfinite values are rejected;
there is no `default=str`, dropped evidence or permissive NaN hashing. The final
snapshot normalization/hash boundary now returns DATA_UNAVAILABLE with
`SNAPSHOT_SERIALIZATION_FAILED` and clears the previous assessment on failure,
allowing the worker to continue. Detector rules, scores and all gates are unchanged.

Stop the old server with Ctrl+C. On the operator's untracked local branch, fetch
and create a new local branch without requiring automatic remote tracking:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git fetch origin refs/heads/feat/iat2-live-intelligence-dashboard-v1
git switch --no-track -c local/iat2-live-json-fix FETCH_HEAD
$logs = Join-Path 'E:\IAT2\IAT2-LiveLogs' ([Guid]::NewGuid().ToString('N'))
py -3.11 .\diagnostics\run_live_intelligence.py --log-directory $logs --interval 10 --port 8765
```

If that local branch name already exists, choose a new local name; do not force
reset or discard edits. No dependency reinstall is required. Use the new log
directory and reopen/refresh http://127.0.0.1:8765/. The standard Flask development
server notice is expected for this local prototype. Review feed/quality status;
fixing serialization does not establish broker session eligibility or guarantee a
directional research assessment. Execution remains disabled; orders_requested stays 0.

Five added regressions use a labeled non-flat synthetic feed, preserving native-
shaped M1/M5 consistency while producing actual detector dataclasses. They cover
JSON/hash/HTTP/log serialization, exact field and ID preservation, nested nonfinite
rejection, guarded failure/recovery and background-worker continuation. Real
Windows terminal validation must still be performed locally by the operator.
