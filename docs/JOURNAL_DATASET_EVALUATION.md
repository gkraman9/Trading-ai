# Manifest-gated Market Reasoning Journal evaluation v1

This adapter connects the unchanged Market Reasoning Journal v1 to the offline
XAUUSD manifest loader and shared historical preflight. It is reasoning review
under the journal's **first-breach criteria**, not trading, return measurement,
forecast calibration, broker validation, or evidence of profitability.

## Eligibility and unchanged rules

`iat.journal_dataset_replay.run_journal_manifest` accepts a manifest, typed existing
context/intelligence configurations, and optional assessment/observation bounds.
It does not accept a caller-provided provenance label or review policy override.
The existing adaptive rankings, strategy predicates, confluence thresholds, and
5/15-minute review criteria remain unchanged. Source provenance comes from the
loaded manifest. All outputs retain Exness BLOCKED, signal WAIT, and
execution_allowed=false; no broker access occurs.

Before creating a journal, reuse the manifest's source, file checksums, calendar,
closed-bar/finality, full-frame quality, and overlapping M1/M5 OHLC checks.
Independent historical inputs must also satisfy the existing source/evidence
attestations and selected evaluation-window coverage threshold. Observation-tail
bars cannot satisfy coverage for an earlier selected evaluation window. An
operator declaration is not independently authenticated by the program.
Synthetic fixtures remain explicitly synthetic and cannot establish historical
validation. Derived M5 consistency is INTERNAL_AGGREGATION_ONLY, not independent
cross-feed corroboration. Raw data and full real-data journals stay private.

## Time scopes and state

Manifest v2 declares warm-up and evaluation. V1 has no inferred warm-up. To retain
an observation tail without changing the manifest contract, optionally select an
earlier evaluation end on a five-minute UTC boundary. Evaluation starts at the
manifest's declared start; it cannot extend beyond the declared end.

A single chronological journal runs through warm-up, evaluation and the tail.
Warm-up assessment closes are `close <= evaluation.start`; evaluation closes are
`start < close <= selected end`; later closes are observation-tail assessments.
The report separates all three cohorts and exposes the journal prefix hash,
last warm-up assessment and pending warm-up review pairs at evaluation start.
Pending reviews continue; they are not restarted or counted as evaluation origins.
Material changes belong to the cohort containing the new original assessment.

`requested_outcome_observation_cutoff_utc` is bounded by the manifest and must be
minute-aligned and no earlier than the selected evaluation end.
`outcome_observation_cutoff_utc` is the actual last evaluated M1 close, not an
invented clock tick. By default both scopes end at the manifest end. No future
observations beyond the cutoff enter the causal replay. An input ending before a
review is due leaves HORIZON_INCOMPLETE. Later observations can complete reviews;
original assessments, evidence IDs and configuration hashes remain frozen.

The full archive is preflighted before replay. A later defect can reject an
archive even when its earlier prefix was valid; prefix equivalence concerns
eligible inputs, not bypassing source/quality checks.

## Counts and denominators

For each cohort and horizon, count only the latest available review per original
assessment/horizon pair. Report total results and strata by **original** regime
(TREND_UP/DOWN, RANGE, TRANSITION, UNKNOWN) and original leader status
(UNIQUE/TIED/NONE). Later regime changes do not recategorize the original.

Each group reports:

- All-assessment denominator and SUPPORTED/CONTRADICTED/UNRESOLVED counts.
- Resolved-review denominator, equal to supported plus contradicted.
- Incomplete and elapsed-complete horizon counts; elapsed completion does not
  imply sufficient quality or resolution.
- Unresolved reasons, which are multi-label and need not sum to the unresolved count.
- READY/UNKNOWN/BLOCKED and leader-status denominators.
- Per-scenario results for every original and separately for original leader
  memberships. A tie has multiple memberships; their sum can exceed the number
  of assessments. The tied assessment stays unresolved, without selecting a
  retrospective winner.

The unchanged criteria use the first strict envelope breach, with OHLC both-side
ambiguity unresolved. Original UNKNOWN/BLOCKED states, missing/late/blocked
observations, and unfinished horizons remain visible rather than becoming losses
or zero-valued historical metrics. A preflight-rejected dataset produces no
journal, accounting or historical metrics.

## Private invocation

