# R1 typed timeframe and interval foundation v1

Implemented as an additive offline module, `iat/timeframes.py`, based on draft
PR52 at `6bdee14174f9087ab020afb432c650f0e349f506`. The architecture, research
protocol and roadmap were reviewed in full. This implements R1 contracts only,
not R2 observations or a generalized live market-data/strategy engine.

The first performance benchmark remains the existing deterministic M1/M5 strategy
with USD50 virtual capital. R1 adds no performance measurement or improvement
claim. Exness calendar correction, E4.7 review and historical paper qualification
remain independent workstreams. No new timeframe is a prerequisite for the baseline.

## Boundary and compatibility

No legacy Python module, API, detector, context/selected hypothesis, strategy,
paper/risk/cost policy, live SDK allowlist, dashboard or calendar is modified.
Legacy DURATIONS/TIMEFRAMES remain M1=60/M5=300. The new module is not imported by
any runtime path. An empty TimeframeProfile enables nothing; explicit frame
bindings do not enable MT5 acquisition or legacy analysis of the added frames.

All reports retain READ_ONLY_SHADOW, WAIT, execution_allowed=false, Exness BLOCKED,
DATA_NOT_QUALIFIED, historical_validation=PENDING and historical_comparisons=NOT_RUN.
There are no broker/order/credential/AI/paper activation dependencies or calls.

## Typed definitions and provider mapping

FrameName declares fixed M1, M3, M5, M15, M30, H1, H4 plus reserved D1, W1, MN1 and
TICK names. FrameDefinition v1 exposes only these fixed contracts:

| Frame | Fixed seconds |
|---|---:|
| M1 |60|
| M3 |180|
| M5 |300|
| M15 |900|
| M30 |1,800|
| H1 |3,600|
| H4 |14,400|

D1/W1/MN1 raise CALENDAR_SEMANTICS_REQUIRED. They have no seconds entry and cannot
be constructed as fixed intervals. TICK raises TICK_IS_NOT_OHLC. Broker-local grids,
implicit aliases, inferred native constants and arbitrary provider mappings are
unsupported. H4 UTC anchor shifts need separate dated contracts; a window spanning
an unsupported shift blocks, rather than extrapolating a guessed DST policy.

The sole resolver is FIXED_UTC_GRID_V1: explicit UTC anchor, matching canonical
provider frame name and exact duration. Anchor microseconds are forbidden; grid
alignment uses integer microseconds, not floating epoch modulo. No epoch-zero
anchor is assumed. Validity must cover the entire selected interval and cutoff.
UTC timestamps with nonzero offsets or missing zones are rejected, not silently
interpreted as broker wall clock. Provider-specific local/calendar adapters are
separate future review work, not automatic D1=24h/W1=7d/MN1=30d assumptions.

FrameBinding.resolve returns nominal bounds validated against the declared source
interval contract. FrameBinding.interval returns a frozen FixedInterval v1 with
frame, UTC bounds and binding hash. Neither establishes bar finality or analysis
eligibility by itself. Use assess_closed_prefix for source/as-of/session checks.

## Exact evidence and strict configuration

EvidenceDocument stores immutable exact UTF-8 JSON bytes. SHA256 covers those
bytes, not normalized text. Duplicate keys, unsupported versions/fields, nonfinite
constants and documents above65,536 bytes reject. EvidenceStore accepts at most64
unique typed documents; decoded documents are independent copies. No document
reference, label or checksum can substitute for the actual matching bytes.

Each frame binding requires four evidence documents; every envelope has exactly
`version`, `kind`, `available_at_utc`, `claims`. Source evidence must be explicitly
available by the research cutoff. Its bytes and declarations are mechanically
checked; they are NOT independent review, provider certification or qualification.

| Kind | Exact claim fields |
|---|---|
| SOURCE |provider, feed, symbol, price_basis, provenance, source_revision|
| INTERVAL |source_sha256, frame, provider_frame, mapping, duration_seconds, anchor_utc, grid_timezone, valid_from_utc, valid_until_utc, bar_policy|
| CALENDAR |source_sha256, coverage_start_utc, coverage_end_utc, phases|
| FINALITY |source_sha256, interval_sha256, policy, correction_policy|

SOURCE currently scopes to XAUUSD and explicit BID/ASK/MID. SYNTHETIC_FIXTURE is
mechanically admissible for labeled offline testing. DECLARED_OFFLINE contracts
can be represented, but assessment returns INDEPENDENT_QUALIFICATION_REQUIRED;
no independent historical-source bridge or approval mechanism is introduced.
This avoids treating caller declarations and document hashes as market truth.
Do not relabel real exports as synthetic to bypass their existing qualification.
No new native/derived historical lineage is certified by R1.

FINALITY policy must be EXPLICIT_FINAL_CLOSE_AND_AVAILABILITY and correction policy
REVISION_BOUND_NO_RETROSPECTIVE_REWRITE. These declarations do not infer finality
from age, a closed flag alone, native position1, or an aggregation OHLC match.

CALENDAR phases partition finite coverage exactly with explicit UTC start/end,
quotations OPEN/CLOSED/UNKNOWN and new_positions ALLOWED/DISALLOWED/UNKNOWN. Gaps,
overlaps, contradictions and an unfinished coverage partition reject. UNKNOWN
quotation coverage blocks a request that uses it. Closed quotes cannot grant new
positions. Quote-open/close-only phases may support OHLC while keeping execution
false and reporting new-position permission DISALLOWED. No Exness schedule or
verification flag is created or approved by these synthetic declarations.

