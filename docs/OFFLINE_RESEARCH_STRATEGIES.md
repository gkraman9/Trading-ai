# Offline strategy registry v1

These are **original IAT 2.0 rule compositions**, attributed to the IAT research
implementation. Neither is presented as a reproduced third-party strategy or
an established trading method. The familiar labels describe observations;
all precise eligibility, sequencing and invalidation predicates below are
IAT-specific experimental choices. There are no external method quotations,
profitability claims, source-feed certifications or broker validation claims.

`iat.intelligence.strategy_registry.registry()` returns registry version 1,
two rule-version `1.0.0` definitions, their authorship/source, descriptions,
supported M1/M5 timeframes, evidence requirements, eligibility, invalidation,
IAT choices and `EXPERIMENTAL_SYNTHETIC_ONLY` validation status. A canonical
SHA-256 identifies registry content. Unsupported versions and invalid metadata
are rejected; each returned registry is detached from internal definitions.
Changing rules requires a new version and regression review.

## Shared gates and observation vocabulary

`strategies_at(symbol, m1_history, m5_history, as_of, **options)` selects causal
closed prefixes and calls the existing quality-gated `context_at`. It does not
fetch data, use a terminal, create orders or change API/confluence behavior.
Only explicit `SYNTHETIC_RESEARCH` or `HISTORICAL_RESEARCH` provenance is accepted.
The latter is a research input label, not proof of eligibility or validation.
The lower-level `evaluate_strategies(ContextReport)` consumes the existing
observation contract; it is not an alternative raw-data validation path.

Both M1 and M5 must be present and their structures established (bullish,
bearish, ranging or transitional). Insufficient pivots/history or blocked
quality causes ABSTAINS before any qualification or invalidation. The inherited
gates detect stale, gapped, malformed and unclosed input bars. A historical
query excludes unfinished/future bars; a directly supplied context analysis
with unfinished bars is blocked by the existing raw-input gate.

Both strategies require:

- A same-direction existing M1 candlestick interpretation on the latest closed
  M1 candle. The existing context engine decides which pattern is directional;
  this evaluator does not add pattern recognizers or reinterpret dojis.
- Current same-direction SUPPORT_RESISTANCE or SUPPLY_DEMAND evidence from
  M1 or M5, status FRESH, TESTED or ROLE_REVERSAL_CANDIDATE. Existing context
  logic applies zone polarity/role reversal and proximity thresholds. Proximity
  is to that timeframe's last closed price, not an inferred future M1 price.
- Evidence and its source references available by the query timestamp. Current
  evidence is tied to each timeframe's actual closed `data_as_of`, not to wall
  time or the Phase 7 alignment label.

## Exact continuation rules

`M5_TREND_M1_CONFIRMATION` evaluates bullish and bearish separately. A directional
case QUALIFIES if M5 structure and M1 structure both match that direction,
the shared gates/pattern/zone requirements pass, and no fresh opposing M1
CHoCH is present. No additional score or confluence-leader requirement is used.

M5 structure matching the direction anchors the setup. A fresh opposing M1
CHoCH then makes it INVALIDATED, even if the Phase 7 alignment remains bullish
or bearish and even if some confirmation requirements are also missing.
Without an anchor the case abstains instead. Missing M1 confirmation, zone or
pattern produces ABSTAINS unless the anchored invalidation predicate fires.

## Exact sweep reversal rules

`SWEEP_M1_STRUCTURE_CHANGE` also evaluates both directions independently:

1. A bullish case requires an existing M1 CONFIRMED_SWEEP of a SWING_LOWS or
   EQUAL_LOWS pool; a bearish case requires SWING_HIGHS or EQUAL_HIGHS. Mere
   LEVEL_PENETRATION, AMBIGUOUS_EVENT and SUSTAINED_BREAKOUT do not qualify.
2. The pool must have been confirmed before or at the sweep candle opening.
   The sweep must be available within the inclusive five-minute interval
   ending at `as_of`. If multiple sweeps qualify, choose the latest availability,
   with canonical event ID as a deterministic tie-break. No score accumulation.
