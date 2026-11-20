# Stage B.3 — three-engine shadow research v1

This is an experimental comparison consumer of Stage B.2's read-only recorder. It cannot place, modify or cancel broker orders. Operational `signal=WAIT`, `execution_allowed=false`, `orders_requested=0`, Exness `BLOCKED`, Stage B qualification `PENDING`, and Stages C/D `BLOCKED` remain invariant. Historical validation is `PENDING`; historical comparisons are `NOT_RUN`. No existing strategy, confluence threshold, session profile, historical gate or original dashboard route changes.

## What is implemented

`iat/three_engine/` supplies a shared causal evidence bundle, structured plan validation, optional provider transports, independent paper ledgers, an append-only SQLite comparison journal, deterministic replay and a separate loopback dashboard. It reads the original `shadow.sqlite3` through a read-only connection. It does not import MetaTrader5, read accounts, switch terminals, or change terminal permissions.

- **A_RULES:** the existing `live_shadow.research.assess` adapter and original continuation/reversal observations. The selected baseline strategy is frozen in configuration; both strategies' assessments remain visible. Its original structural stop, 2R target and 900-second hold are preserved. The common feasibility layer can reject a baseline plan without changing the underlying strategy predicate.
- **B_HYBRID:** a request is eligible only when A's deterministic adapter produced a potential candidate. That candidate is a separate hint alongside the common evidence. The model may accept it, reject it, or choose a different evidence-grounded direction/plan. A's result is never rewritten.
- **C_AI_LED:** receives the same common evidence, without A's candidate or a prerequisite A trigger. It independently chooses BUY, SELL, WAIT or BLOCKED and selects supplied anchors, target rules and invalidations. It still passes every deterministic feasibility gate.

Each engine has its own balance, pending proposal, position, retired-setup identities, daily opening cap and loss latch. One engine cannot consume another's risk allowance. All hypothetical actions carry `SHADOW_SIMULATED_NOT_BROKER_EXECUTED`.

## Frozen evidence and availability

Each comparison point freezes an XAUUSD bundle with observed paired Bid/Ask (never reconstructed Ask), spread, source receipt and comparison cutoff, closed M1/M5 bars, source/evidence IDs, confirmed pivots, BOS/CHoCH, candlesticks, zones, liquidity, momentum, regime/volatility, alignment, session status, quality diagnostics, symbol specifications, and explicit cost/account declarations. Original context and adaptive classifications are reused. Native M5 remains native; overlapping M1 aggregation is only a consistency diagnostic, never a replacement.

Ordering, gaps, freshness, finality eligibility and causal alignment use the existing quality engine and supplied calendar. Unclosed/future bars, future evidence, malformed quotes, missing overlap or blocked context fail closed. The absence of a verified calendar is disclosed as a limitation: mechanical shadow research is not live session authorization or historical qualification. Supplied closed/restricted sessions are respected. B.2 capture completeness remains a terminal observation, not an independently authenticated provider guarantee.

Evidence IDs and bundle IDs are canonical hashes. Repeated references are rejected instead of increasing score. Closed-candle extrema and original confirmed structure/zone levels form a price catalog. Only catalog references can create stops or anchored entries. Models cannot supply arbitrary numerical prices or add indicators, levels, past outcomes, costs or permission fields.

The source receipt, shared cutoff, provider request/response and final decision availability are distinct timestamps. Common price/risk validation finishes before availability is sampled; the journal then repeats pure validation for integrity without reading new evidence. Latency is measured from the **common cutoff**, with provider round-trip and market-to-decision latency reported separately. Plans are queued until the captured market watermark reaches their actual availability. On a timestamp tie, a quote is processed before a new decision. No earlier quote or candle high/low can fill that decision. Historical AI backfilling is not supported; offline replay uses the already frozen responses and actual availability timestamps.

## Contracts and interpretation limits

Published JSON contracts:

- [`three-engine-response-v1.schema.json`](../schemas/three-engine-response-v1.schema.json): strict, bounded model response, every property required, no additional properties.
- [`three-engine-proposal-v1.schema.json`](../schemas/three-engine-proposal-v1.schema.json): standardized validated public proposal, including entry, structural SL, up to three targets/allocations, risk, volume, feasibility, evidence, timestamps, versions and safety constants.

