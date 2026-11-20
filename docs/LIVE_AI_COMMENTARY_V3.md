# Live AI commentary and evidence validation v3

Base: exact PR #34 `db4bebe4b82497c5b253b8a66c13e3e652b180d5`.
No merge, rebase, strategy, score, confluence, session-calendar or execution-gate
change. The optional provider is a separate research boundary with no terminal
object, order interface or broker credentials.

## What is verified, and what remains local

The operator reports one genuine Windows MT5 observation window: PASS, 72/72
connected samples, 33 Bid/time/acquisition updates, 6 M1 and 1 M5 close transitions,
no blocked transport samples/reconnections/issues, zero orders. This is an
operator-reported result, not an independent Cloud terminal test. It establishes
one six-minute observation only. `BLOCKED_DATA_QUALITY` and
`SESSION_CALENDAR_UNAVAILABLE` still appeared in every sample. Transport stability
never removes these analytical eligibility blockers.

V3 automated tests use synthetic observations and mocked provider HTTP, including
the actual supported SDK request/response boundary. No actual OpenAI request or
Windows MT5 integration is claimed by Cloud/CI. Do the optional local test below
to establish a real provider result. Historical qualification stays separate.

## Windows 10 / Python 3.11: update and start without AI

Stop the old dashboard with Ctrl+C. Run each command individually, top to bottom,
without copying `PS`, `>>` or trailing backslashes. Preserve any uncommitted work
shown by `git status` before switching; do not reset or force a checkout.

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git status --short
git fetch origin refs/heads/feat/iat2-live-ai-commentary-v3
$branch = 'local/iat2-commentary-v3-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
git switch --no-track -c $branch FETCH_HEAD
git rev-parse HEAD
py -3.11 -m pip install -r requirements.txt MetaTrader5
```

Compare the displayed SHA with the delivered PR head. The no-tracking switch
works with the operator's single-branch clone and preserves the old local branch.
The random local suffix avoids overwriting an existing branch. No merge occurs.
The normal dependencies are unchanged. Do not install the optional SDK unless you
want the provider. Normal startup never reads an API key or calls OpenAI.

Keep the authorized **demo** terminal connected, exact **XAUUSD** visible, **Algo
Trading disabled**, and **external Python API trading disabled**. Do not enter
broker account data into this application.

```powershell
$logs = Join-Path 'E:\IAT2\IAT2-LiveLogs' ([Guid]::NewGuid().ToString('N'))
py -3.11 .\diagnostics\run_live_intelligence.py --log-directory $logs --interval 10 --port 8765
```

Leave the server running. Open `http://127.0.0.1:8765/` in your browser. AI status
is DISABLED; the chart, evidence panels and every commentary section still work.
Use a NEW private log directory on every restart. Existing files are not reused.
Historical CSV intake is not a prerequisite. An unverified calendar remains
blocked; do not bypass it to obtain a directional assessment.

## Optional genuine OpenAI test