From the repository root using an existing supported Python environment:

```powershell
python diagnostics/journal_dataset_replay.py `
  --manifest 'E:\IAT2\private-data\manifest.json' `
  --report-path 'E:\IAT2\private-evidence\journal-dataset-run-001.json' `
  --evaluation-end-utc '2026-11-12T08:25:00Z' `
  --observation-cutoff-utc '2026-11-12T08:45:00Z'
```

The dates above illustrate scope syntax only; replace them with the reviewed
manifest's actual interval. Omit the two bounds to use declared defaults.
Existing optional `--context-config` and `--intelligence-config` files use the
strict existing schemas. Do not tune thresholds in response to these outcomes.
The command uses no terminal credentials. Reports may contain full OHLC and must
remain in a private directory outside Git. Parent directories must already exist.
It refuses overwrite, reserves an explicit FAIL/RUN_INCOMPLETE report before
work, atomically publishes the validated result, and prints only status fields.
Exit codes: PASS 0, WARN 2, BLOCKED 3, FAIL 1. WARN can be expected for synthetic
inputs or unresolved eligible reviews; it does not certify historical data.

## Reproducibility evidence and limits

The committed synthetic audit records manifest/configuration/journal hashes,
cohort counts and horizon/regime/leader breakdowns. Full/full comparison requires
identical complete reports. For a real truncated prefix, compare journal records
and cohort accounting at a common cutoff, not whole wrappers: truncated files,
manifest hashes and declared ends legitimately differ. A prefix projection of the
full journal must also agree.

No qualified historical export is supplied for this milestone. The available
private pilot is rechecked only through preflight; source review/finality/calendar
requirements remain outstanding. Historical validation is PENDING, historical
comparisons are NOT_RUN, and historical metrics are unmeasured (`null`). No
full real-data journal is published. A permitted export must first provide the
source/feed, usage, timestamp/price basis, dated session and exception coverage,
and finality evidence required by the existing qualification workflow.

## Actual synthetic evaluation

[Committed audit](research_audits/journal-dataset-evaluation-synthetic-v1.json)
contains all strata, denominators and hashes. These deliberately constructed OHLC
fixtures are not market observations. Main evaluation is 2026-11-12
08:20–08:25 UTC (five assessment closes), with 20 warm-up and 20 tail closes;
observations stop at 08:45. The incomplete case evaluates through 08:30 with no
tail (ten evaluation closes). Counts below are supported / contradicted /
unresolved under the unchanged first-breach criteria.

| Synthetic case | Evaluation assessments | 5-minute outcomes | 15-minute outcomes |
| --- | ---: | --- | --- |
| Persistent trend | 5 | 5 / 0 / 0 | 5 / 0 / 0 |
| Regime change | 5 | 1 / 2 / 2 | 1 / 2 / 2 |
| Tie present | 5 | 4 / 0 / 1 | 4 / 0 / 1 |
| Incomplete horizon | 10 | 5 / 0 / 5 | 0 / 0 / 10 |
| Coverage gap | Unmeasured: preflight BLOCKED | NOT_RUN | NOT_RUN |

For the regime-change example, the 08:21 original is TREND_UP with a unique
BULLISH leader. At 08:23, newly confirmed opposing M1 CHoCH changes the new
assessment to TRANSITION with a BEARISH leader. The original remains frozen;
its separate completed 5- and 15-minute reviews are CONTRADICTED by the first
lower-envelope breach. The five evaluation originals include one tie and one
NO_DIRECTIONAL_BREACH case; neither is converted to a resolved outcome.

The tie fixture contains one tied original. Its root review remains unresolved
at both horizons while the individual scenario memberships stay visible.
All ten 15-minute reviews in the incomplete fixture remain HORIZON_INCOMPLETE.
Every journal-producing case passed identical-input full/full comparison and
eligible truncated-prefix/common-cutoff journal and cohort comparisons. The gap
case produced no journal, so its prefix comparison is NOT_RUN.

The private pilot preflight remains BLOCKED with
CANDLE_FINALITY_UNCERTAIN, EVIDENCE_CALENDAR_PENDING,
EVIDENCE_FINALITY_PENDING, INDEPENDENT_REVIEW_PENDING, and
SESSION_CALENDAR_REQUIRED. No historical journal or comparison was produced.
