# Support/Resistance Rejection Research v1

An isolated original IAT experimental composition: `SR_REJECTION_M1_CONFIRMATION`, rule `1.0.0`, validation status `SYNTHETIC_ONLY`. This implements the reviewed specification in [the automated V3 audit](MARKET_INTELLIGENCE_V3_AUTOMATED_REVIEW.md). It never registers with the existing strategy registry, changes the four adaptive candidate rows, changes confluence thresholds, selects a trade or authorizes execution.

Base: PR #43 head `ae0fa46959315ee18e9899a6fd02b1e9b1cadd48`. The new branch targets `feat/iat-v3-unified-market-view`; PRs #41/#42/#43 remain draft and unmerged. Their source, contracts, journals, execution gates and Exness profile are unchanged.

## Interfaces

```python
from iat.intelligence.sr_rejection import (
    evaluate_sr_rejection, validate_sr_result, SRRejectionLedger, validate_sr_log,
)

# Typed context + the exact V3 view already built from it.
# Supply matching optional V3 inputs if the original view used them.
result = evaluate_sr_rejection(view, context, view_inputs=matching_view_inputs)
validate_sr_result(result, view=view, context=context, view_inputs=matching_view_inputs)
ledger = SRRejectionLedger()
entry = ledger.record(view, context, view_inputs=matching_view_inputs)
validate_sr_log(ledger.to_dict())
```

The module has no terminal, account, provider, order, service, network or wall-clock dependency. It loads only a checked-in public schema at import. No new HTTP endpoint or live runner is provided. A ledger is an explicit single-threaded offline object, not a default strategy or background service. Nothing writes a file automatically. Validate before publishing a NEW private artifact with the existing atomic/no-overwrite utilities; never append trials to original journals or commit real-data logs.

`iat.sr_rejection_dataset.replay_sr_rejection(symbol, m1, m5, ..., as_of=None)` is a labeled synthetic-fixture helper. It visits supplied M1 closes in order, reuses the causal context and V3 gates, and never invents snapshots for missing candles. It has no historical-provenance override. `run_sr_manifest(path, ..., as_of=None)` is the separate manifest/preflight entry point.

## Exact predicates and availability

Both directions are evaluated independently for every existing canonical M1/M5 support/resistance zone. No new clustering, pivot, zone, indicator, pattern-recognition or score algorithm is added. Zone geometry is copied exactly, without rounding or moving boundaries to manufacture a match.

| Condition | Bullish | Bearish |
|---|---|---|
| Existing M5 structure | BULLISH or RANGING | BEARISH or RANGING |
| Existing zone | SUPPORT, FRESH or TESTED | RESISTANCE, FRESH or TESTED |
| Knowledge | Zone confirmed by T opening | Same |
| P | Immediately preceding closed M1, range does not touch zone | Same |
| T | Range intersects fixed zone; close inside inclusive boundaries | Same |
| C | Distinct immediately following closed M1, close > open | Close < open |
| Break | Close strictly > upper + existing break tolerance | Close strictly < lower - tolerance |
| Contradiction | No fresh opposing BEARISH M1 CHoCH at C | No fresh opposing BULLISH M1 CHoCH at C |

P/T/C must be contiguous and eligible. Qualification is timestamped at C close only. A closed T with valid P/T and no C is CANDIDATE, never QUALIFIED. A fresh opposing CHoCH invalidates an otherwise anchored confirmation even if an alignment label agrees. Existing CLOSE or WICK event policy is retained and recorded upstream; this extension does not relabel a wick as close confirmation. The raw-OHLC regression explicitly exercises an opposing WICK-policy event.

The cutoff must equal the newest available M1 close. Re-observing an old close at a later timestamp is blocked rather than treated as a new eligible close. M5 must satisfy inherited quality/freshness/closed-bar rules. A direct unfinished M5 fails existing gates; causal prefix selection excludes future/unclosed M5. Missing frames, malformed/mismatched views or BLOCKED sessions fail closed. UNKNOWN is not approval: explicitly synthetic observations may be studied while all session and qualification uncertainty remains visible. Historical-labeled typed context alone is blocked.

Overlapping M1/M5 zones remain independent candidates with distinct identities; there is no new rank, tie-breaker, arbitrary score, BUY/SELL output or automatic selection. Same-geometry zones from two frames are not claimed statistically independent. When no touch episode exists, EVALUATED with an empty candidate list and NO_TOUCH_EPISODE is an abstention, not positive confirmation. Individual attempts that fail predicates explicitly record ABSTAINED and reason codes.

