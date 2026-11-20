# Stage B.2 — live DEMO shadow recorder

Base: draft PR #38, `1defb60d02d0bc3809e3f78dd01cdc48d3ab84c6`.
This is an isolated **read-only research recorder**, not Stage C/D. It has no
order adapter, order/position-management calls, account switching or permission
changes. WAIT, execution_allowed=false, orders_requested=0, Exness BLOCKED,
historical validation PENDING and historical comparisons NOT_RUN are invariant.
Stage-B qualification is independent and remains pending. Both source strategies
remain EXPERIMENTAL_SYNTHETIC_ONLY. Nothing here qualifies a strategy or dataset.

Cloud tests demonstrate software behavior with synthetic data. **Actual Windows
MT5 Bid/Ask, tick-history availability, broker symbol terms and sustained capture
have not been independently tested here.** Local pilot acceptance remains pending.

## Architecture and compatibility

`ShadowFeed` retains only MT5 read callables. It reuses the original preflight:
connected DEMO, visible XAUUSD, Algo Trading OFF, external Python trading disabled.
It additionally checks the observed company label for Exness; this is not
provider authentication or atomic account binding. Account numbers, server labels,
passwords and tokens are not read or stored. The only retained account properties
are trade_mode and company; published identity uses fixed redacted labels.

The separate runner captures observed Bid AND Ask from one tick, closed position-1
M1/M5 rates, and bounded `copy_ticks_range` catch-up. No fixed spread or inferred
Ask is used. UTC millisecond epochs are the MT5 API time basis, not broker wall
clock. Missing/invalid Ask, crossed/nonpositive/nonfinite prices, future/stale
quotes, inconsistent epochs and ambiguous timestamp ordering fail closed.

The recorder has its own closed-candle checks, using the existing quality and
session engines, plus complete overlapping M1/native-M5 OHLC comparison. It never
replaces native M5. Original observer failures remain visible separately as
original_observer_status/reason_codes. The original observer's calculations,
operational WAIT and permission restrictions are not relaxed. The original APIs,
Gemini/OpenAI selection, Stage-A durability and Stage-B qualification code remain
unchanged. Optional runner arguments attach a **read-only** journal view to the
existing dashboard; the recorder does not consume any AI output.

## Descriptions, research and operational gates

The new endpoint is GET `/live/shadow/v1/snapshot`. Existing `/live/v1/snapshot`,
`/live/v2/snapshot`, `/live/v3/snapshot` and settings retain their contracts.
Absent an attached recorder, the new route returns SHADOW_DISABLED safely.

Separate fields report:

- descriptive_direction and M1/M5 structure;
- research_candidate: BUY_CANDIDATE, SELL_CANDIDATE, WAIT or BLOCKED;
- frozen assessment, source/evidence references and reason codes;
- actual decision available_at, distinct from analysis_at (M1 close);
- session diagnostics and safety_gate_outcome;
- operational signal WAIT and execution_allowed=false.

Existing experimental predicates and the Stage-B stop/target/volatility policy
are reused without threshold optimization. Both strategies and directions are
assessed independently; a single explicitly configured strategy gets the one
paper position. Bearish alignment alone cannot produce SELL_CANDIDATE.
Continuation requires the existing aligned structure, candle and zone predicates;
reversal requires the existing sweep and subsequent confirmed CHoCH predicates.
Fresh opposing CHoCH, anchor retirement, confirmed-stop availability and the fixed
relative-volatility filter remain relevant.

A frozen captured window is passed to the **existing offline** HISTORICAL_RESEARCH
API mode. This enum means experimental analysis of recorded observations; the
report explicitly records LOCAL_MT5_LIVE_FROZEN_CAPTURE_NOT_QUALIFIED. It is not
an authenticated historical export or a promoted VALIDATED_LIVE ContextReport.
A supplied calendar is always enforced and never discarded. With no calendar,
existing strict mechanical research checks can describe hypothetical candidates,
while the original VALIDATED_LIVE session gate remains blocked. **All shadow
trades are excluded from qualified performance statistics**, including those with
verified calendar declarations. Qualified performance metrics are always null.

Regime and volatility are reported using the existing adaptive engine, with
UNKNOWN preserved when evidence is insufficient. M1/M5 alignment, momentum,
volatility, original evaluations and supporting/contradictory IDs remain traceable.
No new indicators, scores or strategy rules are fitted to live observations.

## Why session_eligible may be false

