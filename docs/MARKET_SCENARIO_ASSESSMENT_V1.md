# Market Scenario Assessment v1

A deterministic read-only presentation of existing `ContextReport` observations, hypotheses and confluence. Exness remains BLOCKED, qualification DATA_NOT_QUALIFIED, historical validation PENDING, historical comparisons NOT_RUN, mode READ_ONLY_SHADOW, signal WAIT and execution_allowed=false in every result.

## Architecture and compatibility

Base: PR #25, `d628805785fc9399165d94436d1972569863e01c`. The requested branch `feat/iat2-market-decision-intelligence-v1` was absent locally/remotely and was created from that verified clean base. Existing context/model, confluence, hypothesis, canonical evidence, DecisionLog, adaptive, research API and replay code/tests were inspected before implementation.

The additive `iat.intelligence.scenario_assessment` module consumes a typed ContextReport or its exact `to_dict()` schema. Existing ContextReport/DecisionLog fields, model versions, hypothesis definitions, weights, thresholds, API registration/responses, session profiles, data qualification and execution gates are unchanged. Existing logs remain consumable byte-for-byte; regression tests check DecisionLog hashes before/after assessment. This milestone supplies a Python research interface. Existing HTTP transport envelopes include extra request/session metadata and are separate from the exact ContextReport schema accepted here.

The layer uses existing canonical identity functions and the existing confluence/hypothesis builders to **check consistency**. It returns the supplied scores and selection after validation. It does not replace a rejected selection with its own direction. No trading, terminal, provider, order or network dependency is introduced. No new HTTP endpoint is needed for this integration.

## Research interface

```python
from iat.intelligence.scenario_assessment import (
    assess_scenarios, validate_scenario_assessment,
)

# supplied_context comes from the existing upstream context/quality workflow.
assessment = assess_scenarios(supplied_context)
validate_scenario_assessment(assessment)
assert assessment['signal'] == 'WAIT'
assert assessment['execution_allowed'] is False
```

The assessor accepts SYNTHETIC_RESEARCH, HISTORICAL_RESEARCH and VALIDATED_LIVE context provenance as declarations about the supplied ContextReport. A provenance label is not independent source qualification or proof of broker connectivity. Continue using existing manifest/preflight/qualification gates before any real-data workflow. The assessor never loads a dataset, contacts a broker or authorizes replay, chart review or trading.

`scenario_at(symbol, m1, m5, cutoff, **existing_context_options)` and `replay_scenarios(...)` are **synthetic-fixture helpers** using the existing closed-prefix and causal replay functions. Their raw-OHLC path rejects other provenance with UPSTREAM_GATED_CONTEXT_REQUIRED. Feed approved upstream ContextReport values into `assess_scenarios` for other integration; do not relabel real exports as synthetic. These helpers introduce no historical-manifest bypass or new scoring parameters.

## Report v1

- `scenario_assessment_version=1`, model IAT_MARKET_SCENARIO_ASSESSMENT_V1, original symbol/UTC analysis timestamp/provenance and context/intelligence configuration hashes.
- `market_regime` is the existing `context.classification`, such as BULLISH_ALIGNMENT or SIDEWAYS_OR_RANGING. `m1_m5_alignment` retains Phase 7 alignment, per-frame structures, completed-data timestamps and context limitations. No new regime taxonomy is inferred.
- `ranked_hypotheses` preserves all six existing hypotheses, their heuristic scores, supporting/contradictory evidence IDs, assumptions, invalidation conditions, relevant zone IDs, timeframe context and limitations. Display rank is dense descending score, with alphabetical type order for stable display. Equal scores share a rank and remain ties.
- `selected_hypothesis` retains the original `confluence.selected_hypothesis`. `selected_by_context` identifies that existing choice; `selection_source` explicitly says it is not authorization. Ranking never chooses a new hypothesis. A high-ranked hypothesis can retain an unmet structural precondition; its existing limitation remains visible. NO_CLEAR_DIRECTIONAL_HYPOTHESIS remains an existing analytical outcome, including its score.
- `evidence_index` forwards canonical evidence/event identities, category, direction, timeframe, observation/availability times and references. It contains no raw OHLC arrays or newly invented market/order prices. Fresh opposing M1 CHoCH references remain visible even when Phase 7 alignment remains bullish/bearish.
- Upstream abstention reasons, non-DATA_VALID diagnostic codes, explanations and limitations remain available. Additional explanations identify display semantics and validation limits.

Scores retain **HEURISTIC_EVIDENCE_NOT_PROBABILITY**. Their magnitude can exceed one. They are not calibrated probabilities, predictions, numerical confidence, trading signals or profitability evidence. Entry, stop-loss and take-profit fields are absent.

