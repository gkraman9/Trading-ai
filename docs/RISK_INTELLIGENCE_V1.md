# Risk Intelligence v1 — E3 reference research

Model IAT_RISK_INTELLIGENCE_V1; report/risk policy version 1. Synthetic-only,
stateless, deterministic source projection. It does not create a trade, position,
fill, stop, target allocation, order, probability, executable size, margin, capital
risk or profitability result. Source eligibility, geometry availability, original
hypothesis lifecycle, ambiguity and costs remain separate.

[Automated E2 contract review](EXIT_INTELLIGENCE_V1_INDEPENDENT_REVIEW.md) passed
21 new adversarial tests before implementation. No verified critical/high/medium
defect required correction. Low limitations remain: in-process authentication and
bounded full-prefix verification cost. This is not external human approval.

## Six stages and public interface

1. Authenticate original E1 and E2/current E2 against their actual producers.
2. Recover the original confirmation observation and frozen invalidation.
3. Project reward from the unchanged original frozen E2 target.
4. Optionally describe original reference distances relative to current source ATR.
5. Validate availability of explicitly synthetic cost declarations; never approve a
   cost/fill model or compute net costs.
6. Explain reference geometry, lifecycle restrictions, missing evidence and WAIT.

```python
from iat.intelligence.risk_intelligence import assess_risk, validate_risk_report, RiskPolicy
inputs = dict(original_e1=original_e1_report,
    original_e2=qualification_cutoff_e2_report, current_e2=current_e2_report,
    entry_source=original_entry_session, exit_source=producing_exit_session,
    as_of=current_e2_report['current_observation_cutoff_utc'],
    policy=RiskPolicy(atr_timeframe='M1'),
    context=current_context, view=current_v3, view_inputs=current_v3_inputs)
report = assess_risk(**inputs)
validate_risk_report(report, **inputs)
```

Context/view are optional only if volatility is unavailable; any supplied pair is
still authenticated even without a selected ATR timeframe. Provide both or neither.
ATR timeframe must be explicitly M1 or M5; None does not silently choose a frame.
No wall clock is read. An explicit evaluation cutoff is required and must equal
current authenticated E2 cutoff. A past authenticated report can describe its own
cutoff; it is not an assertion about the current live market. Missing/stale explicit
cutoff, blocked current E2, incorrect source or incompatible supplied data fails
closed and withholds geometry.

Original E1 must be an authenticated SYNTHETIC_RESEARCH qualification-cutoff report.
Both E2 reports must be authentic outputs of the same provided ExitResearchSession.
Original E2 cutoff must equal qualification; current identity, direction, original
E1 hash, configuration hashes, policy/body/hash, frozen invalidation, target and
candidate references must match. The setup ID can be explicitly asserted. A new
checksum, another producer, changed symbol, later target selection or live/historical
label cannot establish eligibility. The original E1 producer's public fork_at
verifies the exact old SR prefix; its qualification bar supplies the confirmation
price/ID/open/availability. Later producer state cannot revise it.

Existing E1/E2 contracts, strategy predicates, ranking, confluence thresholds,
source calendars and execution permissions are unchanged. There is no historical
or live bridge, and no arbitrary serialized log importer. Validation remains an
in-process source contract, not cryptographic provider authentication or a Python
sandbox. Portable authenticity requires reviewed raw-source replay and independent
qualification, not hashes alone.

## Exact geometry and arithmetic contract

Let C be the observed confirmation close, L/U the original frozen zone bounds,
and T the original break tolerance. Let N be the frozen target near boundary.

| Direction | Original SR invalidation threshold B | Reference risk | Reference reward |
|---|---|---|---|
| Bullish | L − T, strict eligible close < B | C − B | target lower − C |
| Bearish | U + T, strict eligible close > B | B − C | C − target upper |

