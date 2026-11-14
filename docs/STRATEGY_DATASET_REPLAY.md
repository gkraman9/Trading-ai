# Manifest-gated strategy replay and evaluation accounting

This adapter connects Strategy Replay Log v1 to the existing local dataset
loader and historical preflight. It adds a version 1 STRATEGY_DATASET_REPLAY
wrapper; it does not change Strategy Replay Log v1, DecisionLog v1, strategy
registry/rule versions, lifecycle policy or confluence thresholds.

## Eligibility and trust boundary

`iat.strategy_dataset_replay.run_strategy_manifest` accepts a private manifest
path and optional typed analytical configurations. There is no provenance
argument or arbitrary Dataset-object entry point: the strict loader derives
provenance from the manifest after verifying its schema and local file hashes.
The shared `iat.historical_replay.dataset_preflight` is also used by the
original historical runner. That refactor preserves its prior reports and
DecisionLog behavior, without executing an extra analytical replay.

The shared path checks:

- Manifest v1/v2 schema, safe local paths, exact CSV/calendar checksums, exact
  symbol, UTC interval openings and declared closed intervals within coverage.
- OHLC validity, chronological continuity/gaps, freshness at the declared end,
  calendar/session assurances and the existing finality requirements.
- Historical source independent-review attestation, v2 usage/instrument/
  timestamp/price-basis/calendar/finality review states, and known lineage.
- M1/M5 OHLC consistency using the existing tolerance. Missing comparison or
  mismatched OHLC rejects replay. Existing evaluation coverage diagnostics
  distinguish uncovered warm-up from evaluation bars.

Historical strategy metrics additionally require the existing coverage rule:
complete evaluation coverage and at least 12 comparable M5 bars. This does not
lower any threshold or turn aggregation into independent evidence. M5 derived
from M1 is labeled INTERNAL_AGGREGATION_ONLY. Synthetic manifests can exercise
short windows but cannot establish historical validation, even at 100% internal
consistency. Caller-provided historical labels alone do not satisfy the gates.

Preflight failure returns no Strategy Replay Log, no window accounting and
`historical_metrics=null`. Status/reason codes explain the rejection, rather
than reporting zero setups for a replay that never ran. Historical validation
remains PENDING and historical comparisons NOT_RUN for those reports.

Attestations and review flags are operator declarations under the existing
manifest contract, not cryptographic proof that a provider certified the data.
A genuinely permitted export still needs independently reviewed source,
permission, dated calendar and closed-bar evidence. Test mocks with VERIFIED
flags exercise code branches only; they are not historical validation results.

## State carried across the boundary

The adapter replays all supplied M1 warm-up history and evaluation history
through one unchanged StrategyReplayLedger. It does not start a second ledger
at evaluation. Every supplied M1 closing timestamp is retained, including
blocked warm-up snapshots. M5 warm-up can precede M1 export coverage under the
existing declared-warm-up rules; M5 alone does not fabricate M1 snapshots.

A v2 evaluation window is opening-time `[start,end)`. Accordingly, closing
timestamps `<= start` belong to warm-up, and `start < close <= end` belong to
evaluation. This matches DecisionLog's existing phase convention. A snapshot
at the exact boundary is processed before the carried-in inventory is captured.
A v1 manifest has no declared warm-up; its full range is evaluated, with zero
carried-in history inferred outside the supplied dataset.

`window_accounting` reconstructs state from chronological lifecycle events,
not from final setup records that might contain future terminal times. Each
phase reports timestamp/blocked counts and per-strategy/direction:

- Snapshot QUALIFIES, ABSTAINS, INVALIDATED and BLOCKED_DATA counts/reasons.
- First-qualified setup IDs/counts, counted only on their first qualification.
- Invalidated-qualified and expired-qualified setup IDs/counts in that phase.
- Unqualified-invalidated anchors, separately from qualified setups.
- Active setup IDs carried into the phase and still active at its end.

A warm-up setup invalidated or expired during evaluation is a carried-in setup
and an evaluation terminal event, **not** another first qualification. Repeated
qualifying snapshots and retired-anchor qualifications never inflate setup
counts. The existing distinct-anchor re-arming and blocked-data suspension
rules are unchanged. Boundary inventories are last-known active lifecycles;
they do not authorize trading or imply current eligibility during blocking.

The original Strategy Replay Log still summarizes the complete replay. The
wrapper alone adds warm-up/evaluation accounting, dataset/preflight metadata
and the bounded eligibility claim. The embedded v1 log retains its original
PENDING/NOT_RUN safety markers. An eligible historical wrapper may report
DATASET_PIPELINE_CHECKS_PASSED and measured evaluation metrics; that means
pipeline checks under the supplied attestations, never broker certification
or profitability. Historical repeat/prefix comparisons are NOT_RUN until
separately executed; one successful run cannot establish repeatability.

## Private execution and publication

