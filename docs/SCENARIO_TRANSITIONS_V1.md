# Scenario Transition & Invalidation Tracking v1

Research-only, pairwise descriptions of PR #26 scenario assessments. No endpoint,
execution integration, new strategy, threshold, ranking or source-qualification
rule is introduced. Inputs and output timestamps are UTC. Synthetic results do
not establish market reliability, source eligibility or profitability.

## Interface and serialization

```python
from iat.intelligence.scenario_transitions import (
    assess_scenario_transition, validate_scenario_transition,
    replay_scenario_transitions,
)
report = assess_scenario_transition(previous_assessment, current_assessment)
validate_scenario_transition(report)  # True, or raises ValueError on invalid reports
```

The inputs are validated serialized Scenario Assessment v1 dictionaries, not raw
candles or caller-selected hypotheses. The function copies inputs and has no
wall-clock, random, network or broker dependency. Unavailable/malformed input
produces a fail-closed report. The validator raises on invalid serialized reports;
callers must not treat a validation exception as a usable transition.

The JSON report contains `transition_version=1`, model and policy versions,
assessment SHA-256 references, UTC observation timestamps, scenario identifiers,
classification, comparability, source evidence references, heuristic support
comparison, explicit invalidation proof, reason codes, explanations, limitations,
immutable input witnesses, `transition_id`, and `sha256`.

The existing canonical `strategy_replay.digest` utility hashes JSON. A scenario
identity hashes instrument, existing selected hypothesis and compatible assessment
model/schema, hypothesis model/configuration version, configuration hashes,
provenance and M1/M5 scope. It deliberately excludes timestamp, score and evidence
revisions. This identifies a research scenario, not a uniquely armed strategy setup.
Transition identity hashes policy version and the two ordered input content digests
and validity states. Missing input has an explicit marker. The report checksum
excludes only itself. Object key insertion order is immaterial; canonical evidence
list ordering is required rather than silently repaired.

The serialized report embeds complete validated input witnesses. Validation
revalidates their contracts and input digests, re-derives the entire transition,
and requires exact schema, semantics and canonical checksum equality. Recomputing
a checksum after changing a state, proof, score, ID or explanation does not make
that change valid. Invalid input witnesses retain only a digest where serializable,
not the untrusted payload. Content hashes establish consistency, not authenticity:
a wholly fabricated but internally consistent source is not authenticated here.

## Eligibility and chronology

Comparisons require the same instrument, provenance, schema/model/scoring method,
configuration hashes, M1/M5 structure scope and known completed frames. Each frame
must have exactly one matching STRUCTURE evidence record; evidence must be
canonical, uniquely ordered, frame-consistent and available by the completed
frame cutoff. Hypothesis generation time and timeframe context must match their
assessment. Selected structural prerequisites and upstream history/measurement
limitations must permit comparison.

V1 intentionally compares **adjacent completed M1 observations**, exactly 60
seconds apart. Each assessment time must equal its M1 close. This is a causal
observation cadence, not a score threshold. M5 close may stay fixed or advance
exactly 300 seconds. Unfinished M5 candles cannot contribute. Duplicate or reversed
observations and reversed M5 snapshots are BLOCKED; an observation gap or unknown
scope is ABSTAINED. Inputs are never sorted to manufacture chronology. A changed
STRUCTURE identity whose confirmation was already available at the prior cutoff
is treated as an unestablished revision, not new evidence.

PR #26 does not expose raw history extent, dated calendar/finality proof or a
fully dereferenceable source graph. V1 compares the declared completed-frame
scope and compatible configuration only; it does not assert equal rolling-window
length, independently verify pivots from raw OHLC, certify broker sessions or
qualify historical data. The report carries this limitation explicitly.

## States and precedence

| State | Deterministic meaning |
| --- | --- |
| BLOCKED | Current input unavailable/invalid, previous input invalid, upstream quality-blocked report, or noncausal chronology. |
| ABSTAINED | No prior observation, insufficient evidence, incompatible scope/model/configuration, missing observation, upstream abstention, or uninterpretable support change. |
| NEW | A comparable observed upstream abstention with NO_CLEAR_DIRECTIONAL_HYPOTHESIS is followed by an eligible upstream-selected scenario. |
| INVALIDATED | Newly available confirmed opposing M5 structure proves the prior scenario's recorded invalidation condition, as described below. |
| REPLACED | A comparable current upstream-selected scenario differs, without established invalidation proof. |
| PERSISTING | Same upstream-selected scenario and equal heuristic score; this does not claim identical underlying evidence. |
| STRENGTHENING | Same selection, fixed structural/zone anchors, strictly increased score and strict support-bucket superset, without increased opposition. |
| WEAKENING | Same selection, fixed structural/zone anchors, strictly decreased score and strict support-bucket subset, without decreased opposition. |