## Fail-closed and causal rules

| Status | Meaning |
| --- | --- |
| ASSESSED | Input is internally consistent and upstream retains a selected hypothesis without abstention. All trading/qualification permissions remain disabled. |
| ABSTAINED | Valid input with upstream abstention or NO_CLEAR_DIRECTIONAL_HYPOTHESIS. Competing existing hypotheses remain research views. |
| BLOCKED | Unavailable, malformed, unsupported, inconsistent, future-dated or quality-blocked context. Ranked hypotheses and evidence index are withheld. |

`as_of` is optional; omission evaluates the original report's own timestamp. When supplied, it must exactly equal that timestamp. An earlier cutoff rejects future reports; a later cutoff requires a fresh upstream report rather than reusing old quality assertions. There is no implicit wall clock or invented freshness threshold.

Checks include exact model/configuration contracts and hashes; finite JSON; safe mode/signal/flags; upstream diagnostic consistency; complete source references and acyclic same-frame chronology; closed/aligned source candles; canonical candle/pivot/evidence/event identity; frame coverage and context/measurement/zone consistency; original alignment and limitations; inherited capped scores, hypotheses and selection. Future observations anywhere in structured timestamps are rejected. This establishes contract consistency, not independently validated market prices, sessions, finality or source authenticity.

Identical duplicate evidence/weighted records and repeated hypothesis references are collapsed before comparison and hashing. Conflicting records or distinct revisions of one CHoCH occurrence in one snapshot are blocked. Across snapshots, evidence revisions retain upstream canonical IDs and their stable event ID; no window-relative IDs are substituted. Scores remain current-snapshot capped scores and never accumulate ledger counts.

Legacy CHoCH evidence hashes may include a repeated broken-pivot reference before `derive()` stores unique references. Validation reconstructs that existing reference multiplicity from the source graph. It preserves the original evidence/event IDs and existing logs instead of rewriting the identity convention.

Known source selection can remain recorded on an invalid/inconsistent input as provenance; BLOCKED always has empty ranks/evidence and execution false. It cannot be treated as a new directional authorization. Failure explanations use fixed reason codes and omit raw exception text.

## Determinism and limits

`sha256` is the existing IAT canonical payload digest: JSON sorted keys, compact separators, default ASCII escaping, allow_nan=false, UTF-8, excluding root sha256. `context_report_sha256` binds the normalized context snapshot, not original file bytes. Evidence/hypothesis and weighted-evidence ordering, identical duplicates and set-like hypothesis reference lists are normalized; other source metadata is retained. No runtime timestamp, filesystem state, output path or random ID is injected. Typed/serialized inputs and repeated equivalent snapshots produce identical reports/hashes. Real context revisions can change the snapshot digest while stable event identity remains unchanged.

Limits: input JSON <=8 MiB, <=10,000 evidence records, <=20,000 source nodes, bounded reasons/explanations, chronology tree depth <=64 and source reference depth <=32. Oversized, cyclic or unsupported input fails closed; nothing is truncated into success. `validate_scenario_assessment` checks the output version/hash, safety flags, causal evidence references and deterministic ranks, and grants no approval.

## Executed synthetic audit and testing

[Published synthetic audit](research_audits/scenario-assessment-synthetic-v1/audit.json) uses labeled inherited synthetic OHLC fixtures. Twelve cases yield **2 ASSESSED, 8 ABSTAINED, 2 BLOCKED**. Every selected hypothesis equals upstream selection. The range and normal trend cases are assessed; high-volatility trends, opposing CHoCH, sweep conflicts, a tie and insufficient structure abstain; gap and direct unfinished-M5 inputs block. These are analytical pipeline outcomes, not real-market or profitability validation.

Focused tests cover duplicate/event-revision integrity, forged scores/selection, assumptions and invalidations, invalid/future inputs, closed M5 availability, deterministic hashes/order, published audit regeneration, source immutability, no network/MT5 dependency, existing DecisionLog compatibility, full/prefix equivalence, rolling windows and future-append invariance. CI runs the full inherited/new suite on Linux/Windows Python 3.11/3.12 and an offline synthetic fail-closed smoke test. Actual final counts/results are recorded in the PR.

```powershell
py -3.11 -m unittest discover -s tests -p test_scenario_assessment.py -v
py -3.11 -m unittest discover -s tests -v
```

Historical validation is still PENDING, comparisons NOT_RUN and Exness BLOCKED. No real broker data, credentials, live trades, performance claims or independent source approval are part of this milestone.
