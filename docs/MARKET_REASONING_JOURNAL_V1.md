# Market Reasoning Journal v1

This is an offline, append-only reasoning review over Adaptive Market Intelligence
v1. It freezes what IAT assessed at each evaluated M1 close, then records separate
later observations under a declared review policy. It does not tune scores,
strategies, confluence thresholds or ranking rules, and does not model trades,
returns, stop/take-profit orders or profitability.

## Original assessments and revisions

`replay_reasoning_journal` consumes the existing causal `replay_adaptive` output.
Every original adaptive report is stored verbatim, including its checksum,
regime, independent volatility, scenario ranks/ties, evidence IDs, assumptions,
invalidation conditions, strategy fit, uncertainty and what would change the
assessment. An assessment ID binds symbol, UTC timestamp and original report
hash. The journal does not replace old reports when later observations arrive.

Each run fixes symbol, provenance, adaptive configuration hashes and review
policy. A changed configuration/provenance requires a new journal. Duplicate or
backward evaluation clocks and changes to previously observed candle values
are rejected transactionally. Returned records and serialized output are detached
copies. The original adaptive, DecisionLog v1, Strategy Replay Log v1 and PR #15
manifest/warm-up/evaluation contracts remain unchanged.

A material assessment revision records changes in availability status, regime,
scenario rank groups, leading scenario set, volatility classes or strategy fit.
Numeric score/ATR changes within identical semantic states remain in each frozen
report but do not inflate the material-change counter. Tied groups are compared
as sets; presentation order does not invent a ranking change.

Revision records link old/new assessment IDs and UTC time, frozen before/after
states, new/withdrawn evidence IDs, scenario support/opposition deltas, score
changes and current reason/conflict codes. These are proximate evidence changes,
not proof of counterfactual causation. BLOCKED/UNKNOWN transitions are retained,
including entry/exit from initial structural warm-up.

## Review policy and horizons

`ReviewPolicy` version 1 defaults to elapsed UTC horizons **5 and 15 minutes**.
`criteria_version=1` fixes the method below. Explicit custom horizons are allowed
as a sorted, unique tuple of 1–8 integer minute values in [1,240]; booleans,
duplicates, unsupported versions and noninteger values are rejected. The policy
checksum covers both configuration and criteria. Shortened horizons in some
unit tests are labeled synthetic settings, not changes to analytical thresholds.

At the original assessment, freeze a reference envelope:

- Upper bound: maximum of the latest closed M1 candle high and the HIGH-pivot
  prices cited by its original M1 STRUCTURE interpretation.
- Lower bound: minimum of that candle low and the cited confirmed LOW pivots.
- Preserve the original candle/pivot evidence IDs and freeze timestamp. UNKNOWN
  or BLOCKED originals have no eligible reference envelope.

This envelope is a declared IAT observation proxy. It is not a trade entry,
price target, trading range certification, or a definition of whether the whole
adaptive interpretation was correct.

Only later completed M1 candles with `original_time < close <= due_time` enter
that horizon. Continuous eligible M1 minute coverage is required. The **first
strict boundary breach** determines the observation outcome:

| Later observation | Bullish scenario | Bearish scenario | Neutral scenario |
| --- | --- | --- | --- |
| First breach only above upper bound | SUPPORTED | CONTRADICTED | CONTRADICTED |
| First breach only below lower bound | CONTRADICTED | SUPPORTED | CONTRADICTED |
| No breach through a complete eligible horizon | UNRESOLVED | UNRESOLVED | SUPPORTED |
| Both bounds crossed in the first breach candle | UNRESOLVED | UNRESOLVED | UNRESOLVED |

Equality is not a breach. OHLC does not establish the within-candle sequence of
a dual breach, so this policy never guesses it from the open/close or favorable
price movement. A later reversal does not erase an earlier, temporally ordered
first breach under this particular criterion. Accordingly, a supported first-
breach review is not a claim that the market stayed directional afterward.

The following independently require UNRESOLVED:

- The elapsed horizon is incomplete.
- The original assessment is UNKNOWN/BLOCKED, lacks a leading scenario or has
  no established reference envelope.
- Any evaluated assessment inside the review interval is BLOCKED, expected M1
  coverage is incomplete, or required observations first arrive late.
- The decisive first-breach bar has ambiguous OHLC event order.

All three stated scenarios are reviewed, rather than selecting a scenario after
seeing its outcome. For a unique original leader, the assessment-level review
uses that scenario's result. Original ties remain assessment-level UNRESOLVED
with ORIGINAL_SCENARIO_TIE; individual tied members still receive explicit
scenario outcomes. There is no retrospective tie winner.

## Availability and append-only outcomes

Each observed M1/M5 candle has a content/time identity, closed timestamp and
`first_seen_at_utc` in the journal. First-seen time describes IAT journal
availability, not an independently verified broker capture timestamp. Candle
facts must match the adaptive source registry and cannot appear before closing.

At each evaluated M1 close, append review versions for still-open assessment/
horizon pairs. A pending version is explicitly unresolved. It can record a
boundary observation while the horizon remains incomplete; it cannot call that
a resolved outcome. The first evaluated close at or after due time produces
the final version, then freezes that horizon's review. New observations never
rewrite existing assessment, observation, revision or review records.

A missing M1 timestamp does not create a fabricated journal assessment. The
first later available evaluated close can finalize an elapsed horizon, using
only observations whose closed times fall within it. Observations after the due
time are excluded even if review publication occurs later. Session closures
can prevent continuous elapsed-minute coverage: the policy returns unresolved
rather than filling prices or assuming elapsed minutes are trading minutes.