The model chooses supplied evidence IDs, catalog anchors or R1/R2/R3 target rules, entry type, bounded risk/expiry/hold, and registered interpretation/invalidation codes. Reasoning such as `BUYERS_CONTROL`, `LIQUIDITY_TRAP_RISK`, `MOMENTUM_WEAKENING`, `M1_M5_CONFLICT`, `REACTION_ZONE`, `TOO_LATE` and `COSTS_TOO_LARGE` is a **conditional model interpretation linked to evidence**, not another observed market fact. Public explanations expose those auditable interpretations, not private chain of thought. The bounded language is intentionally less expressive than an unrestricted analyst narrative.

Fresh opposing CHoCH must be acknowledged as contradictory evidence. Opposing-CHoCH and time-limit invalidations are mandatory for directional plans. Reversal entry additionally requires referenced confirmed sweep evidence on the relevant side (lows for BUY, highs for SELL); a penetration, ambiguous event or sustained breakout alone does not qualify. Anchored pullback/breakout/reversal entries wait for a later executable-side trigger.

Requested confidence bands `40_60`, `60_80`, `80_90` and optional numerical model assessments are uncalibrated research labels. The public `confidence_band` is always `UNCALIBRATED`; `confidence_probability` is always null. Confidence never changes permission, lot limits or risk gates. No win-probability claim is made.

## Registered research protocol and feasibility

`config.PROTOCOL` and its hash freeze this new protocol before a real comparison trial:

| Rule | Value |
|---|---|
| Maximum quote age / immediate-entry delay | 2 seconds |
| Maximum proposal expiry | 30 seconds |
| B/C maximum holding horizon | 180 seconds |
| A baseline holding horizon | original 900 seconds |
| Minimum target reward/risk | 1R |
| Maximum risk | 1% of paper equity |
| A baseline risk | 0.5% |
| Maximum volume | 0.01 lot, additionally constrained by risk/step/minimum |
| Maximum simultaneous exposure | one per engine |
| Daily opening cap / loss latch | 5 / 1% per engine, UTC |
| Provider timeout / retries | 10 seconds / 0 |
| Output-token cap / input-byte cap | 2,048 / 256,000 |

These are explicit new research choices, not profitability-tuned settings or changes to the inherited predicates.

A plan requires matching observed symbol specifications and reviewed declarations of USD-linear contract/tick value, stop minimum, lot minimum/step, spread ceiling, slippage, commissions, fees, free margin and side-specific margin per lot. Unsupported currencies/calculation modes block. Prices must be positive tick multiples with correct SL/TP ordering and increasing targets. BUY stops are checked against Bid; SELL stops against Ask. Expected target distance must exceed declared spread/cost headroom. Costs are rounded per component. Volume is **floored** to the step; it is never rounded up to the broker minimum. A $50 paper account can therefore reject a wide stop as unaffordable; an actually affordable tight evidence-grounded stop can pass.

**Account limitation:** B.3 does not read real broker equity, free margin or margin calculations. These are explicit, dated **paper-account declarations** with file hashes. Current paper balance/equity/free margin are updated from this independent virtual ledger. They are not current broker account data or authenticated broker affordability. Margin changes, nonlinear valuation and liquidation are not modeled. Actual broker/account evidence and isolated Windows validation remain pending.

Entry revalidates spread, stop geometry, dynamic paper equity/free margin, projected daily risk, volume and lot step at the later observed quote. A changed required lot is rejected rather than silently resized. BUY uses Ask; SELL uses Bid, with adverse declared slippage. Exits use Bid for BUY and Ask for SELL. Stops may gap adversely; targets receive no favorable gap bonus. Per-side fees and commissions are included in net results. Session closures/close-only restrictions remain distinct from quote availability. Unsupported rollover ordering blocks entry or leaves an existing position unresolved.

