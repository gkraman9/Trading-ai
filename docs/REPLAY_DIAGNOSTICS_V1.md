# Historical Replay Diagnostics & Evidence Coverage v1

Observability only: explain existing PR #28 replay outputs without changing
intelligence, scenario selection/scoring, transitions, source qualification or
execution. No optimization, profitability measure or trading recommendation.
All timestamps below are UTC market observation timestamps.

## Architecture and limitations found during inspection

PR #28 records four stage hashes plus normalized-context and DecisionLog-entry
references. Its validator regenerates the complete replay from private embedded
files. DecisionLog v1 retains causal context evidence, frame cutoffs, structure,
limitations and abstention reasons; flattened replay reason codes can lose their
original timeframe attribution. In particular, HISTORY_INCOMPLETE alone cannot
identify M1 or M5, even when raw candle counts suggest a likely frame.

Quality-blocked assessments still have valid stage report hashes but omit the
normalized-context reference. Thus valid stage references do not necessarily form
a complete evidence chain, nor do they prove analytical sufficiency. Missing
normalized context is counted as unavailable, not corrupted. Quarantined context
frames do not prove that raw M1/M5 history was absent.

Neither a checksum nor an upstream ASSESSED status establishes independent source
authenticity. The existing transition contract lacks zone/session-expiry
invalidation proof. These unsupported categories remain visible; their absence
is not manufactured as observed zero coverage. No additional intelligence or
market-data measurement is introduced.

## Interface and validation

```python
from iat.replay_diagnostics import (
    generate_replay_diagnostics, validate_replay_diagnostics, diagnostics_text,
)
diagnostics = generate_replay_diagnostics(replay)
validate_replay_diagnostics(diagnostics, replay)  # True, or raises on invalid input
text = diagnostics_text(diagnostics)
```

The architecture-consistent module is `iat/replay_diagnostics.py`, adjacent to
`iat/scenario_replay.py`. Generation first calls the unchanged upstream
`validate_scenario_replay`; the subsequent projection is pure and deterministic.
The inherited validator uses isolated temporary copies of embedded source files
and replays existing logic. This validation cost and temporary-file behavior are
inherited, not new market analysis, broker access or changes to original files.
The projection performs no I/O and does not mutate its input or upstream decisions.

`validate_replay_diagnostics` requires the source replay explicitly; a diagnostic
checksum alone is insufficient. It reuses upstream validation, recomputes the
projection and demands exact schema, contents and canonical checksum equality.
Modified coverage, classifications, attribution, source binding or safety flags
fail even with recomputed diagnostic checksums. Invalid source references,
duplicate IDs, chronology and semantic changes are rejected by the unchanged
source validator, rather than counted as valid zero-coverage input.

`config/replay-diagnostics-v1.schema.json` is the self-contained structural JSON
Schema (2020-12). It reuses PR #28's existing alignment shape. Structural schema
validation complements, and cannot replace, semantic validation against the source.
The deterministic diagnostic ID hashes version, policy/mapping hash and source
replay checksum. The report checksum excludes only itself. Mapping/explanation
policy is also hashed. Original code/evidence order is preserved or canonically
sorted; no wall clock, randomness or external API participates.

## Meanings and denominators

The diagnostic preserves separate snapshot statuses (ASSESSED/ABSTAINED/BLOCKED)
and the eight existing transition classifications. An eligible snapshot can have
an abstained transition because a previous observation is missing. Reason counts
are per observation per code, and can overlap; sums need not equal denominators.

| Measurement | Definition | Denominator |
| --- | --- | --- |
| Stage reference available | Recorded stage hash is present. | All replay observations, including warm-up. |
| Stage reference integrity valid | Its source replay regenerated successfully. | All replay observations. |
| Complete required chain | Four stage references, normalized-context and DecisionLog references are present and validated. | All replay observations. |
| Context evidence available | At least one retained canonical context evidence ID. | All replay observations. |
| Causal frame alignment | Both context frames survived quality gating; their cutoffs match available closed prefixes, M1 equals observation, M5 is aligned and not future. | All replay observations. |
| Confirmed structure | Retained STRUCTURE evidence and a non-UNKNOWN upstream structure classification. | All replay observations, separately M1/M5. |
| Upstream research eligible | Original snapshot status is ASSESSED. No new sufficiency rules. | All replay observations. |
| Blocked without context evidence | BLOCKED snapshot with zero retained context IDs; an association, not inferred causality. | All replay observations. |
| Independently qualified | Not established by this evidence contract; numerator/percent are null. | All replay observations; unsupported status remains explicit. |
| Invalid chains in accepted input | Zero because invalid replay inputs are rejected as a whole. This does not count rejected inputs. | Observations in accepted, validated replays only. |