The existing VALIDATED_LIVE path requires a verified session calendar. No supplied
calendar yields SESSION_CALENDAR_UNAVAILABLE in the original observer and
SESSION_CALENDAR_MISSING in shadow diagnostics. An unverified/expired calendar,
unknown holiday coverage, restricted phase or invalid candle can also block it.
The user's local runtime/configuration has not been remotely inspected, so code
inspection does not establish the exact cause on that machine.

New diagnostics distinguish missing evidence, unverified coverage, CALENDAR_EXPIRED,
verified-calendar CLOSED phases, CLOSE_ONLY/QUOTE_ONLY transitions, stale/missing Bid/Ask,
broker mismatch, symbol visibility/unsupported terms, transport and data errors.
Unverified or synthetic CLOSED phases are labeled UNVERIFIED_DECLARED_CLOSURE,
never ACTUAL_MARKET_CLOSURE; synthetic calendars cannot establish operational
eligibility. A verified declaration is still not independent terminal proof.
Quote permission and permission to open new positions are separate. For a verified
close-only phase: quotes may be true, new_positions false and close_positions true.
Neither permission grants IAT execution authority.

Do not extend the dated November 11–13 broker response to later dates or mark
holidays/maintenance verified without evidence. Existing Exness calendars and
assurance holds are unchanged. Calendar-free analysis cannot certify session gaps.
The full pipeline conservatively quarantines invalid/partial/restricted ordinary
candle context. Even though the quote simulator distinguishes close-only exits,
a pipeline quality failure makes a held trade unresolved rather than bypassing
the ordinary input gate to claim an exit. This limitation stays explicit.

## Simulation protocol v1 and uncertainty

Every position/exit/summary carries SHADOW_SIMULATED_NOT_BROKER_EXECUTED.

- The decision's availability is stamped after initial analysis. Previously
  returned quotes cannot fill it retrospectively. Entry requires a strictly later
  observed quote within two seconds. Polling delay can legitimately reject entry.
- BUY pays observed Ask; SELL receives observed Bid. BUY exits use Bid and SELL
  exits use Ask, with explicitly declared adverse slippage. Spread is embedded in
  bid/ask P&L; entry spread cost is a diagnostic, not charged a second time.
- Original confirmed M1 pivot/sweep extreme plus a one-tick outward buffer sets
  SL; target is 2R from the hypothetical entry. Stops use worse observed gap
  prices; targets receive no optimistic gap bonus. Tick-grid/minimum-distance,
  cost-known-at, volume, profit currency and contract terms must match.
- Fixed simulated 0.01 lot, one position per journal, five openings per UTC day,
  1% paper-equity admission reserve and daily loss latch. Same canonical setup
  cannot rearm. Repeated snapshot observations cannot create extra trades.
- Original matching anchor invalidation and 15-minute holding horizon request an
  exit at an observed executable-side quote. The cutoff never forces a fill.
- Commission/fees round per leg using the explicitly declared currency precision.
  Only USD-linear FOREX/CFD calculation modes 0/1 are supported, with observed USD
  profit currency. Unsupported modes/currencies and unknown contract terms block.
- Missing capture, ambiguous same-millisecond prices, corrected candles, missing
  overnight UTC baseline, session/identity uncertainty or stale data mark a held
  position UNRESOLVED. Recovery never silently converts it into a win/loss.
- Rollover sequencing for live shadow is unsupported: entries spanning a declared
  rollover are rejected; unexpected exposure across one is unresolved. Swap is
  never assumed zero because no row was supplied. Costs require reviewed coverage.
- Each journal is an independent paper study. It does not implement a broker-wide
  capital ledger across parallel studies. Do not reset/recreate journals to hide
  losses, unresolved cases or rejected observations; preserve each study separately.

A terminal-returned tick range is **not independent capture-completeness proof**.
Whole-second API query envelopes are recorded separately from the exact logical
UTC capture window; observed boundary ticks outside that window are counted and
excluded, never interpolated or treated as earlier information.
Exact duplicate ticks collapse; different prices at one millisecond or reversed
order quarantine the entire batch before fills. Missing/truncated history and
catch-up intervals over 60 seconds are blocked; batches cap at 20,000 ticks.
The provider's within-millisecond ordering, execution queues, latency, finality
and capture completeness remain unverified. No result is broker-confirmed P&L.
Observed quote ordering only supports the stated hypothetical model.