Safety/eligibility and chronology checks precede all positive states. Explicit
invalidation precedes replacement/current abstention. A missing previous
observation never proves NEW; replay after a missing observation re-establishes
continuity through abstention. ABSTAINED and BLOCKED do not terminate or invalidate
an underlying strategy setup; this module does not own strategy lifecycles.

Support comparisons reuse the original unmodified heuristic scores and existing
`confluence.CATEGORY_BUCKETS`, keyed by timeframe, category bucket and direction.
Repeated evidence does not create new buckets. Structural identities on both
frames and relevant zone IDs must remain fixed for score-change interpretation.
Strict comparisons introduce no new score thresholds. Mixed changes abstain.
Scores are **heuristic evidence**, not probabilities, confidence percentages,
forecasts, win rates or expected returns. Ties and the original selected hypothesis
remain unchanged in the input witnesses; the module never selects a hypothesis.

## Traceable invalidation

Only the existing condition **“New confirmed structure contradicts this scenario.”**
is supported. The condition must be recorded on the previous selected hypothesis.
The previous M5 structure must support it; a different, newly confirmed M5
structure must oppose it and appear among the current contradictory evidence for
that same prior hypothesis. Confirmation must occur strictly after the previous
observation and no later than the current observation. The new evidence must
reference at least four canonical confirmed M5 pivot identities and carry the
matching upstream structure reason code. The proof records condition, prior and
current structure IDs, confirmation time and source pivot references.

Bullish requires bearish M5 structure, bearish requires bullish M5 structure;
a range can be contradicted by directional M5 structure. M1 CHoCH alone, a lower
score, another leader, upstream abstention, missing evidence or a blocked input
cannot prove this condition. Zone breaches, session expiry, prose conditions
without traceable proof and hypothetical execution-level invalidations remain
unsupported. These cases abstain or are described as replacement/weakening where
those separate rules apply. No entry/stop/target or trading permission is emitted.

## Reproducible synthetic audit

```bash
python -m unittest discover -s tests -p test_scenario_transitions.py -v
python -m unittest discover -s tests -v
```

`tests/test_scenario_transitions.py` generates positive inputs through the existing
causal `scenario_at` pipeline from explicitly synthetic OHLC, using inherited
fixture configurations and unchanged strategy/confluence settings. Adversarial
copies are clearly distinguished from positive evidence. The checked-in audit is
`docs/research_audits/scenario-transitions-synthetic-v1/audit.json`; its golden
regression recomputes event IDs, reason codes, checksums and invalidation proofs.
To inspect it, open that JSON locally. To regenerate for review:

```bash
PYTHONPATH=tests python -c "import json; from test_scenario_transitions import audit; print(json.dumps(audit(), sort_keys=True, indent=2))"
```

Worked examples (independent synthetic sequences, not real XAUUSD):

* `new`: observed high-volatility abstention → eligible bullish selection NEW →
  same selected scenario with equal support PERSISTING.
* `support`: selected bullish score 4.0 → 5.5 STRENGTHENING as M1 candle/momentum
  support buckets appear → 4.0 WEAKENING as those buckets disappear. No invalidation.
* `replace`: 08:29 UTC bullish → 08:30 UTC ranging selection REPLACED. A changed
  selection is not, by itself, invalidation evidence.
* `invalidate`: 08:29 UTC bullish → 08:30 UTC newly confirmed bearish M5 structure
  INVALIDATED, with four or more canonical M5 pivot references in the audit.
* Missing observation, duplicate timestamp, reversed order and quality-blocked
  input are included as separate negative sequences.

Across 20 pairwise audit records: ABSTAINED 9, BLOCKED 5, and one each NEW,
PERSISTING, STRENGTHENING, WEAKENING, REPLACED and INVALIDATED. Initial missing
previous observations are included in the abstention denominator. These are
snapshot counts, not strategy setups or historical metrics. Repeat runs and every
input prefix produce identical overlapping records. Separate regressions verify
future OHLC and unfinished M5 cannot alter an earlier assessment/transition.
All eight states are exercised; only the narrow structural invalidation above is
supported.

## Safety and compatibility

Every output retains READ_ONLY_SHADOW, WAIT, execution_allowed=false,
broker_access=false, orders_requested=0, profitability_tested=false, Exness
BLOCKED, DATA_NOT_QUALIFIED, historical validation PENDING and comparisons NOT_RUN.
Synthetic replay rejects historical provenance; it is not a historical gate or
qualification bypass. No real data was qualified or replayed for this milestone.
Existing ContextReport, Scenario Assessment v1, DecisionLog v1, Strategy Replay
Log v1, calendars, research APIs, ranking/scoring and execution gates are unchanged.
The feature is additive and imports no trading adapters. A caller must continue
to use the existing manifest/preflight gates for historical datasets.
