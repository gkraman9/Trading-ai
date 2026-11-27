# Matched multi-timeframe experiments: proposed protocol v1

DESIGN ONLY; no experiments or profitability measurements have been run here.
All historical metrics are UNMEASURED, historical validation PENDING and historical
comparisons NOT_RUN. Synthetic fixtures establish software behavior, not an edge.
See [architecture](MULTI_TIMEFRAME_INTELLIGENCE_ARCHITECTURE.md) for the frozen
M1/M5 boundary and required source/interval evidence.

## Arms and staging

| Arm | Required observation frames | Admission milestone | Status now |
|---|---|---|---|
| A | M1 + M5 | Unchanged deterministic strategy/paper baseline | Existing synthetic-only contracts; historical metrics unmeasured |
| B | M1 + M5 + M15 | Fixed-frame and M15 hierarchy review | PLANNED / NOT_RUN |
| C | M1 + M5 + M15 + H1 | H1 interval/source validation and availability tests | PLANNED / NOT_RUN |
| D | M1 + M5 + M15 + H1 + H4 | H4 alignment, warm-up and hierarchy review | PLANNED / NOT_RUN |
| E | M1 + M5 + M15 + H1 + H4 + D1 + W1 | Independently evidenced daily/weekly calendars and sufficient preceding history | PLANNED / NOT_RUN |

Compare every admitted arm with A and each increment with its predecessor. M3,
M30 and MN1 are architecture extensions, not unannounced extra arms. Tick input
is a shared execution-research clock/price source across all applicable arms, not
another direction vote. Do not vary quote fidelity by arm and call it a timeframe
effect. No full A–E rollout is required before baseline work can proceed.

Two distinct experiments must not be confused:

1. Observation-only expansion: attach the new context sidecar while decisions,
   entries, exits and paper accounting remain byte/hash equivalent to A under
   identical sources and config. Differences in trade metrics here indicate a
   regression, not a successful higher-timeframe strategy.
2. Preregistered context-filter experiment: evaluate the unchanged baseline setup
   predicates, then apply a separately versioned causal context acceptance policy
   to those same candidate IDs. Policy states may accept, reject or abstain, with
   evidence and reason codes. It cannot create entries, move stops, change risk,
   choose a favorable exit or override a safety gate. No filter is implemented or
   selected in this documentation milestone. A more general strategy change
   requires another named experiment and cannot be attributed solely to context.

Hierarchy predicates, role graphs and any parameter selection must be frozen before
examining evaluation outcomes. No majority voting, hindsight threshold tuning or
unvalidated confidence percentages. Higher-timeframe agreement is not evidence of
profitability. If review cannot define a reproducible policy, keep the arm blocked.

## Identical inputs and evaluation clock

Freeze source/provider/feed and symbol, BID/ASK/MID basis, native/derived lineage,
raw/normalized checksums, dated calendar/finality/correction/permission evidence,
loader/preflight version, code head, detector/strategy/risk/fill/latency/cost/spec
hashes and scenario/overlay versions. Keep raw data and real-data full journals
private. Declared provenance or a mechanically valid CSV never substitutes for
independent qualification. Native OHLC and derived aggregates are distinguished;
aggregation consistency is internal validation only.

Use one declared UTC evaluation window and the same eligible M1 decision schedule
for all arms. Use each frame's own explicit preceding warm-up window, with enough
history for the largest required arm, available before evaluation. Select the
window using evidence/coverage criteria before outcomes, not the best-performing
subperiod. D1/W1 evidence/warm-up may be unavailable: mark E unavailable, do not
invent bars, shrink warm-up or replace E's requirements with D's.

At each cutoff join only source-available confirmed prefixes. Later HTF closes or
pivot confirmation cannot revise earlier choices. Finalized-input full/full hashes,
common-cutoff prefix equivalence and future-append invariance are prerequisites.
Outcome observation cutoffs/tails are separate from evaluation entry times. An
unfinished exit horizon or unknown OHLC ordering stays unresolved. Preserve the
existing 5/15-minute journal reviews as reasoning reviews, not trade returns.

For capital comparisons, each isolated account receives the same explicit initial
capital (USD50 for the current paper reference), currency, no replenishment,
position/concurrency constraints, risk policy, minimum-lot/step rules, specification,
margin/stop-out policies, latency and costs. Fees/financing, adverse slippage/gap
allowances and spread treatment are identical, and missing costs are not zeros.
Each arm sizes from its own causal equity under the same policy; do not force equal
volumes after equity diverges or increase risk to reach the minimum lot. For
accepted common setups the fill selection function is identical, without choosing
more favorable quotes for an arm. Existing synthetic-only execution research needs
a reviewed manifest-gated bridge before qualified historical inputs can enter it.

