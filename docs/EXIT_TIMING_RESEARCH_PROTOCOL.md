# Exit timing research protocol — proposed v1, NOT_IMPLEMENTED

E2 produces analytical observations only. It activates no timer, position, fill,
profitability calculation, stop or executable policy. A five-close setup expiry
is not a position holding duration. This protocol is a future experiment design.

## Fixed cohort and timing contract

Compare 15, 30, 50, 60, 90 and 120 seconds, structural exit and momentum exit on
**identical independently eligible entry cohorts**. Freeze dataset hashes, source
rights/feed identity, session and finality evidence, qualification, entry strategy,
original E1/E2 reports/configurations, hypothetical fill policy, observation cutoff,
quote/cost models and out-of-sample split before comparison. Keep unresolved and
unfilled opportunities in denominators; do not choose policies on test outcomes.
A matched cohort is not evidence that any opportunity was actually filled.

Earliest eligible hypothetical entry must follow confirmation availability under
a separately validated fill model; E1 confirmation close, candle open or setup
detection is not a fill timestamp. Require timestamped, immutable, same-feed
Bid/Ask observations with UTC/millisecond convention, receipt/availability ordering,
monotonic clocks, unique tick IDs, corrections, capture completeness and source
qualification. At identical timestamps require verified ordering or remain
unresolved. Do not manufacture quotes from OHLC or cross-feed prices.

For each validated hypothetical fill timestamp t_fill and frozen duration d,
declare deadline=t_fill+d. The timer protocol requests the first eligible recorded
quote **at or after** that deadline; report quote timestamp, availability/receipt,
actual observed delay and quote age. A quote before deadline cannot be reused as
an exact deadline exit. Freeze explicit freshness, latency and maximum-gap policies
before data evaluation; this document does not invent or widen their thresholds.
If ticks are absent, stale, future-dated, corrected, unordered, incompletely
captured or outside verified sessions, mark unresolved with the precise reason.
A quote after a session interruption must not be called a 50-second exit; record
the interruption and delayed observation or withhold the outcome under the frozen
protocol. A change in quote receipt is not necessarily a new market tick.

A 50-second method measures from a validated fill, **never** from M1 opening or
setup detection. M1 OHLC cannot establish exact 50-second exits, price sequence,
spread or event order. Even sufficiently granular data needs finality/completeness
and side/basis evidence. E2 never evaluates this timer or emits a result for it.

## Side, costs, excursions and ambiguity

Hypothetical long entry uses eligible Ask and exit Bid; short entry Bid and exit
Ask. This is a future fill-model requirement, not authorization or a source of
prices today. Record actual source quote IDs, both sides and spread, instrument
precision, contract size, profit currency, conversion and session permissions.
Quote contact alone does not establish available liquidity or a fill. Slippage,
commission, fee basis and quantity/contract assumptions require independent
evidence; unavailable costs remain null, never silently zero. No executable sizing.

MFE/MAE must use the appropriate mark-to-exit side at every eligible observation
between known fill and exit, with units, completeness and cost treatment explicit.
Missing intervals mean incomplete excursions, not a zero or known maximum.
Target/stop/time observations that share an unordered timestamp or OHLC interval
remain unresolved; optimistic/pessimistic sensitivities must be separate labeled
models, not historical facts. No arbitrary best exit or retrospective target.

## Future exit-family interfaces

Each interface must be versioned and carry original source/entry/policy hashes,
reference availability, quote/basis, observation cutoff, costs, missing reasons
and unresolved ordering. No family below is implemented by this protocol.

| Family | Required inputs / causal trigger | Basis and granularity / evidence | Costs, ordering and comparison |
|---|---|---|---|
| R:R 1:1 | Validated fill and structural risk distance, frozen ratio | Compatible side/basis, contract evidence and ticks or declared close policy | No target without fill/risk; unknown costs null; compare same cohort |
| R:R 1:2 | Same prerequisites, ratio fixed before observations | Same side-specific source requirements | No retrospective ratio optimization; unordered target/stop unresolved |
| R:R 1:3 | Same prerequisites, frozen ratio 3 | Same granularity and finality requirements | Separately versioned result, matched cohorts and unresolved denominators |
| ATR stop/target | Existing eligible ATR, fixed multiplier/update policy | ATR available before use; tick/close policy explicit | Bands are hypotheses, not fills; sourced costs and matched variants |
| Swing trailing | Favorable confirmed swing and frozen update rule | Update at confirmation availability, never historical pivot occurrence | No retroactive tightening; quote order/costs explicit |
| Momentum deterioration | Existing indicator and reviewed trigger/version | Eligible closed observations under the chosen momentum rule | Not an attainable exit price; no threshold tuning on held-out outcomes |
| Break-even | Validated fill/costs and predeclared favorable condition | Basis and full quote sequence; stop model still required | Break-even is not zero net P&L absent known costs; unordered return unresolved |
| Partial exit | Validated fill, declared fractions and allocation policy | Contract/quantity/side and quote availability | No executable sizes; allocate fees explicitly; compare whole/partial cohorts |
| Time-based | Validated t_fill, duration and first eligible post-deadline quote | Timestamped Bid/Ask, capture completeness and receipt chronology | Record delay/gaps/session interruption; do not approximate exact 50 seconds |
| Early hypothesis failure | Frozen invalidation and original rules | Existing confirmed close/event evidence, later eligible quote for any fill | Analytical failure is not a price exit; combine without inventing order |

## Acceptance before any comparison or claim

First independently review data, fill/timing/cost contracts and correction policy.
Use deterministic synthetic tests for deadline ties, no quote, stale/future quote,
clock changes, spread changes, session breaks, missing ticks, simultaneous events,
commission uncertainty, prefix/future invariance and unknown excursions. Then a
qualified private export with required tick/quote evidence may be replayed through
a reviewed manifest bridge. Keep original analytical reports frozen and outcomes
separate. Run full/full/prefix and compare logs before metrics. Reserve untouched
out-of-sample intervals and document cohort exclusions and denominators.

Until all prerequisites exist: historical_validation=PENDING, comparisons=NOT_RUN,
metrics unmeasured. No fill, timer service, P&L or performance result is produced in
E2. Exness BLOCKED; DATA_NOT_QUALIFIED; WAIT; execution_allowed=false.