From the repository root, using Python 3.11 or 3.12:

```text
python diagnostics/strategy_dataset_replay.py --manifest /private/dataset/manifest.json --report-path /private/evidence/new-strategy-report.json
```

Use platform-appropriate absolute private paths and create the report directory
first. Omit `--manifest` to produce an explicit missing-export BLOCKED report
(exit 3). Synthetic research returns WARN (exit 2), failure exits 1 and a
completed eligible pipeline may exit 0. Optional `--context-config` and
`--intelligence-config` use the existing strict typed config readers; omit
them to retain PR #14 defaults. They are provided for reproducible research,
not implicit threshold tuning. Synthetic tests explicitly use inherited
small-window test configurations.

The runner reserves RUN_INCOMPLETE failure evidence before processing, then
uses existing AtomicEvidence publication. Existing output files are never
overwritten; publication failure cannot leave an old success under that path.
Console output contains status labels only, no raw bars or account details.
Full private JSON reports contain source OHLC in their strategy logs: do not
publish them or third-party raw data to GitHub. This runner has no network,
broker, credential or order-placement path.

## Actual synthetic integration results

The [checked-in audit](source_reviews/strategy-dataset-integration-v1.json)
records four independently executed synthetic manifest cases, file/config/log
hashes, coverage, phase accounting and software comparisons. These fixtures
use 35 M1 bars and preceding M5 history. Prior M5 bars are aggregated from
procedural synthetic parents omitted from the M1 export; every overlapping
M5 bar is exactly aggregated from its five exported M1 bars. This exercises
legitimate prior M5 warm-up without implying independently sourced data.

Counts below refer to each case's intended strategy/direction:

| Case | Warm-up snapshots | Warm-up first qualifications | Evaluation snapshots | Carried active | Evaluation first qualifications | Evaluation invalidations | Evaluation expiries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Continuation bullish | 20 | 0 | 15 | 0 | 1 | 1 | 0 |
| Continuation bearish | 20 | 0 | 15 | 0 | 1 | 1 | 0 |
| Sweep reversal bearish | 25 | 1 | 10 | 1 | 0 | 0 | 1 |
| Sweep reversal bullish | 25 | 1 | 10 | 1 | 0 | 0 | 1 |

Each case has two initial blocked warm-up snapshots and no blocked evaluation
snapshots. Continuation has two qualifying evaluation snapshots but one unique
first qualification. Reversal has two qualifying warm-up snapshots but one
setup; it is carried across the boundary and expires once in evaluation.
No qualified setup remains active at the end of these intended cases.

Full/full reports and log hashes matched for all four cases. Prefix manifests
retain identical raw lineage and warm-up with newly checksummed truncated CSVs.
The first 25 continuation or 30 reversal entries matched full overlaps; warm-up
accounting and carried-in inventories matched. Coverage is 3 or 2 comparable
evaluation M5 bars respectively, below the unchanged 12-bar historical gate,
and proves internal aggregation only. These are software comparisons, not
historical DecisionLog or strategy validation.

## Actual historical availability and remaining evidence

The only available concrete private pilot is the previously reviewed anonymous
publisher archive. The new default-config adapter actually ran its preflight
and rejected it with CANDLE_FINALITY_UNCERTAIN, EVIDENCE_CALENDAR_PENDING,
EVIDENCE_FINALITY_PENDING, INDEPENDENT_REVIEW_PENDING and
SESSION_CALENDAR_REQUIRED. No strategy replay ran for that source. The audit
records the same manifest hash as the earlier source review and no raw prices.

No authorized OANDA export or newly permitted replacement was supplied.
The provider/operator still needs to supply an identifiable feed/entity,
applicable offline-use permission, UTC/price-basis conventions, dated sessions
and exceptions for the entire warm-up/evaluation range, closed-bar/capture
completeness evidence and independent review. See
[SOURCE_QUALIFICATION_REVIEW.md](SOURCE_QUALIFICATION_REVIEW.md).

Historical validation therefore remains **PENDING**, comparisons **NOT_RUN**,
and historical metrics **unmeasured (`null`)**. Exness remains **BLOCKED**,
`signal=WAIT`, `execution_allowed=false`. No terminal validation or trading
performance is claimed, and all PRs remain unmerged. Full-prefix recomputation
and observation-heavy logs retain the prior implementation's memory/time limits.

## Local verification

The complete suite passed on Python 3.11.9 (586 tests, 59.123 seconds) and
Python 3.12.14 (586 tests, 38.212 seconds): 568 inherited tests plus 18 new
integration tests. These include source/lineage/calendar gates, checksums,
malformed OHLC, unclosed bars, consistency rejection, both strategy directions,
boundary carry-in, exact-boundary and blocked-snapshot accounting, repeatability,
prefix equivalence, compatibility and atomic publication failure. Final
Linux/Windows CI results are linked from the draft PR.