Threshold B is computed using **the same Python float operation as the original
SR rule**, not a rationalized or newly buffered substitute. Its shortest round-trip
decimal representation is then used for reference arithmetic. This preserves the
original strict breach threshold, including source floating-point detail. No
broker-point conversion, rounding-to-tick, extra buffer or executable stop occurs.
The threshold must be finite/positive; reference distances must be positive and
directionally consistent. Missing, zero, negative, boolean, nonfinite or unsupported
numeric references reject. Input numeric width/exponent guards prevent unbounded
formatting; no positive/negative quantity is silently clamped into validity.

Reference reward-to-risk = reference reward / reference risk. Calculation basis is
**REFERENCE_RR_ONLY**, price distances INSTRUMENT_PRICE_UNITS, ratio DIMENSIONLESS.
Outputs use canonical decimal strings with explicit local precision 34 and
ROUND_HALF_EVEN, independent of ambient Decimal settings. They are not broker
points, account currency, expected profit, realized/net/fill-based R/R or a success
probability. Unknown price basis remains unavailable, not assumed Bid. Same-source
instrument reference geometry can still be described with that explicit limitation.

All frozen E2 target candidates remain preserved. Near-boundary distance is distinct
from far-boundary confirmation: WICK_CONTACT and CLOSE_BEYOND_REFERENCE retain their
original policy/hash and actual E2 observation semantics. E3 neither changes that
policy nor selects a new target. TARGET_UNAVAILABLE leaves risk distance available
but reward and ratio null. The scalar reference_geometry function is isolated
arithmetic with authentication=NOT_ESTABLISHED_BY_ARITHMETIC; its output is never a
trusted risk report or source qualification interface.

Proposed future research comparisons at 1:1, 1:1.5, 1:2, 1:2.5 and 1:3 are **not
implemented thresholds or validated rules**. No ratio rejects, approves, selects
or ranks an opportunity. A future comparison must be explicitly selected/versioned
and must not alter E1/E2 qualification or the operational decision.

## Source-bound volatility and costs

When selected, ATR is reused from the matching typed ContextReport/V3 at the
current E2 cutoff. The existing V3 validator establishes canonical context binding;
E3 does not invent a second raw-context hash scheme. Preserve timeframe, actual
ContextConfig ATR period, evidence ID/references, occurrence/availability/cutoff,
configuration hash, units and the existing volatility/momentum observations.
The selected frame's data_as_of must match evidence availability and not exceed
cutoff. M5 can legitimately have an earlier closed cutoff than M1; they are never
mixed. Missing/warm-up/zero/incompatible ATR is VOLATILITY_UNAVAILABLE. Edited or
future source evidence blocks rather than accepting a supplied ATR scalar.

Descriptive ratios are original reference risk / current selected ATR and original
reference reward / that same ATR. They are not an ATR stop or risk rating. Existing
HIGH_VOLATILITY source labels may be displayed as observations; E3 does not invent
LOW/MEDIUM/HIGH risk classes or a volatility eligibility threshold.

Optional costs is a strict version-1 dictionary with headers version, symbol,
e2_sha256 and provenance=SYNTHETIC_RESEARCH_DECLARATION. Optional fields are bid,
ask, spread, broker_point, tick_size, tick_value, contract_size, commission,
slippage, account_currency, currency_conversion, swap, quote_at_utc,
quote_available_at_utc, price_basis, evidence_sha256 and a units mapping. Unknown
fields reject. Symbol/current-E2 binding mismatches block projection. Numeric,
units, currency, basis and timestamp consistency are mechanically checked; future
quote availability rejects. With Bid/Ask, preserve BID_ASK and occurred <= available
<= cutoff; declared spread must equal declared Ask − Bid under local arithmetic.
A missing spread is not inferred from OHLC or silently filled as zero. Zero fees
are only an explicit synthetic declaration, not a default assumption.

Missing values remain UNAVAILABLE. Valid supplied values are DECLARED_SYNTHETIC_NOT_
QUALIFIED (or DECLARED_UNITS_UNAVAILABLE), never independently observed/qualified.
Malformed declarations are INVALID_DECLARATION and unavailable for cost reasoning;
independently authenticated geometry may remain available. A declared evidence
hash is not independent evidence. Freshness is NOT_ESTABLISHED_NO_REVIEWED_QUOTE_POLICY;
there is no new or widened quote tolerance. No Exness specification, commission,
slippage, currency conversion or swap is hardcoded. Signed swap/conversion/commission
conventions require a future reviewed model; unsupported inputs remain invalid or
unknown rather than coerced. qualified_model_available is always false in E3.