## Identity and frozen lifecycle

The setup ID hashes strategy, rule version, exact symbol, direction, canonical zone ID and first-touch T candle ID. It never uses a window index, current score, subsequent confirmation timestamp or local clock. P's non-touch requirement defines a new touch episode; a continuing multi-bar touch cannot re-arm the same setup. Distinct zones/touch episodes remain distinct, including when an earlier setup is still active.

| State / observation | Behavior |
|---|---|
| CANDIDATE | Valid P/T; wait for immediately following closed C |
| QUALIFIED | All confirmation predicates hold; count once per identity |
| ABSTAINED | Missing/failed predicate, or a candidate's immediate confirmation was not established |
| INVALIDATED without qualification | Unqualified anchored confirmation has opposing CHoCH; never counted as invalidated-qualified |
| INVALIDATED after qualification | Later eligible close loses the frozen opposite zone edge by existing tolerance, or fresh opposing M1 CHoCH |
| EXPIRED | Five distinct observed eligible M1 closes after C, excluding C; no earlier terminal transition |
| BLOCKED observation | Record rejection and uncertainty; do not qualify, invalidate, expire, supersede or increment eligible-close count |

A repeated identical observation at the same cutoff returns the original entry without incrementing counts. Changed same-cutoff input, backward cutoffs, configuration/symbol/provenance changes, dropped full-prefix history or late/corrected candles are rejected atomically. No existing entry is rewritten. Once invalidated, expired or abstained, the same anchor does not re-arm.

Expiry uses **five observed eligible closes**, not five wall-clock minutes or five polls. Blocked, omitted or session-closed intervals are not assumed eligible; expiry is established only at a valid observation. A caller wanting complete lifecycle coverage must visit every supplied M1 close, as the replay helper does. Sparse manual observations describe only visited eligible observations, not the first event in an unobserved interval. A candidate whose C observation was blocked cannot be retrospectively qualified from a later snapshot. Ending a replay does not expire active setups.

Zone geometry/P/T references are frozen at first appearance; C, original exit hypotheses and qualification timestamp freeze at qualification. Subsequent classifications cannot rewrite them. The summary separates snapshot/blocked counts from unique qualified, invalidated-qualified, expired-qualified and unqualified-invalidated counts. Final inventories are last-known research setups, never positions or trades.

## Paper-only exit hypothesis

At C, freeze pre-existing FRESH/TESTED opposing zones beyond C's observed close, if any. A later eligible close through their far boundary plus existing tolerance is a paper observation, not an executable target. No opposing zone means unavailable, without manufacturing another level.

The first observed qualifying paper criterion is recorded separately from lifecycle: opposing-zone close, invalidation or five-close expiry. Simultaneous criteria on the same bar produce UNRESOLVED_EVENT_ORDER, without guessing OHLC path order or picking a profitable interpretation. No executable entry, stop, target allocation, size, order or P&L is produced. The copied current M1 close and zone prices are observed source facts, not execution prices. Existing 5/15-minute reasoning journal first-breach criteria remain unchanged.

## Contracts and source audit

`config/sr-rejection-research-v1.schema.json` defines snapshot version 1. `validate_sr_result` enforces shape, fixed safety, checksums, policy, canonical setup identity, reference chronology, latest close, outcome/condition consistency and optional exact source-bound recomputation. Independently rechecksummed EVALUATED snapshots with missing/blocked quality, missing frames or restricted sessions are rejected before ledger progress. Session declarations are revalidated using the existing V3 session checker. `validate_sr_log` reconstructs every lifecycle transition/inventory/count from the versioned snapshots. It does not authenticate source data from an unkeyed hash.

| Binding | Enforcement |
|---|---|
| V3 view ↔ typed context | Existing exact source-bound `validate_market_view_v3`; optional matching V3 inputs must also be supplied |
| Configuration | Original context/intelligence SHA-256 and literal inherited `break_tolerance` in the explicitly typed binding object; fixed extension policy digest |
| Zone / P/T/C | Existing canonical IDs and source availability; zone knowledge at T and contiguous closed candles |
| Opposing evidence | Existing current M1 TRANSITION IDs, separately labeled in the evidence metadata; no raw-candle ID substituted as a structure-change fact |
| History | Full causal prefixes; canonical raw candles tracked separately from contextual pattern IDs, which may change between snapshots |
| Manifest | Existing strict loader/checksum/source/calendar/finality/alignment preflight before any historical-labeled replay |
| Qualification | Never promoted by snapshot, setup qualification, source hash or synthetic labels |