Metrics include closed/open/unresolved denominators, empirical win rate, average
win/loss, net P&L, PF (null without a loss denominator), expectancy, equity drawdown
fraction, average holding seconds, entry spread diagnostic and commission/fees.
Rejection counts/frequencies and valid-quote/candle poll counts have explicit
observation/decision denominators. Segments bind strategy version, permission
phase, alignment, adaptive regime, volatility and calendar status. UNKNOWN and
missing-calendar cases are retained. Unresolved trades have no realized outcome;
when marks are stale/unavailable, current unrealized P&L is withheld.

## SQLite schema v1 and recovery

Engine version `live-shadow-1.0.2` binds the stricter diagnostics and query-window policy.
Pre-release 1.0.0/1.0.1 journals must be retained and replayed with their original code;
do not edit metadata to resume them under changed semantics. Start a separately
labeled study for this build.

The private directory contains `shadow.sqlite3` (SQLite's default rollback journal,
not an application broker database). All write transactions use BEGIN IMMEDIATE
and synchronous=FULL; inputs, effects, projections and checkpoint commit together.
Connections close explicitly on every path, including Windows failure paths.

| Table | Contents |
| --- | --- |
| meta | Schema/engine versions, source kind, frozen config, policy/registry/context/intelligence and calendar hashes |
| sources | Deduplicated canonical raw-safe MT5 rate fields and normalized closed-candle windows, keyed by SHA-256 |
| events | UTC observation packet, source reference, research/intent/fill/exit/rejection effects, previous event hash, next state hash; unique packet ID |
| checkpoint | Current paper position, pending decision, retired setup IDs, UTC risk/latch state, strategy lifecycle state, metrics and completeness counters |
| artifacts | Rebuildable DECISION, INTENT, FILL, EXIT and UNRESOLVED projections linked by deterministic IDs |

Source checksums bind canonical captured API values, not a fictitious raw broker
export. Raw data are never uploaded by this code. Only whitelisted market fields,
fixed identity labels and bounded reason codes enter the store; arbitrary fields
are rejected, not “redacted” by guessing which strings might be secrets.

Startup checks SQLite integrity, config/calendar/source-kind identity, sources,
audit chain, projections and checkpoint binding. Offline verification additionally
recomputes every assessment, effect and state hash from the frozen observations.
Idempotent packet processing makes a retry after commit safe; failure before
commit leaves no partial event. New configuration/calendar/policy requires a new
explicit study; unknown schema is not silently migrated.

Hashes provide tamper evidence, **not authentication against someone who rewrites
an entire database and every hash**. Preserve independently stored file/event-hash
anchors and original journal copies. Do not copy an active database without a
consistent SQLite backup; stop the recorder before hashing or sharing a copy.

At 1,000,000 events, 10,000 strategy setups or less than 128 MiB free disk, recording
fails closed. Storage/clock failures produce BLOCKED/stale UI, not a previous
success display. Plan private disk capacity/retention; automatic archival and
long-running disk/terminal soak validation remain pending. Restart gaps cannot
force-close or silently reset a held paper position or its daily latch.

## Windows 10 / Python 3.11 setup

Keep Algo Trading OFF and external Python trading disabled. Keep an already
logged-in **DEMO** terminal open with exact visible XAUUSD. No credentials go into
source, CLI arguments, config, evidence or chat.

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git fetch origin feat/iat-v3-live-shadow-research-v1
git switch --no-track -c local/iat-live-shadow FETCH_HEAD
py -3.11 -m pip install -r requirements.txt MetaTrader5
$journal = Join-Path 'E:\IAT2\IAT2-ShadowLogs' ([Guid]::NewGuid().ToString('N'))
py -3.11 diagnostics/run_live_shadow.py --journal-directory $journal --create --port 8766
```

Open `http://127.0.0.1:8766/`. This first run records real Bid/Ask/candles and missing
conditions, but is **record-only**: no guessed contract/cost config and no fills.
The existing dashboard can keep running independently on 8765. Ctrl+C stops the
recorder. Resume the same study by removing `--create`; do not change its config
or calendar. The endpoint and UI remain loopback-only; there are no order buttons.

