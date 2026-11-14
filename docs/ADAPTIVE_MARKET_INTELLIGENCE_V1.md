# Adaptive Market Intelligence Engine v1

This is a deterministic offline research assessment over existing IAT context.
Adaptive means compatibility changes with the observed regime; it does not mean
online learning, automatic threshold tuning or selection by past profitability.
The regime/compatibility/ranking policies are original IAT research choices,
not reproduced third-party methods or validated predictors.

`adaptive_at` consumes causal M1/M5 histories through the existing `context_at`
and its data-quality, closed-candle, session, continuity, OHLC and freshness
gates. `assess_adaptive` is the lower-level typed ContextReport consumer for
observation-contract tests; it is not another raw-data eligibility path.
There is no broker/provider/network access or new live HTTP endpoint.
Unsupported live/unverified provenance blocks this version. Invalid request
configuration is rejected; malformed history selection returns BLOCKED without
inventing observations. All output remains read-only.

## Directional classification v1

Each timeframe needs one unambiguous existing STRUCTURE interpretation, matching
its context label and backed by at least two distinct confirmed HIGH pivots and
two distinct confirmed LOW pivots from that timeframe. Candidate/unconfirmed
pivots do not count. Structure evidence and referenced sources must be available
by the closed frame/query timestamps. The existing intelligence engine determines
HH/HL/LH/LL and structure classifications; this layer does not replace that logic.

Classification precedence:

| Result | Required observations |
| --- | --- |
| UNKNOWN, status BLOCKED | Data-quality failure, unavailable/future/conflicting evidence, invalid context configuration hash, unsupported provenance or unsafe observation contract. Observations and rankings are quarantined. |
| UNKNOWN, status UNKNOWN | Data passes its gates, but either timeframe lacks the required confirmed structural evidence or its interpretation is ambiguous/inconsistent. Scenario scores/ranks remain null. |
| TRANSITION | Both structures are established and a fresh M1 CHoCH opposes directional M5 structure, or a fresh M1 CHoCH appears against nondirectional M5 context. This takes precedence over matching pivot-based labels. |
| TREND_UP | Both established structures are BULLISH and the preceding transition condition is absent. |
| TREND_DOWN | Both established structures are BEARISH and the preceding transition condition is absent. |
| RANGE | Both established structures are RANGING and the transition condition is absent. |
| TRANSITION | Other established combinations: disagreeing timeframes or either structure TRANSITIONAL. |

Fresh retains the existing rule meaning: the CHoCH is available on the latest
closed M1 frame, not merely a favorable Phase 7 alignment label. TRANSITION
reports a structural disagreement/change proxy, not proof a reversal will finish.
READY means a research classification is available; it never means ready to trade.

## Independent volatility

The engine copies existing per-frame ATR, disjoint-range ratio, change and
volatility regime. It does not create new volatility thresholds. Overall HIGH
means at least one frame reports HIGH_VOLATILITY. If neither is HIGH, both must
have established measurements: both LOW gives LOW, both NORMAL gives NORMAL,
and LOW/NORMAL disagreement gives MIXED. Otherwise the result is UNKNOWN.
Missing measurements remain explicit even when the other frame is HIGH.

Directional regime is not overwritten by volatility. TREND_UP + HIGH and
TREND_DOWN + HIGH are valid combinations. High volatility adds uncertainty;
it does not change the existing experimental strategy predicates.

## Regime compatibility policy v1

Every snapshot evaluates both existing strategy rules in both directions,
independently, preserving their original QUALIFIES/ABSTAINS/INVALIDATED results,
reason codes and evidence references. The table is a separate policy:

| Regime | Continuation bullish / bearish | Sweep reversal bullish / bearish |
| --- | --- | --- |
| TREND_UP | SUPPORTED / INCOMPATIBLE | SUPPORTED / CONDITIONAL |
| TREND_DOWN | INCOMPATIBLE / SUPPORTED | CONDITIONAL / SUPPORTED |
| RANGE | INCOMPATIBLE / INCOMPATIBLE | SUPPORTED / SUPPORTED |
| TRANSITION | CONDITIONAL / CONDITIONAL | SUPPORTED / SUPPORTED |
| UNKNOWN or blocked | UNKNOWN / UNKNOWN | UNKNOWN / UNKNOWN |

An adaptive CANDIDATE requires READY context, original rule QUALIFIES and
SUPPORTED compatibility. CONDITIONAL does not authorize a candidate: further
structural clarification is needed. Compatible approaches whose rules abstain
or invalidate are RULES_FAILED. A qualifying rule without supported regime fit
is REGIME_UNSUITABLE. Unknown context is UNKNOWN; blocked context does not run
the strategy evaluator. Compatibility never repairs missing confirmation,
invalid zones, opposing CHoCH, missing history or other rule failures.

Trend-aligned sweep reversal here means recovery of M1 structure within the
broader trend. A counter-direction sweep needs transition/range evidence before
full regime support. This is a declared IAT interpretation, not an empirical
strategy advantage. Some conditional states cannot qualify simultaneously with
the unchanged strategy predicates; they describe what an approach still needs.

## Scenario and candidate ranking policy v1

Bullish, bearish and neutral scenarios use existing capped evidence weights from
the supplied, hash-checked ContextConfig. Contributions are capped by timeframe,
category bucket and direction exactly as in the existing confluence evaluator.
Zones share the original PRICE_ZONE cap; volatility contributes zero directional
weight. No existing weights, minimum-score, margin or contradiction thresholds
are modified. The diagnostic confluence votes/abstentions remain visible.

For each scenario:

```text
support = existing capped score for its direction
opposition = maximum capped score among the other two directions
research heuristic = support - opposition
```