Available, integrity-valid, analytically sufficient and independently qualified
are distinct concepts. Per-category tables measure presence/integrity for the
existing eight evidence categories; category-specific sufficiency stays unknown
rather than inventing a criterion. Evidence IDs are preserved without counting
duplicates as additional evidence.

A measured zero with a positive denominator is 0%. A zero observation denominator
has percent=null and status=NO_OBSERVATIONS. Unsupported/unestablished metrics
have numerator=null, percent=null and status=NOT_ESTABLISHED, including on an
empty replay. A blocked admission with no records is not successful coverage.

Snapshot abstention and block reason distributions use DecisionLog abstention
codes filtered by the actual snapshot status. Transition abstention/block
reason distributions use the separate transition codes and their own status
counts as denominators. The all-observation distribution retains the original
merged codes, including noncausal warnings. Admission reasons use one input run,
not zero observations, as their denominator.

## Attribution and temporal behavior

Diagnostic attribution categories are explanation labels, not new upstream reason
codes. Each label retains its supporting original codes and a fixed research-only
recovery action. Unknown/unmapped or empty causes are UNATTRIBUTABLE. For example:

* HISTORY_INCOMPLETE is HISTORY_UNSCOPED; no timeframe is guessed.
* Explicit M1_HISTORY_UNAVAILABLE/M5_HISTORY_UNAVAILABLE retain their frame scope.
* Measurement/structure restrictions and conflicting scenario evidence are grouped
  only when explicit codes support them. Phase WARMUP is not itself a reason for
  an abstention; a snapshot may be research-eligible within declared warm-up.
* Preflight frame diagnostics retain actual frame keys, so a scoped GAP_UNVERIFIED
  can be identified as M1 or M5. Missing calendar/finality/review is a separate
  source qualification restriction, not a scenario weakness.
* CURRENT_UPSTREAM_ABSTENTION says the upstream abstained, but does not establish
  a root cause by itself. Its specific snapshot reasons remain separately visible.

Observation diagnostics include current evidence IDs, category/frame counts,
missing required references, original frame state/cutoffs, evidence additions and
removals relative only to the prior observation, status changes and frame-close
changes. A removed ID is not automatically an expired/invalidated zone.

ABSTAINED/BLOCKED runs are reported separately for snapshots and transitions.
Consecutive means the same status with exactly 60 seconds between observations;
a schedule gap breaks the run rather than assuming unobserved continuity. Changes
between successive observed pairs have denominator n-1, explicitly including any
gaps; contiguous-pair coverage is separate. Warm-up/evaluation boundaries and
entry into original ASSESSED eligibility are separate facts. `warmup_to_eligible`
records an entry from a preceding WARMUP, non-ASSESSED observation; it does not
assert that elapsed warm-up caused eligibility.

Per-observation diagnostic IDs bind policy and the original record ID/checksum,
not the full archive hash. Prefixes with identical causal history retain identical
observation diagnostics. Full-run diagnostic IDs, aggregate counts and run endpoints
can change as the replay grows; these completed-run summaries never feed back
into earlier decisions. PR #28's eligible-extension and fixed-source/configuration
constraints on prefix equivalence are unchanged.

## Private CLI and Windows workflow

Use a saved, valid PR #28 report. No terminal, credentials, network access or new
optional dependency is required beyond the existing project environment.
Full input replay reports embed source CSVs/documents and must remain private.
Diagnostic outputs omit those files, prices, provider/server identities and review
text, but still remain local/private research artifacts. Only explicitly labeled
synthetic audit aggregates are committed in this milestone.

```powershell
py -3.11 diagnostics/replay_diagnostics.py `
  --replay-report 'C:\PrivateIAT\reports\scenario-replay-001.json' `
  --json-output 'C:\PrivateIAT\reports\diagnostics-001.json' `
  --text-output 'C:\PrivateIAT\reports\diagnostics-001.txt'