3. A fresh same-direction M1 CHoCH must be confirmed on the latest closed M1
   bar with existing confirmation policy CLOSE. Its break candle must open at
   or after the sweep's availability. A sweep and CHoCH on the same candle
   cannot establish sequence from OHLC and therefore abstain.
4. The shared current M1 candlestick and active directional zone are required.
   M5 structure must be established but need not agree with the reversal.
   M1's pivot-based structure label need not yet agree with the new CHoCH.

A recent matching sweep anchors this setup. A fresh opposing M1 CHoCH
invalidates it regardless of alignment. Any observed M1 close **after** the
sweep's availability strictly below a bullish swept level or strictly above
a bearish swept level also invalidates it. Equality is not a violation. A
later reclaim does not erase an earlier violation while this sweep remains
the selected anchor. There is no new tolerance threshold for that predicate.
Missing post-sweep confirmation/pattern/zone causes abstention unless an
anchored invalidation predicate fires. Five-minute age and strict-level loss
are explicit IAT choices, not empirically fitted parameters.

## Report semantics

Report version 1 contains four independent directional evaluations, each with
strategy/rule identity, direction, QUALIFIES/ABSTAINS/INVALIDATED status,
reason codes and supporting/contradictory evidence IDs. It records query time,
symbol, provenance, registry hash and inherited analytical configuration hashes.
QUALIFIES means only that the listed research predicates are met. INVALIDATED
is a snapshot description of an anchored setup; there is no persisted position,
order lifecycle, entry/exit price, P&L or strategy ranking. Missing conditions
are retained alongside invalidation reasons. Strategies cannot change one
another's status or affect existing confluence selection.

Every report retains `mode=READ_ONLY_SHADOW`, `signal=WAIT`,
`execution_allowed=false`, `exness=BLOCKED`, `historical_validation=PENDING`
and `historical_decision_log_comparisons=NOT_RUN`. This milestone does not
produce historical DecisionLogs or alter the existing DecisionLog schema.
No eligible historical export is available; source qualification requirements
in [the PR #12 review](SOURCE_QUALIFICATION_REVIEW.md) remain outstanding.

## Offline use

```python
from datetime import datetime
from iat.intelligence.strategy_registry import registry
from iat.intelligence.strategies import strategies_at

catalog = registry(version=1)
# m1_rows/m5_rows must be supplied locally; no data is generated or fetched here.
report = strategies_at(
    'XAUUSD', m1_rows, m5_rows,
    datetime.fromisoformat('2026-11-12T08:30:00+00:00'),
    provenance='SYNTHETIC_RESEARCH',  # only for explicitly labeled synthetic inputs
)
assert report['signal'] == 'WAIT' and report['execution_allowed'] is False
```

Use normal IntelligenceConfig/ContextConfig defaults for research. Their hashes
remain unchanged from PR #12. Tests may use the inherited small-window synthetic
configurations to isolate components; those are not replacement production
settings. Registry rules add no new confluence weights, scores or thresholds.
No API endpoint is changed and existing working components are preserved.

## Validation and limits

The test module explicitly distinguishes synthetic observation-contract cases
from synthetic OHLC integration. The former compose typed existing IAT pattern,
zone, liquidity and structure observations to test each rule in isolation.
They cover both directions and qualifying, abstaining and invalidated states,
opposing CHoCH despite alignment, missing evidence, sequencing, sweep expiry,
level loss and blocked/insufficient context. Integration tests exercise actual
context/quality/prefix logic, unfinished M5 exclusion and future-append invariance.
Synthetic fixtures are not historical data and do not establish predictive value.

A future eligible export must still pass the source, calendar, finality and
cross-frame gates before historical full/full/prefix replay can be claimed.
Raw data must remain private. Neither tests nor CI validate an Exness terminal.

## Local verification results

The complete suite passed on Python 3.11.9 (545 tests, 54.669 seconds) and
Python 3.12.14 (545 tests, 39.431 seconds): all 521 inherited tests and 24
new registry/rule/causality tests. Both strategies qualify in both directions
through the actual context pipeline over labeled procedural synthetic OHLC.
Future-append invariance is checked for qualifying continuation and reversal
outcomes, not only abstentions. CI results are linked from the draft PR.