Neutral uses the RANGING score; it is a range/nondirectional scenario, not a
probability of no price movement. NEUTRAL evidence such as volatility and dojis
is not assigned invented directional voting weight. Bullish/bearish/neutral
support and opposition IDs, assumptions, invalidation conditions and additional
observations that could change the assessment are recorded explicitly.

Scores are labeled RESEARCH_HEURISTIC_NOT_PROBABILITY. Dense ranks preserve
all exact ties; a lexical presentation order does not choose a winner. Candidate
ranking includes only regime-supported, predicate-qualified candidates and uses
their directional scenario's heuristic. There is no learned strategy-specific
bonus or extra score cutoff. Multiple candidates may tie; none may qualify.
The best eligible candidate can still have a nonpositive score or a scenario
that does not lead overall. Those conditions are explicitly uncertain, not
silently filtered or interpreted as favorable trading recommendations.

Legacy confluence's single `leader` remains a diagnostic inside `confluence_votes`;
the adaptive assessment's `top_scenarios` preserves ties independently. Legacy
hypothesis selection and the original strategy predicates are not replaced.

## Report and compatibility

Version 1 reports include symbol, UTC timestamp, sanitized research provenance,
READY/UNKNOWN/BLOCKED status, directional regime, independent volatility,
data-quality diagnostics, observation-contract status, observed candle facts,
existing interpretations/source registry, four candidate assessments, three
scenarios, conflicts, uncertainty, reason codes and policy versions.

Hashes identify context, intelligence, strategy registry, adaptive policy,
compatibility policy, ranking policy and optional session/finality settings.
Canonical JSON SHA-256 covers the report excluding its own hash.
`validate_adaptive_report` checks safety/version, policy hashes, causality,
evidence references, eligibility, scores, ranks and leaders. A checksum is not
a source authentication or proof of broker data completeness.

Observed candle OHLC/counts/as-of times are kept separate from structural,
zone, liquidity and volatility interpretations. The resulting assessment does
not rewrite either input layer. Full reports contain OHLC and should stay
private for real data; the published synthetic audit contains hashes and
summary metadata only.

DecisionLog v1, Strategy Replay Log v1 and PR #15's manifest-gated replay and
warm-up/evaluation accounting are unchanged. A regression runs the manifest
pipeline before/after adaptive assessment and requires identical results.
Research provenance alone never establishes dataset eligibility: use the
[existing manifest gate](STRATEGY_DATASET_REPLAY.md) for future historical work.
Every adaptive report still has historical_validation=PENDING,
historical_decision_log_comparisons=NOT_RUN, Exness BLOCKED, signal WAIT and
execution_allowed=false. No eligible historical export was used here.

## Offline use

```python
from iat.intelligence.adaptive import adaptive_at, validate_adaptive_report

# Supply local histories; this module never creates or downloads market prices.
report = adaptive_at('XAUUSD', m1_rows, m5_rows, aware_utc_timestamp,
                     provenance='SYNTHETIC_RESEARCH')  # synthetic inputs only
validate_adaptive_report(report)
assert report['signal'] == 'WAIT' and report['execution_allowed'] is False
```

`replay_adaptive` yields strictly chronological M1-close assessments with an
optional visibility cutoff. Full supplied warm-up prefixes are retained.
Unknown/blocked observations are recorded rather than replaced with prices.
As with prior replay, this is a bounded, recomputing reference implementation;
throughput optimization is a later milestone.

## Actual synthetic outcomes and limits

The [checked-in audit](research_audits/adaptive-intelligence-synthetic-v1.json)
records input/config/report hashes and exact outcomes. It uses inherited
small-window test configurations, not replacements for production defaults.

- Twelve OHLC snapshot cases: 9 READY, 1 UNKNOWN and 2 BLOCKED. They cover up/down
  trends, normal and high volatility, ranges, fresh opposing CHoCH, confirmed
  reversal candidates, structural disagreement, absent confirmations,
  insufficient history, gaps and directly supplied unfinished M5 candles.
- Actual trend cases produce one matching continuation candidate. Both reversal
  directions qualify as candidates in TRANSITION. RANGE leads with the neutral
  scenario but no strategy qualifies without its own sweep/confirmation rules.
- Opposing frames produce an exact bullish/bearish scenario tie and no candidates.
  Two separately labeled synthetic observation-contract cases demonstrate tied
  continuation/reversal candidates in each direction; they are not acquired OHLC.
- Five chronological OHLC replays contain 112 timestamps: 72 READY, 30 UNKNOWN,
  10 BLOCKED. They include 13 up-trend, 13 down-trend, 16 range, 30 transition and
  40 unknown-regime observations. Two initial blocked and six insufficient-
  structure snapshots per case are retained, rather than hidden as warm-up.
- Repeated full sequences matched in all five cases. Prefixes of 20/20/23/22/22
  entries matched their full overlaps; adding future M1 and unfinished M5 bars
  did not revise earlier assessments.

These are deterministic software results, not predictive accuracy, profitability,
validated strategy superiority or real-terminal results. Structure, OHLC sweep
and zone interpretations are proxies. Compatibility and ranking are experimental
original IAT policy choices. Primary data rights, dated sessions and closed-bar
provenance remain unresolved for the available pilot as documented in prior PRs.

## Local verification

The complete suite passed on Python 3.11.9 (613 tests, 78.459 seconds) and
Python 3.12.14 (613 tests, 56.361 seconds): 586 inherited tests plus 27 new
adaptive tests. These cover policy versions, causal references, classifications,
volatility independence, original strategy outcomes, ranking/ties, blocked and
unknown states, malformed inputs, unfinished bars, repeat/prefix/future checks
and preservation of manifest replay accounting. Final Linux/Windows CI results
are recorded in the draft PR. No live terminal or historical export was used.