TP1/TP2/TP3 and allocation math are validated, including broker minimum/step for every allocated portion. A partial target touch has no independent fill/liquidity proof and therefore leaves the position **UNRESOLVED**, rather than manufacturing partial profit. Missing ticks, ambiguous quote order, unsupported exit permission or unknown opening equity likewise remain unresolved. An unresolved exposure is not later converted into a winner. Optional `BREAKEVEN_AT_R1` changes a hypothetical stop only for subsequent quotes and means gross breakeven, not cost-free. Opposing CHoCH, anchor loss, high volatility and elapsed hold can request exit only on later executable quotes.

## Providers, privacy and budgets

Real providers are **off by default**. OpenAI and Gemini adapters use the existing optional pinned SDK dependencies, official vendor endpoints, structured JSON, no tools, no redirects/environment proxy, a bounded response and no automatic retries. No real provider calls were used in implementation tests. The deterministic test provider is explicitly labeled synthetic and cannot establish real AI activity.

Before a request, the journal reserves one call, an input-byte upper bound covering the evidence, instruction prompt and response schema, a 4,096-token vendor-envelope reserve, plus the output-token cap, and the corresponding **declared** input/output per-million cost. Unknown pricing or insufficient call/token/cost allowance blocks before transport. Reservations survive crashes and are not refunded. The byte-token bound and declared rates are conservative research accounting, **not an independently verified vendor billing cap**. Apply vendor-side spend controls separately. Two engines may each make a request per eligible point; hybrid gating does not apply to C.

API keys are read from `IAT_OPENAI_API_KEY` or `IAT_GEMINI_API_KEY` only with `--enable-ai`; do not put keys in source, commands committed to Git, configs or reports. SDK errors, arbitrary text, private thoughts, account identifiers and invalid raw responses are not persisted. Malformed responses become bounded reason codes. No confidence, model output or prompt can authorize execution. Provider observations disclose configured transport, attempted calls and validated responses separately; interface existence is not evidence of AI success.

## Journal, recovery, replay and metrics

The separate `comparison.sqlite3` binds exact source-journal identity, source kind, calendar, research config, protocol and per-engine model references. Tables contain metadata, deduplicated source candles, hash-chained events/effects and a checkpoint. Transactions use SQLite full synchronization. Each event recomputes deterministic state/effects and stores hashes; offline verification replays without SDK calls or MT5. Identical event IDs are idempotent; tampering/config/model mismatch fails closed. Source corrections latch comparison quality; there is no silent revised-history backfill.

A provider request is committed before transport. Restart marks unfinished requests `INTERRUPTED` and preserves budget reservations; it does not resend them. An outstanding timeout thread cannot block capture, cause retry or later overwrite the timeout. Quote batches are validated before any fill. Study limits (10,000 points, 1,000,000 events, and at least 128 MiB free disk headroom) stop safely; use a new private study instead of deleting evidence or changing an existing binding.

Metrics report BUY/SELL/WAIT/BLOCKED counts, rejections with reasons, entries/exits, open/unresolved exposures, all-decision/source-observation/completed-trade denominators, missing-data rate, measured decision latency, closed-trade win rate, after-cost expectancy and observed drawdown. Zero completed trades gives null win rate/expectancy. Disabled/not-attempted provider latency is null. Closed-trade metrics are explicitly **conditional on resolved trades**; unresolved/rejected/pending cases remain visible. Drawdown is observed marks only and incomplete across unresolved intervals. Paper marks are withheld when stale. Qualified-performance metrics remain null, calibration `NOT_RUN`, AI improvement `UNMEASURED`.

The separate GET-only API is `http://127.0.0.1:8767/research/v1/comparison`; UI is `http://127.0.0.1:8767/`. It shows all three plans, supporting/opposing references, quotes, context, latency/expiry, position/exit events, quality limitations and metrics/denominators. It rejects remote hosts, query strings and write methods, has no-store/CSP headers and renders data through text nodes. Original 8765/8766 interfaces are untouched. Flask's built-in localhost server is for this local pilot, not public hosting.

## Windows 10 / Python 3.11 operator procedure

Run commands in order, one block at a time. Keep both MT5 Algo Trading and external Python API trading disabled. Use the already connected DEMO terminal; no credentials are requested. Do not change to a real account. Nothing here enables orders.