A matched conditional setup comparison and separate chronological portfolio
comparison answer different questions. Report both distinctly; portfolio states
can diverge because rejected entries change capital/concurrency, even when rules
and starting capital are identical.

## Coverage, denominators and missingness

Keep an explicit record for every scheduled evaluation timestamp and every unique
baseline candidate. Distinguish frame NOT_CONFIGURED, unavailable, insufficient
warm-up, data-quality blocked, session-closed, strategy abstention, context rejection,
capital rejection, accepted setup and unresolved outcome. Snapshot totals and
unique setup/lifecycle totals are separate; repeated qualification is not another
opportunity. Carry warm-up-active setups into evaluation without double-counting
first qualification, and keep earlier account state explicit.

Primary results cover the entire preregistered window, including blocked/rejected
opportunities. Also report per-frame eligible/required bar counts, eligible-time
coverage, comparable aggregate counts where meaningful and cross-frame gaps. A
complete-case paired sensitivity view may use common eligible timestamps, but
must show exclusions/attrition and cannot replace the primary result. Do not drop
blocked HTF intervals and compare a favorable remaining subset with all of A.
If underlying source qualification fails, no historical arm runs. A frame-specific
failure blocks dependent arms; a shared feed/basis/checksum failure blocks all
implicated inputs. An unresolved open position is not a zero loss or a free slot.

## Descriptive metrics (future measurements)

| Requested metric | Definition / required denominator | Missing/edge-case policy |
|---|---|---|
| Net expectancy | Sum of net hypothetical P&L / resolved closed positions, in account currency; report sample size and unique setups | Zero closed positions: null with reason; incomplete/unresolved outcomes reported separately, not removed silently |
| Profit factor | Sum of positive net closed-position P&L / absolute sum of negative net closed-position P&L, after the same declared costs | No losses: undefined/null with numerator and denominator, not a validated infinite edge; no trades likewise unavailable |
| Drawdown | Maximum decline from the causal equity high-water mark; absolute and percent, with common mark-observation clock and cash-flow policy | Missing quote marks make affected current/path estimates unknown; retain observed drawdown and known coverage, never forward-fill a guaranteed price |
| Capital survival | Survival/exhaustion state through the common cutoff, first exhaustion time and duration; negative balances retained | One deterministic path gives a state, not a survival probability; incomplete marking/outcomes: unresolved |
| Opportunity frequency | Unique baseline qualified setup IDs and accepted setup IDs per declared eligible session/time unit; show scheduled/eligible exposure | Count setup anchors once; show blocked exposure and warm-up carry-in; do not count every snapshot as a setup |
| Rejected opportunities | Unique candidate IDs by strategy/context/safety/data/capital reason, plus snapshot-level counts | Report overlapping reasons and distinct primary totals separately; rejected does not mean a missed profitable trade |

Also report risk-budget exceedances, gap-through losses, unresolved exits, account
restrictions, margin warnings, fees, financing and coverage. The earliest benchmark
is deterministic correctness, not highest net return. OHLC-only data cannot measure
exact tick timing, Bid/Ask execution, slippage or first-event order. Where that
information is required, metrics stay unmeasured/unresolved rather than fabricated.

Compare paired differences under the same frozen window and policies. Timeframes
and setups are correlated; do not treat each bar as an independent trial or assign
confidence percentages. Use preregistered chronological development/holdout windows,
record every attempted arm/policy and control for multiple comparisons in any later
statistical study. Do not pick a winner on the evaluation sample and call it validated.
Sensitivity studies change one explicitly named factor and report separately.

## Required research output

A later report must contain arm/profile and rule versions, code/source/config hashes,
full warm-up/evaluation/outcome ranges, qualification evidence, per-frame coverage,
all snapshot/setup/rejection/outcome denominators, deterministic log comparisons,
the requested measured metrics or explicit reasons they are unmeasured, differences
versus A, uncertainty and limitations. A–E status is NOT_RUN until these prerequisites
and the separate bridge are implemented and independently reviewed.

READ_ONLY_SHADOW, WAIT and execution_allowed=false remain invariant. Exness stays
BLOCKED; no live paper activation, real/demo orders, source approval or automatic merge.