A later backfill is first seen when it actually enters the journal, not at its
claimed historical bar close. Completed reviews are not repaired retrospectively;
pending reviews identify late observations and remain unresolved. Corrections
to already observed prices require a new dataset/journal, never an in-place edit.

## Summaries and denominators

Summaries count original assessments and material transitions separately from
review record versions. Only the **latest version per assessment/horizon pair**
contributes to review totals. In-progress records do not count as multiple cases.

Each horizon has explicit all-assessment, unique-leader, tied-leader and no-leader
denominators; original READY/UNKNOWN/BLOCKED counts; elapsed-complete/incomplete
horizon counts; and supported/contradicted/unresolved totals. Elapsed-complete
means due time has passed, not that coverage/quality passed. Unresolved cases
remain in the denominator. Each scenario has all-assessment outcomes and
original-leader membership outcomes, including tied memberships. Summed leader
memberships can exceed the number of assessments because ties have multiple
members. Horizons are reported separately, not pooled into an accuracy rate.

## Actual synthetic audit and worked examples

The [checked-in audit](research_audits/market-reasoning-journal-synthetic-v1.json)
uses seven labeled synthetic OHLC cases, default 5/15-minute reviews and the
inherited small-window analytical test configurations. No historical prices or
full private journal files are published. The timeframe fixtures are software
observations, not independent same-feed historical validation.

| Worked original assessment | Subsequent observations | Five-minute review |
| --- | --- | --- |
| Persistent bullish TREND_UP, unique bullish leader | An upper-envelope breach on a later closed M1 candle | SUPPORTED |
| Bullish TREND_UP, unique bullish leader | Fresh opposing M1 CHoCH changes regime to TRANSITION and scenario ranking; first envelope breach is lower | CONTRADICTED; original bullish report stays frozen |
| Bullish/bearish scenario tie | Later upper breach supports bullish member and contradicts bearish member | Assessment UNRESOLVED; no tie winner |
| Initially assessed trend, then a missing M1/blocked interval | Review coverage cannot be established | UNRESOLVED |
| Valid assessment with only two later minutes | Five-minute horizon has not elapsed | UNRESOLVED |
| Initial bullish assessment, later candle spans both bounds | OHLC cannot establish decisive event order | UNRESOLVED |
| Original range with unique neutral leader | Envelope remains intact | SUPPORTED under the stated envelope criterion |

Across these independent cases: **199 assessments**, 192 chronological
transitions and **39 material changes**. Original states include 138 READY,
42 UNKNOWN and 19 BLOCKED. The journal contains 3,425 append-only review
versions, but only **398 latest assessment/horizon pairs** contribute to totals.

| Horizon | All-assessment denominator | Supported | Contradicted | Unresolved | Elapsed complete / incomplete |
| --- | ---: | ---: | ---: | ---: | --- |
| 5 minutes | 199 | 77 | 5 | 117 | 164 / 35 |
| 15 minutes | 199 | 27 | 0 | 172 | 95 / 104 |

Each horizon includes 119 unique-leader cases, 19 tied-leader cases and 61
no-leader cases. These are observation-review counts, not prediction accuracy
or trading performance. Per-scenario denominators, change categories and exact
hashes are in the audit. Repeated full journals matched in all seven cases;
truncated prefixes, bounded replay and projections at the same cutoff matched.
Tests additionally append new future candles and require every older record
and original assessment to remain byte-equivalent under canonical JSON.

## Offline use, validation and privacy

```python
from iat.intelligence.reasoning_journal import (
    replay_reasoning_journal, journal_prefix,
    validate_reasoning_journal, write_reasoning_journal,
)

journal = replay_reasoning_journal(
    'XAUUSD', m1_rows, m5_rows,
    provenance='SYNTHETIC_RESEARCH',  # explicitly synthetic inputs only
)
validate_reasoning_journal(journal)
write_reasoning_journal(private_new_output_path, journal)
```

The lower-level MarketReasoningJournal consumes validated adaptive reports for
incremental use. `journal_prefix` projects records available by a UTC cutoff.
The validator rebuilds the journal from frozen adaptive reports and rejects
changed originals, invented reviews/observations, unsafe flags, inconsistent
summaries or unsupported policy versions. Checksums are not authentication of
the underlying feed or evidence of complete market capture.

The writer validates first, reserves a new private path and publishes atomically.
It refuses overwrites; failure leaves an explicit INCOMPLETE placeholder rather
than misleading success. Full journals contain OHLC and should stay outside
GitHub or under the existing ignored private-data/evidence directories.

All prior strategy rules, heuristic scores, confluence settings, adaptive policy,
DecisionLog v1, Strategy Replay Log v1 and manifest accounting remain fixed.
Research provenance alone never qualifies a historical dataset; the existing
manifest/source/calendar/finality gates remain necessary. No qualified export
was used here: historical validation stays PENDING, historical comparisons
NOT_RUN, Exness BLOCKED, signal WAIT and execution_allowed=false. There is no
broker, credential, network, order or automatic learning/tuning path.

The full-prefix reference implementation stores full frozen adaptive reports and
many review versions. Large histories have substantial time, memory and private
file-size costs. Causal pruning/compaction and empirical source-qualified review
are later milestones; neither can change frozen reasoning or hide unresolved cases.

## Local verification

The full suite passed on Python 3.11.9 (638 tests, 85.890 seconds) and
Python 3.12.14 (638 tests, 60.016 seconds): 613 inherited tests plus 25 new
journal tests. Coverage includes frozen originals/configuration, revisions,
strict/ambiguous event order, ties, blocked and incomplete windows, late data,
transactional rejection, explicit denominators, repeatability, common-cutoff
prefix/future invariance, compatibility and atomic publication failures.
Final Linux/Windows CI results are linked from the draft PR. No actual broker,
terminal, credentials or qualified historical export was used.