Fetch the new development branch (works without remote-tracking configuration):

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git status --short --branch
git fetch origin feat/iat-v3-three-engine-research-v1
git switch --no-track -c local/iat-three-engine-b3 FETCH_HEAD
Test-Path '.\diagnostics\run_three_engine_research.py'
py -3.11 -m pip install -r requirements.txt MetaTrader5
```

If the local branch name already exists, inspect it before using `git switch local/iat-three-engine-b3`; do not discard local changes. `Test-Path` must be True. Verify the SHA from the draft PR. Never use reset/clean as a workaround.

### 1. Start the existing B.2 recorder in PowerShell window 1

Use a NEW private directory outside the checkout and keep its exact path for window 2:

```powershell
$source = Join-Path 'E:\IAT2\IAT2-LiveLogs' ('b2-' + [Guid]::NewGuid().ToString('N'))
Write-Output $source
py -3.11 .\diagnostics\run_live_shadow.py --journal-directory $source --create --interval 1 --port 8766
```

This uses original record-only defaults. If already using reviewed B.2 `--config`/`--session-config`, keep the exact same files and pass them to B.3 as `--source-config`/`--session-config`. Do not use the synthetic research cost/account declarations with a real source. The existing live-intelligence/AI commentary app may remain separately on 8765.

### 2. Start the comparison in PowerShell window 2, initially with AI off

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
$source = Read-Host 'Paste the private B.2 journal-directory printed in window 1'
$comparison = Join-Path 'E:\IAT2\IAT2-LiveLogs' ('b3-' + [Guid]::NewGuid().ToString('N'))
Write-Output $comparison
py -3.11 .\diagnostics\run_three_engine_research.py --source-journal-directory $source --journal-directory $comparison --create --port 8767
```

Open `http://127.0.0.1:8767/`. No provider is contacted. With no research configuration, costs/account are null and budgets zero: directional feasibility stays blocked. This is the safe recorder/consumer connectivity check, not a completed trading trial. A stale/unavailable source must show warnings. Preserve both private journal directories; Ctrl+C stops each process. To resume the same bindings omit `--create`.

### 3. Optional model study, after reviewing paper terms and spend limits

Prepare a private `research-config.json` matching `iat/three_engine/config.py`: version 1, `baseline_strategy_id`, the exact existing `Costs` fields, declared `account`, and `budgets`. Required adjacent files are `cost-evidence.txt` and `account-research-evidence.txt`; their **actual byte SHA-256** must equal each declaration's `evidence_sha256`. Document where each term came from, its date and uncertainty; no credentials/account numbers. Native contract metadata must match the observed source. Declare actual published vendor input/output rates and conservative positive budgets. Do not infer missing terms or copy synthetic terms as broker evidence. The generated example below demonstrates shape only. Missing/unreviewed terms are a blocker, not permission to guess.

Install only the selected existing optional SDK requirements, using pip (no downloaded scripts):

```powershell
# Select ONE provider. These commands install packages; they do not contact a model.
py -3.11 -m pip install -r requirements-ai.txt
# Or: py -3.11 -m pip install -r requirements-gemini.txt
$research = Read-Host 'Absolute path of reviewed private research-config.json'
$study = Join-Path 'E:\IAT2\IAT2-LiveLogs' ('b3-model-' + [Guid]::NewGuid().ToString('N'))
$model = Read-Host 'Exact supported vendor model ID'
```

Only after explicitly deciding to send the frozen **redacted market evidence** to the provider, make a new study with `--research-config $research --enable-ai --provider openai --model $model` (or `--provider gemini`). The corresponding environment key must already be securely provisioned in that process. Do not print it or paste it into a report. Example invocation, assuming the same `$source` and reviewed configuration:

```powershell
py -3.11 .\diagnostics\run_three_engine_research.py --source-journal-directory $source --journal-directory $study --create --research-config $research --enable-ai --provider openai --model $model --port 8767
```