Future verified cost evidence needs provider/source provenance, quote UTC and
receipt clocks, symbol-specification validity dates, price units, tick/point/value,
contract and account currency, commission basis, slippage and conversion evidence,
and financing where applicable. Side-specific fill prices already incorporate
spread: **do not add spread a second time**. E3 encodes that contract but computes
no net cost or profitability. Descriptive live spread is a separate observation,
not a qualified cost-model input.

## Report, lifecycle and limits

The canonical report includes model/report/policy versions, original setup/symbol/
direction/qualification, original E1/original-current E2 hashes, explicit evaluation
cutoff, confirmation reference with source ID/times, frozen zone/threshold/targets,
reference geometry/basis/units, ATR source, cost availability, source restrictions,
original lifecycle, ambiguity, missing/supporting/contradictory evidence, explanation,
configuration and policy hashes, validation status and safety.

Multiple states coexist: REFERENCE_GEOMETRY_AVAILABLE, TARGET_UNAVAILABLE,
VOLATILITY_UNAVAILABLE, COST_MODEL_UNAVAILABLE, FILL_MODEL_UNAVAILABLE,
HYPOTHESIS_INVALIDATED, HYPOTHESIS_EXPIRED, OBSERVATION_ORDER_UNRESOLVED and ABSTAINED.
Bad sources block with SOURCE_MISMATCH; invalid arithmetic has
REFERENCE_GEOMETRY_INVALID/RISK_REFERENCE_UNAVAILABLE diagnostics. An invalidated
or expired hypothesis's original geometry can remain available for analytical
review, with its actual terminal state preserved. It does not become a new entry.
E2 ambiguity and skipped-observation uncertainty are copied unchanged. There is
no TRADE_APPROVED state or operational BUY/SELL.

Always null: entry_fill, exit_fill, executable_stop_loss, executable_take_profit,
fill_based_risk_reward, net_risk_reward, position_size, capital_at_risk,
margin_required, hypothetical_pnl, realized_pnl, expected_return,
probability_of_success and performance_metrics. No numerical confidence is emitted.

Canonical SHA-256 covers sorted JSON without sha256; NaN is forbidden. A valid
report must exactly reproduce from its actual supplied sources through assess_risk.
Checksum-only validation cannot authenticate it. Canonical empty blocked reports
can validate standalone but establish no eligibility. Previously returned reports
remain immutable; after producer advancement, re-verification uses those same
frozen sources/cutoff. No E3 lifecycle, cache, account or duplicate source log is
stored. Original E1/E2 objects are never advanced or mutated by E3.

Parent bounds remain. E3 adds 2,048 frozen candidates, 10,000 supplied context
source IDs and a 1,000,000-byte canonical report ceiling. Failures return explicit
unavailable/blocked states without source mutation or silent reset. The byte guard
includes sha256 and UTF-8 canonical encoding. Benchmark boundary testing lowers
that engineering budget to the actual report's byte size: exact budget passes,
one byte below blocks. It is not maximum-dataset throughput/memory certification.

## Worked examples and testing

`docs/research_audits/risk-intelligence.synthetic.json` separates:

- Illustrative A: C=2100, original float threshold=2098, target near=2106 → risk 2,
  reward 6, reference R/R 3. Arithmetic only; no source authentication.
- Illustrative B: C=2100, threshold=2102, target near=2094 → the same 2/6/3.
- Illustrative D: nonpositive risk is explicitly rejected, not repaired.
- End-to-end independently invented E1/E2 reports: actual detector-confirmed source
  levels yield their own geometry, not injected 2/6/3 prices. Missing target keeps
  risk only; E2 ambiguity remains unresolved; missing costs do not become zero or
  net R/R. All examples are SYNTHETIC_ONLY, not historical/profitability evidence.