For unqualified hypothetical simulation, prepare a reviewed private config v1:
exact keys `version,strategy_id,costs`. Strategy ID must be one of the two existing
candidates; costs are the exact Stage-B Costs fields (see
[Stage-B guide](STRATEGY_QUALIFICATION_STAGE_B.md#quote-and-cost-evidence-contracts)).
Baseline spread_stress_multiplier must be "1". Put the dated, non-secret terms in
`cost-evidence.txt` beside the JSON; evidence_sha256 must match those exact bytes.
Do not copy synthetic costs into a real study or mark missing swap coverage zero.
This file binding records an operator declaration, not independent certification.

```powershell
$private = Read-Host 'Directory containing reviewed shadow config and calendar'
$shadowConfig = Join-Path $private 'shadow-config.json'
$calendar = Join-Path $private 'verified-session-calendar.json'
$journal = Join-Path 'E:\IAT2\IAT2-ShadowLogs' ([Guid]::NewGuid().ToString('N'))
py -3.11 diagnostics/run_live_shadow.py --journal-directory $journal --create `
  --config $shadowConfig --session-config $calendar --interval 1 --port 8766
```

Do not supply an unverified calendar as verified. Omit --session-config for
explicitly unqualified mechanical research, not as a way to certify or bypass an
existing blocked profile. With a supplied invalid calendar, startup fails; with
supplied unverified coverage, the existing calendar gates block analysis/fills.

To attach the separate recorder to the existing AI dashboard, use matching
config/calendar arguments. Optional AI flags remain the original opt-in controls:

```powershell
$logs = Join-Path 'E:\IAT2\IAT2-LiveLogs' ([Guid]::NewGuid().ToString('N'))
py -3.11 diagnostics/run_live_intelligence.py --log-directory $logs --port 8765 `
  --shadow-journal-directory $journal --shadow-config $shadowConfig --session-config $calendar
```

For a record-only journal omit --shadow-config. For a calendar-free journal omit
--session-config in both processes. The attachment retains only the read snapshot
callable; it does not advance the simulator or create intents. The original
Gemini/OpenAI runner options and optional credentials behavior are unchanged.

## Reproduction, inspection and documented UI evidence

Stop the recorder, then verify a real captured journal entirely offline:

```powershell
py -3.11 diagnostics/run_live_shadow.py --journal-directory $journal `
  --config $shadowConfig --session-config $calendar --offline-verify
Get-FileHash -LiteralPath (Join-Path $journal 'shadow.sqlite3') -Algorithm SHA256
```

Omit config/calendar arguments if absent at creation. Replay opens SQLite read-only,
does not import/initialize MT5, and reports MATCH only after recomputing frozen
inputs and effects. Failure exits 1. Output reports no historical qualification.

Reproducible software example (no terminal or network required):

```powershell
$example = Join-Path $env:TEMP ('iat-shadow-SYNTHETIC-' + [Guid]::NewGuid().ToString('N'))
py -3.11 diagnostics/shadow_synthetic_example.py --output-directory $example
py -3.11 diagnostics/run_live_shadow.py --journal-directory (Join-Path $example 'journal') `
  --offline-verify --synthetic-replay
Get-Content -LiteralPath (Join-Path $example 'SYNTHETIC-example.json') -Raw | ConvertFrom-Json
```

The example contains three neutral-candle journal observations plus separately
labeled BUY/SELL **decision/quote software contracts**, each with an observed-side
2R exit under its declared synthetic costs. These are not recognized broker
setups, real fills, market history or evidence of an edge. The committed
`docs/source_reviews/live-shadow-synthetic-v1.json` is the recomputable output.
The regression suite also exercises original typed predicate contracts through
SQLite for both strategy identities/directions; such contracts are distinct from
OHLC detector validation. Actual OHLC integration may legitimately produce WAIT.

Documented UI evidence: `test_dashboard_endpoints_compatible_and_shadow_route_local_only`
requests v1/v2/v3 plus the new shadow route with the Flask client, verifies safe
responses, checks the execution-disabled page label, rejects remote clients and
rejects POST. `test_read_only_dashboard_attachment` verifies stale-mark withholding.
The panel displays source kind, feed, Bid/Ask/spread/age, M1/M5 structure, alignment,
regime, candidate, WAIT, assessment/availability times, paper positions/exits,
metrics/denominators, quality warnings and session/rejection explanations. It uses
textContent and same-origin fetch under the existing CSP. This is documented
synthetic UI/HTTP evidence, not a screenshot of the user's terminal.

```powershell
py -3.11 -m unittest discover -s tests -p test_live_shadow.py -v
py -3.11 -m unittest discover -s tests -v
py -3.12 -m unittest discover -s tests -v
```

Before local acceptance, review actual Ask/tick history, matching symbol/cost
metadata, UTC freshness, missing/duplicate ticks, private disk behavior, restart
recovery and unchanged trading-disabled permissions. Then stop and independently
replay the real journal. Until those checks actually run, live-market acceptance
and broker capture assurance remain unverified. Stage B remains PENDING and
Stages C/D BLOCKED. There is no request or capability to place an order.