```

Parent directories must already exist. Both output filenames must be new and
resolve to paths distinct from each other and the input. The existing atomic,
non-overwriting `write_new` is reused. Each file publishes completely or not at
all; the pair is not a filesystem transaction. If text publication fails after
JSON publication, the complete valid JSON remains, the command returns failure,
and no success is printed. Inspect existing artifacts and choose new filenames
for recovery. Input files are never changed or silently uploaded. Console output
contains fixed status/counts only, never complete source bytes or sensitive metadata.
Exit 0 means diagnostics were created, not data qualified; exit 1 means invalid
input/publication failure (argparse also uses 2 for malformed command syntax).

Read JSON locally for coverage, attribution, temporal records and schema hashes;
the text export includes numerator/denominator, explicit unknown metrics and
separate snapshot/transition reason distributions. Do not publish real artifacts.

## Actual synthetic audit

The audit reuses all eight PR #28 30-observation fixture cases plus its missing,
duplicate and reversed schedules, through actual `run_scenario_replay` output.
No classifications, prices, evidence or thresholds are altered by diagnostics.
`docs/research_audits/replay-diagnostics-synthetic-v1/audit.json` records source and
diagnostic hashes, actual per-case counts/temporal summaries and aggregate coverage,
reason frequencies and unattributable categories. Golden tests regenerate it.

Actual observations: **244**. Snapshot distribution: ASSESSED 36, ABSTAINED 192,
BLOCKED 16. Transition distribution remains PR #28's observed ABSTAINED 188,
BLOCKED 24, NEW 12, PERSISTING 15, INVALIDATED 2, REPLACED 1, STRENGTHENING 1,
WEAKENING 1. Duplicate/reversed schedules block admission and add zero observations.

* Four stage integrity references: 244/244 each (100%).
* Complete six-reference chains: 228/244 (93.4426%); 16 lack normalized context.
* Causally aligned context frames: 228/244 (93.4426%). Directional agreement is
  not required for geometric causal alignment.
* Original ASSESSED eligibility: 36/244 (14.7541%). This is not a confidence or
  market-performance percentage.
* Independent qualification: unknown/unestablished, not 100% or an invented zero.

Top snapshot-abstention codes (denominator 192): NO_UNIQUE_ELIGIBLE_SCENARIO 192,
HIGH_VOLATILITY_REQUIRES_FURTHER_RESEARCH 117, CONFLICTING_TIMEFRAME_STRUCTURE 84,
INSUFFICIENT_STRUCTURAL_CONTEXT 48. Blocked snapshot codes (denominator 16):
BLOCKED_DATA_QUALITY 16 and HISTORY_INCOMPLETE 16. Transition-abstention codes
(denominator 188): CURRENT_UPSTREAM_ABSTENTION 138 and
UPSTREAM_HISTORY_OR_STRUCTURE_INSUFFICIENT 48, plus one each OBSERVATION_GAP and
PREVIOUS_OBSERVATION_MISSING. Transition blocks (denominator 24) retain 16 current
and 8 previous blocked-assessment reasons. All counts are descriptive, overlapping
where applicable, and preserve upstream results.

## Verification and safety

```powershell
py -3.11 -m unittest discover -s tests -p test_replay_diagnostics.py -v
$env:PYTHONPATH = 'tests'
py -3.11 -m unittest test_replay_diagnostics test_scenario_replay -v
py -3.11 -m unittest discover -s tests -v
```

Tests cover invalid source checksums/IDs/versions/references/chronology, recomputed
nested IDs/checksums, contradictory states, missing frames, partial boundaries,
unknown attribution, empty schedules, schema strictness, stable serialization,
prefix equivalence, source immutability and private atomic exports. CI runs full
regressions on Ubuntu/Windows and Python 3.11.9/3.12 with a diagnostics safety smoke
check. No upstream tests or validators are weakened.

Source qualification, historical validation and execution status do not change.
Exness remains BLOCKED; READ_ONLY_SHADOW, WAIT, execution_allowed=false,
historical validation PENDING and comparisons NOT_RUN are invariant. Real-data
permission/feed/basis, dated calendar/finality and independent review remain
outstanding without a qualified export. Zone/session invalidation proof and
independent authenticity coverage remain unsupported. No profitability, win-rate,
broker-equivalence or live-execution claim is made.