A study freezes model/config/calendar identity. Resume with the same flags, omitting `--create`. To change a model or protocol create a new directory. Provider schema/model support and real SDK connectivity have **not** been validated by cloud mocks. Errors/timeouts/insufficient budget must remain BLOCKED; do not loosen gates to obtain trades. Cost estimates are not vendor billing guarantees.

### 4. Offline verify (no provider or terminal access)

After stopping the consumer, retain the original source/config/calendar:

```powershell
py -3.11 .\diagnostics\run_three_engine_research.py --source-journal-directory $source --journal-directory $comparison --verify-only
# For a model study add --research-config $research and use $study as journal-directory.
# Also repeat --source-config and --session-config if originally supplied.
```

Expected result is JSON `status: MATCH`, `orders_requested: 0`, `execution_allowed: false`, `signal: WAIT`. A mismatch is a blocked integrity issue: preserve files and investigate; do not regenerate hashes over altered evidence. Full raw journals and provider-market evidence should stay private.

## Reproducible synthetic example

This is explicitly fabricated **test OHLC**, not historical XAUUSD or measured AI skill. It uses no MT5, network, broker credentials or actual model requests. Generate into a NEW directory outside Git:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
$example = Join-Path 'E:\IAT2\IAT2-LiveLogs' ('SYNTHETIC-b3-' + [Guid]::NewGuid().ToString('N'))
py -3.11 .\diagnostics\three_engine_synthetic_example.py --output-directory $example
py -3.11 .\diagnostics\run_three_engine_research.py --source-journal-directory (Join-Path $example 'source') --journal-directory (Join-Path $example 'comparison') --research-config (Join-Path $example 'research-config.json') --verify-only --synthetic-source
Get-Content -LiteralPath (Join-Path $example 'SYNTHETIC-comparison.json') -Raw
```

The committed metadata-only [synthetic report](source_reviews/three-engine-synthetic-v1.json) has one comparison point and three observed fixture packets:

| Engine | Decision | Simulated entries/exits | Completed-trade denominator | Reason |
|---|---|---|---|---|
| A | WAIT | 0 / 0 | 0 | flat fixture has no original strategy candidate |
| B | BLOCKED | 0 / 0 | 0 | NO_RULE_CANDIDATE; no model request |
| C | BUY | 1 / 1 | 1 | deterministic fixture response references an actual supplied closed-low anchor |

C's fixture availability is cutoff +0.5 seconds; entry is observed Ask at +1 second; target exit is later observed Bid at +2 seconds. The illustrative closed result is USD 2.00 **within fabricated test data only**. It says nothing about win probability, market profitability or AI superiority. Actual AI calls are zero. Verification covers seven journal events, replay `MATCH`, unchanged source bytes and deterministic full/full/prefix histories. The report contains canonical logical hashes, not platform-dependent SQLite file hashes.

## Verification and remaining work

Run focused and inherited suites (Python 3.12 is offline only):

```powershell
py -3.11 -m pip install -r requirements-dev.txt
py -3.11 -m unittest discover -s tests -p test_three_engine.py -v
py -3.11 -m unittest discover -s tests -v
py -3.12 -m unittest discover -s tests -p test_three_engine.py -v
py -3.12 -m unittest discover -s tests -v
```

The added regressions cover independent C generation, hybrid disagreement, causal evidence, duplicate/future references, correct quote sides, stops/targets/allocations, $50 reject/afford cases, margin/costs, expiry/latency, sessions/rollovers, provider schemas/budgets/timeouts, missing ticks/unresolved cases, recovery/idempotency/tamper/model bindings, source byte invariance, full/full/prefix equivalence, future append and loopback API compatibility. OpenAI/Gemini tests use mocked SDKs only. Exact totals and four-platform CI results are recorded in the draft PR, not assumed from source inspection.

Before answering the research question, obtain: independently reviewed live contract/cost/calendar/account assumptions; Windows DEMO source/consumer evidence with both trading permissions disabled; real provider schema/latency/billing observations under explicit spend limits; a preregistered sufficiently long identical observation window; complete rejected/open/unresolved denominators; and independent out-of-sample review/calibration. Independent historical export qualification and blinded review are still pending. No engine improvement or profitability has been measured. Do not merge or enable Stages C/D on the strength of synthetic tests.