Run tests and benchmark from the repository root:

```text
python -m unittest discover -s tests -p test_exit_independent_review.py -v
python -m unittest discover -s tests -p test_risk_intelligence.py -v
python -m unittest discover -s tests -v
python tests/benchmark_risk_intelligence.py
```

The complete focused and full Linux/Windows 3.11/3.12 results are recorded in the
new draft PR. The existing actual Windows PowerShell 5.1 -File regression remains.
CI's job-only execution budget is 25 minutes for the growing strict suite; no
market-data freshness, source verification, strategy or risk tolerance is widened.

## Windows and remaining blockers

Preserve local changes. Do not force/reset/clean or merge a PR. In PowerShell:

```powershell
$iatRoot = 'E:\IAT2\IAT3-Live-Test'
git -C $iatRoot status --short
git -C $iatRoot fetch origin refs/heads/feat/iat-v3-risk-intelligence-v1
git -C $iatRoot switch --no-track -c local/iat-v3-e3-review FETCH_HEAD
git -C $iatRoot rev-parse HEAD
powershell.exe -NoProfile -File "$iatRoot\diagnostics\Start-IATLiveMarketView.ps1" -ValidateOnly
```

Verify HEAD against the draft PR's exact SHA. If that local branch exists, inspect
it or choose another fresh name; never overwrite it. After manually stopping the
old dashboard on port 8768, remove -ValidateOnly to start the existing read-only
observer with a fresh private GUID journal outside Git. Keep DEMO and terminal/API
trading disabled. No B.2/B.3 startup, credential input or AI activation is added.
The four availability areas remain blocked/unavailable for live E1/E2/E3; actual
live quotes/spread stay descriptive. Operator confirmation of PR #47 startup is
not independent verification of this version or of the lower panel. Cloud DOM/
PowerShell tests do not establish actual terminal or visual Windows success.

Historical qualification remains PENDING; comparisons NOT_RUN, metrics unmeasured.
No qualified export, independent approval or portable historical bridge was
available or run. Next: independent E3 contract review, then a narrowly scoped E4
synthetic quote/fill contract with validated side/timing/cost evidence. See
PAPER_TRADING_ENGINE_ARCHITECTURE.md. WAIT; execution_allowed=false; Exness BLOCKED;
DATA_NOT_QUALIFIED. No live or demo orders, sizing or calendar approval.

## Recorded synthetic benchmark and focused validation

Linux Python 3.11.9, prebuilt identical synthetic inputs, tracing enabled:

| Component | Milliseconds | Peak traced bytes |
|---|---:|---:|
| Source authentication including matching V3/context | 526.383 | 1,391,842 |
| Isolated reference calculation | 0.131 | 2,281 |
| E1 on same current input | 1,634.193 | 1,791,327 |
| E2 on same current input | 1,656.573 | 1,939,153 |
| E3 complete projection | 538.389 | 1,395,607 |

Three fully reverified E3 repeats: 534.336 / 541.434 / 533.737 ms, peak traced
allocations up to 1,397,689 bytes. The 9,411-byte canonical report passes at an
exact 9,411-byte engineering budget and blocks at 9,410, with producer state
unchanged. Report SHA-256:
`08ffc3449118c21c0ad3ddf16f584de0dbfbbc7ede68c94c709e6456e42b10c4`.
E3 consumes already authenticated E1/E2 reports rather than rerunning their full
lifecycle, so this comparison is component cost on the same inputs, not a whole
pipeline speedup claim. Source construction, process RSS, maximum-sized datasets,
Windows/MT5/network latency and profitability are not measured. Timings vary;
strict authentication remains enabled on each repeat.

Focused review/E3 plus inherited E2/live-view: **144 tests passed** on Python
3.11.9 (128.439 s) and 3.12.14 (111.945 s), including 21 new review and 47 E3 cases.
Five committed metadata SHA-256 checks pass, zero restored files. Complete local
suite and exact-head Linux/Windows CI evidence are recorded in the draft PR.