TimeframeProfile v1 JSON has exactly `version`, `bindings`, `edges`. Each binding
has version, frame, source/interval/calendar/finality SHA256 references,
required_closed_bars and max_slots. from_json requires an EvidenceStore and checks
all references and cross-source/frame/finality bindings. Duplicate frames, unknown
names, unsupported mappings, bad types (including bool-as-int), graph cycles,
duplicate edges or edges to unconfigured frames reject. Edges only declare a
finite dependency graph in R1, not strategic voting or direction predicates.

Direct typed construction still requires proof binding at use. No default provider,
source, anchor, finality, calendar, enabled profile or evidence approval is inferred.
For complete executable examples see tests/timeframe_fixtures.py; its provider,
feed, prices and session coverage are explicitly invented, not Exness evidence.

## Closed-prefix eligibility

assess_closed_prefix takes a typed profile/store, one explicitly enabled frame,
raw rows, an explicit window_start_utc and frozen as_of_utc. The request window is
not inferred from the first returned bar: leading gaps must remain detectable.

Each consumed row has exactly frame, provider_frame, provider, feed, symbol,
price_basis, source_sha256, opened_at_utc, closed_at_utc, available_at_utc, finality,
revision and open/high/low/close. Metadata must match its evidence binding. Verified
close must match the explicit grid; availability cannot precede close or exceed
as_of. Finality must be FINAL and revision a nonnegative integer. Existing
validate_candles performs OHLC/chronology validation on the consumed prefix.

Only intervals whose nominal end <= as_of can be considered. After the first
future/forming opening, its OHLC/extra payload and later rows are not inspected.
A nominally closed but late-published bar blocks with SOURCE_NOT_AVAILABLE_AS_OF;
its price is never admitted early. Prefix chronology and exact expected coverage
are validated; this does not certify ordering or completeness of an unseen tail.

Expected slots come from the configured UTC anchor. Fully declared closed quote
slots are counted separately, not classified as missing data. Full active slots
must match every selected open, including leading/middle/trailing coverage. The
cutoff must be within known open quotation coverage. Required history is explicit;
source windows and validity must extend beyond the cutoff, not merely end there.

R1's FULL_QUOTATION_INTERVALS_ONLY policy deliberately blocks any slot containing
both an open and a closed quote segment, including unreviewed partial session-close
bars. It does not move a21:58 boundary to22:00 or certify a partial H1/H4 bar. A
reviewed partial/multi-session interval policy is deferred. Off-grid slots and
unknown holiday/maintenance coverage also fail closed.

The successful status is ELIGIBLE_SYNTHETIC_ONLY: a mechanical closed prefix, not
an eligible trading/context report. It contains normalized supplied OHLC, interval
bounds/availability, hashes, counts, current quotation permission and limitations.
Any failure returns BLOCKED with fixed reason codes and no bars. Unknown/malformed
inputs never produce a directional hypothesis or fabricated replacement price.
validate_foundation_report recomputes the complete canonical report; changing a
checksum is not source authentication, and numeric0 cannot impersonate false.

A profile's explicit bar quota is not sufficient proof of feature warm-up. R2 must
derive detector-specific windows and still require confirmed pivots; R1 never
claims that three valid bars establish structure, ATR, momentum or a strategy.

## Independent identities and bounds

MTF:R1:INTERVAL IDs bind source/interval evidence and exact bounds. Observation IDs
add normalized prices, availability, revision and finality evidence. A correction
can change an observation revision without pretending another interval occurred.
Old emitted reports are immutable returned values and are never rewritten.

event_reference preserves original_event_id verbatim, binds the original report
hash and creates a separate MTF:R1:EVENT_REF identity scoped to the sidecar config.
It is reference-only, not an authenticated event producer. Configuration revisions
can produce multiple references to ONE underlying event. No legacy Phase7 index,
canonical candle/pivot/CHoCH ID, DecisionLog or strategy/paper journal is modified.

Source rows are capped at5,000; required history is3..5,000. Explicit slot budget is
bounded at10,000 (including closed slots); evidence/phase/profile/graph sizes are
bounded. A too-long window is blocked, not shortened. Per-request resolution binds
proofs once and reuses interval arithmetic; this is not an analytical frame cache.
Cache scheduling and detector updates remain later MTF milestones.

## Validation and sequencing

The53 focused tests pass locally on Python3.11.9 (8.586s) and3.12.14 (7.126s).
They include exact seven-frame contracts, missing/duplicate/out-of-order bars,
known overnight closures, partial boundaries, late publication, future/forming
payload exclusion, DST anchor contracts, unknown zones, missing finality/evidence,
source/basis conflicts, resource limits, strict report types and immutable proofs.
Three direct equivalence tests compare full legacy context/scenario/strategy/
DecisionLog outputs and hashes before/after R1 use, and regenerate the unchanged
committed USD50 paper golden twice. These are synthetic correctness/accounting
checks, not measured strategy profitability or historical validation.

The inherited full suite and Linux/Windows Python3.11/3.12 CI run on the final PR
head; consult that PR's final result table for actual counts, not this initial
focused result. Actual PowerShell5.1 startup and ValidateOnly checks are preserved.
No live higher-timeframe acquisition or dashboard feature is added.

After R1 passes, propose R2 separately: M15 observation-only sidecar using the
existing detectors behind an interval-aware adapter, unchanged M1/M5 decisions,
source-bound closed/final/available prefixes and explicit detector warm-up. Do not
start R2 automatically. Do not judge MTF performance until the unchanged USD50
M1/M5 baseline is measured under a qualified source and matched cost/risk protocol.