Stop the no-AI server with Ctrl+C. Install only the pinned optional SDK from the
normal package index; no remote scripts are downloaded or executed:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
py -3.11 -m pip install -r requirements-ai.txt
$env:IAT_REASONING_MODEL = Read-Host 'Available OpenAI model supporting Responses structured outputs (for example gpt-4.1-mini)'
$apiSecure = Read-Host 'OpenAI API key (never paste into chat or Git)' -AsSecureString
$env:IAT_OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $apiSecure).Password
$logs = Join-Path 'E:\IAT2\IAT2-LiveLogs' ([Guid]::NewGuid().ToString('N'))
try {
    py -3.11 .\diagnostics\run_live_intelligence.py --log-directory $logs --interval 10 --port 8765 --enable-llm --llm-min-seconds 60
} finally {
    $env:IAT_OPENAI_API_KEY = $null
    $env:IAT_REASONING_MODEL = $null
    Remove-Variable apiSecure -ErrorAction SilentlyContinue
}
```

The API key exists only in this process environment/in-memory SDK authorization.
Never use `setx`, commit it, put it on the command line, or paste it into a report.
The example model is not an assertion of your account's availability; choose an
available Responses/strict-JSON model. `--llm-model` can alternatively specify it.
Unsupported models/configurations fail to deterministic commentary. No model
listing, credential check or network call occurs merely because a key exists.

In a **second PowerShell window**, inspect metadata only:

```powershell
$r = Invoke-RestMethod 'http://127.0.0.1:8765/live/v3/snapshot'
$r.commentary | Select-Object status,source,provider,model,validation,request_at_utc,response_at_utc,latency_ms,cached,reason_codes
$r.commentary.evidence_cutoffs
$r.ai_evidence | Select-Object bundle_id,policy,scope,fact_count
$r.commentary.metrics
$r.commentary.usage
$r | Select-Object signal,execution_allowed,orders_requested,exness,qualification,historical_validation,historical_comparisons,profitability_tested
if ($r.signal -ne 'WAIT' -or $r.execution_allowed -ne $false -or $r.orders_requested -ne 0) { throw 'Safety invariant failure: stop the server' }
```

Wait for a completed request, then repeat. ACTIVE requires a real response passing
all validations for the current evidence. A configured key, REQUESTING, usage
estimate or cached response from another bundle cannot establish ACTIVE. If a
new candle arrives while a request is pending, that old result is rejected; wait
for the next eligible request. The 30-second bound, provider/model limitations,
rate limits, missing SDK/key, invalid output or networking can produce fallback.
The market-data observer continues. There is no need to change MT5 permissions.

Check that `request_snapshot_id` matches the original logged request snapshot,
`evidence_cutoffs` match the current M1/M5 cutoffs, and current `ai_evidence.bundle_id`
matches commentary `bundle_id`. Quote-only updates may have a different current
observation ID while legitimately reusing the same closed evidence. Open an
Evidence link and compare its original canonical reference and UTC availability.
Keep logs private. Send only sanitized metadata if requesting help; never upload
raw logs, account data or keys.

To disable AI again, Ctrl+C completes the `finally` cleanup above. Restart with a
new `$logs` directory and omit `--enable-llm`. Status must return to DISABLED even
if a key was accidentally left in the environment. Keep both terminal trading
permissions disabled throughout. Reuse the v2 six-minute local stability diagnostic
in `docs/LIVE_REASONING_V2.md`; it samples v1 and does not trigger provider calls.

## Research synthesis and evidence contract

The dashboard retains Bid/timestamps, interactive received closed M1/M5 OHLC,
structure, evidence inspector, calculated levels and expandable technical JSON.
The AI Market Intelligence section adds nine labeled sections: summary, M1/M5,
price action, levels, bullish/bearish research, conflicts, WAIT and next observation.
“What changed?” is a deterministic comparison, not a model assertion. Provenance
shows request and current observation IDs separately, closed-candle cutoffs,
bundle ID, provider/configured model, last successful response, request/response
UTC, current-bundle freshness/response age, cache/fallback, latency and token usage.
A previous success timestamp is historical metadata, not an old interpretation
presented as current. Disconnect/refresh failure clears current interpretation.

V3 goes beyond v2's seven wording choices: the provider receives a bounded typed
catalog of existing observations, swings, relevant events, momentum/volatility,
calculated levels, supporting/opposing evidence, formal conditions when present,
scenario transition, unresolved gates and changes. It selects salient facts and
organizes their explanation in nine sections. The deterministic formatter renders
those typed facts after exact validation. Factual correctness is not established
by attaching a real citation to arbitrary model prose, so unrestricted model prose
and new model-authored market assertions remain intentionally unsupported.
This is constrained AI evidence synthesis, not autonomous discretionary analysis
or a new scenario-selection engine. No chain-of-thought is requested, displayed
or logged. There is no confidence probability, entry/stop/target or order advice.

Each returned claim must copy the exact fact ID, evidence references, timeframe,
event type, direction and level object. The local validator enforces exact fields,
unique facts, nine sections, correct section membership, required WAIT/safety,
all supplied directional support/opposition and missing-condition explanations.
Unknown indicators, changed direction/level/event/timeframe, extra execution/free
text fields, invented IDs, duplicate inflation, omitted uncertainty and old bundle
IDs are rejected. Prices only originate from the existing calculated levels and
confirmed events. A level's approach/rejection/break is not inferred from a Bid;
only existing deterministic states are described. OHLC liquidity is a proxy.

Packets use canonical source references and eligible closed evidence only.
Chronology, UTC, cutoff/frame agreement, referenced-source existence, duplicate
evidence and OHLC sanity are rechecked. The existing observer still performs all
underlying quality gates and forming-candle exclusion. A tampered/unsupported
snapshot is quarantined. No new session truth, strategy or score is introduced.
A formal BLOCKED context can supply explicitly descriptive observations; it
cannot become an eligible bullish/bearish assessment. When formal conditions are
unavailable, the UI says so instead of inventing confirmation/invalidation prices.

Catalog limits: latest two swings/two events per frame; latest evidence per
pattern/momentum/volatility/liquidity/transition category and frame; eight recent
non-invalidated calculated levels; at most three supporting/opposing observations
per direction; two existing assumptions/invalidation conditions. These are
presentation bounds only; the original complete snapshot/chart remains available.
Levels are ordered deterministically by timeframe, origin and ID, not invented
proximity. Missing or oversized inputs fail closed instead of being filled.

## Provider, event policy and costs

`requirements-ai.txt` pins the supported `openai` Python SDK. No new mandatory
runtime dependency. The adapter uses **Responses**, strict `text.format` JSON
Schema, `store=false`, no tools, no conversation/session state, no automatic
retries, fixed HTTPS `https://api.openai.com/v1/responses`, normal TLS verification,
no redirects or environment proxy/netrc lookup. The secret is never returned.
SDK failures are mapped to static codes; raw request/response/error bodies are not
logged. Reasoning output items are ignored, never treated as visible evidence.