Standalone results accept only synthetic-research provenance. The manifest path derives provenance from loaded data, never from a caller override. Historical inputs additionally require v2 native-same-feed lineage and sufficient scoped evaluation coverage; derived M5 remains an internal aggregation check, never silently substituted as native. Warm-up is carried into evaluation, with carried-in qualified IDs and evaluation-first qualifications reported separately. A common-cutoff replay of the same manifest retains its data hashes; different/truncated source files are different bindings and must not be claimed hash-identical.

Every result stays WAIT, execution_allowed=false, DATA_NOT_QUALIFIED, Exness BLOCKED, historical validation PENDING and historical comparisons NOT_RUN. Strategy validation remains SYNTHETIC_ONLY even if eligible historical data later exercises the software. Historical metrics are null in this milestone. No genuine independently qualified export was available or replayed here.

## Synthetic examples, tests and performance

[The synthetic audit](research_audits/sr-rejection.synthetic.json) records source-derived positive bullish/bearish examples, candidate/no-confirmation cases, canonical hashes, the selected-cutoff lifecycle summary, original configuration hashes and measured benchmark. The fixture is independently written for this extension. Its standalone M1/M5 histories are invented predicate-test observations, with no real feed consistency claim. Separate temporary CSV tests aggregate synthetic M1 to M5 and explicitly report INTERNAL_AGGREGATION_ONLY while exercising the real manifest/preflight path.

The selected seven-close example has two overlapping bullish setups, each counted once and expired after five later eligible closes: 2 unique qualified, 2 expired-qualified, 0 invalidated-qualified. These are setup counts, not executed trades or performance statistics. Some reducer-only tests deliberately construct labeled synthetic observation contracts; they are distinct from the end-to-end raw-OHLC tests. An actual raw-OHLC opposing-CHoCH case verifies unqualified invalidation without relying on those controls.

From the checkout on Windows Python 3.11:

```powershell
py -3.11 -m unittest discover -s tests -p test_sr_rejection.py -v
py -3.11 tests/benchmark_sr_rejection.py --iterations 3
```

Benchmark methodology: prebuild synthetic contexts/views, one excluded warm-up, three iterations, GC before each, `perf_counter_ns`, and Python `tracemalloc`. Source validation remains enabled; the eight-close case includes full log validation. Python 3.12 Linux measurements: snapshot median 448.400 ms / peak 696,297 traced bytes; eight-close lifecycle median 4,412.450 ms / peak 2,535,064 bytes. All repeated hashes matched. These shared-machine, tracing-enabled small samples exclude context/view creation, are not RSS measurements or live-latency guarantees, and say nothing about profitability.

Regression scope covers both directions, P/T/C timing, actual late-created zones, bad zone state, wrong M5 structure, overlaps, current opposing CHoCH, missing/stale/unfinished/late data, unknown/blocked sessions, identity, duplicate/late/corrected input, new touches, qualified versus unqualified invalidation, five-close expiry and blocked suspension, ambiguous paper exits, source hash tampering, raw/full/prefix/future-append equivalence, manifest preflight/carry-in/read-only files, unchanged original strategies/DecisionLog and execution-disabled safety. Exact focused/full/CI results are recorded against the draft PR head.

CI registers the new feature branch and PR #43 target and runs the entire inherited/new Linux/Windows Python 3.11/3.12 matrix. The job execution budget is 20 minutes (previously 15): the inherited Windows 3.11 unit suite alone took 610.686 seconds and the new focused tests add roughly a minute locally. No market freshness, clock-skew, trading, session, risk or analytical threshold is relaxed.

## Limitations and next milestone

Full-prefix recomputation and copied reference registries are deliberately bounded research implementations, not high-rate stream optimizations. Ledger use is single-threaded; complete observation coverage requires the chronological replay path. Hashes and typed reports do not establish feed authenticity, finality, rights, calendar approval or independent human sign-off. Root UNKNOWN, research QUALIFIED and DATA_NOT_QUALIFIED describe different layers and must not be conflated.

Next: an independent automated/human review of this single-family contract and its expiry/blocked-interval accounting, then qualified-data research replay when genuinely eligible inputs exist. Do not activate the strategy or add other families until those reviews define the next narrow scope. All existing PRs remain unmerged.