One commentary worker watches observer snapshots every second without calling
MT5 itself. Provider calls run in another single-inflight thread. They do not
block the market-data observer, dashboard requests or deterministic journals.
Reevaluation keys include closed M1/M5 evidence, canonical events/structure,
liquidity, scenario/configuration, feed/gate state and deterministic changes.
A new closed candle, BOS/CHoCH, liquidity event or scenario transition changes the
key. Bid/acquisition-only changes and dashboard refreshes do not. Up to 64 success
or failure bundles are cached; unchanged failed evidence is not retried in a loop.
This bounded LRU is not permanent cross-restart deduplication. Disconnect invalidates
current commentary; recovery is revalidated and may wait for the cooldown.

Default minimum interval is 60 seconds, configurable 30..3600. There is no
automatic retry. At 60 seconds the upper bound is 60 requests/hour while the
application is running and evidence keeps changing; fewer when unchanged/blocked.
Background commentary continues when the browser is closed. Stop the server or
restart without `--enable-llm` to stop provider calls. The request timeout is 30
seconds (connect up to 3); a streamed-body wall-budget is checked as chunks arrive.
Input is capped at 96 KiB, decoded response 256 KiB, output at 12,000 tokens.
Read timeouts also bound a stalled chunk. Actual billable tokens/cost depend on
model, packet and provider accounting. Token counts, when returned, are usage
metadata, not a dollar estimate; no prices are invented. Consult current pricing
and account limits before enabling prolonged observation:
https://openai.com/api/pricing/ and https://platform.openai.com/settings/organization/limits.

Status semantics: DISABLED=no opt-in; CONFIGURED=valid setup awaiting an evidence
event; REQUESTING=one call in flight; ACTIVE=received and validated current-bundle
response; RATE_LIMITED=local cooldown or provider 429; ERROR=configuration,
transport, schema/evidence or audit failure; FALLBACK=no eligible current feed or
a stale result. All non-ACTIVE states use deterministic commentary. Configuration
alone never claims ACTIVE. A response arriving after material evidence changes
is recorded as stale and cannot become the current interpretation.

Official SDK/API references inspected November 18, 2026:
https://github.com/openai/openai-python,
https://developers.openai.com/api/docs/guides/structured-outputs,
https://developers.openai.com/api/reference/resources/responses/methods/create.
No real provider request was performed to test account/model availability.

## Private audit and compatibility

V1 `/live/v1/snapshot`, V2 `/live/v2/snapshot`, original evidence/snapshot IDs,
DecisionLog and Strategy Replay Log contracts remain intact. V3 is additive at
GET `/live/v3/snapshot` with its own SHA-256. All routes retain loopback/Host
checks, no query mutations, no-cache headers and CSP. There is no config/trade API.
The existing v2 provider API remains available for backward compatibility; the
Windows runner uses the new SDK provider only after explicit opt-in.

Original `raw-candles.jsonl` and `research.jsonl` are unchanged. New
`ai-commentary-v3.jsonl` is a separate append-only hash chain in the private log
directory. It binds original observation ID, evidence bundle/cutoffs,
provider/model, request/response and record UTC, validation, commentary ID,
references, cache state, sanitized reason code, latency and available token usage.
Both request completion (including stale/failure) and view state are recorded,
so closing the browser does not lose the provider audit. No API key, raw prompt,
raw response, provider error body or terminal account/server fields are recorded.
Disk errors withhold AI output instead of modifying deterministic DecisionLogs.
Files are never silently overwritten or rotated; monitor disk use locally.

All modes retain WAIT, execution_allowed=false, orders_requested=0,
profitability_tested=false, Exness BLOCKED, DATA_NOT_QUALIFIED,
historical_validation=PENDING and historical_comparisons=NOT_RUN.
No credential, order, trading-permission or historical-qualification capability
is introduced. Actual provider behavior and prolonged Windows observation remain
operator validations, not conclusions from synthetic CI.
