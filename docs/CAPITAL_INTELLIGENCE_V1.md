# Capital Intelligence v1 — synthetic affordability only

E4.2 implements `assess_capital`, with `capital_arithmetic` as a separately labeled
arithmetic helper. Neither can authorize an order. A technically qualified setup
can still be financially unsuitable or unavailable. The intended research starting
capital is USD50, not a connected MT5 account balance or recommended account size.

## Authenticity and availability

Require actual E1/E2 producers and original/current reports through
`validate_risk_report`, the authenticated E3 report, current `PaperAccount`, typed
synthetic tape/quote, specification, costs, fill and capital policies. All setup,
direction, symbol, original qualification, frozen invalidation/target/configuration
and current cutoff bindings come from E3. Unavailable/blocked/expired/invalidated,
ambiguous, stale and already-observed exit hypotheses cannot open a position.
A checksum/provenance label alone is insufficient. The account cannot be replaced
by a caller-edited snapshot; future account state cannot inform an earlier decision.
An independent replay that genuinely produced identical sources is compatible;
Python object identity is not market identity.

The context is optional; when supplied, E3 authenticates it with its matching V3
view. Evidence components reuse structure, M1/M5 alignment, entry confirmation,
SR, momentum, volatility, liquidity, reference RR, integrity and contradictions.
Missing components remain UNAVAILABLE. There are no new scores or 40–90% confidence
classes. Evidence strength is separate from capital suitability. Future probability
calibration needs preregistered out-of-sample outcomes, denominators, uncertainty
and calibration assessment; it cannot be inferred from these fixtures.

## Specification and cost contracts

`BrokerSpecification` v1 declares symbol/feed, contract size, min/max/step volume,
tick size/value, point, account/profit/margin currencies, margin method/leverage,
minimum-stop distance/freeze level, commission/financing conventions, margin-call
and stop-out ratios, session eligibility, source, verification and effective/expiry
UTC. All financial inputs use exact decimal strings/integers, not floats/bools.
Values are synthetic declarations, never actual Exness defaults.

Implemented financial model: LINEAR_NOTIONAL_LEVERAGE, all three currencies USD,
tick_value = tick_size × contract_size per lot. Volumes lie on zero-origin step
multiples; min/max must themselves be multiples. Quotes/slippage must lie on the
tick grid. Unsupported margin/currency/convention or missing required fields block
the financial calculation. Every monitoring/exit quote is revalidated against
the same frozen specification, including its tick grid and effective dates.
A nonpositive modeled exit mark is unsupported and blocks calculation.
Point/tick/contract units stay separate. Minimum stop
and freeze values are instrument price units, not presumed broker points. Freeze
is retained metadata; no stop order or modification is submitted. No liquidation
is simulated merely from a broker label or unverified rule.

`SyntheticCosts` v1 explicitly declares commission/other costs in USD per lot per
side, adverse price slippage per fill, financing in USD per lot per 24 hours, and
conversion multiplier1 for this same-currency model. Missing is not zero. Zero is
allowed only as an explicit invented fixture assumption. Other currencies/margin
methods, financing credits/rollover calendars and real specification collectors
require further reviewed adapters.

`specification_collection_plan(symbol)` prepares the future read-only field
inventory and missing-evidence report. It performs **no terminal or account read**
and no network call. A future separately authorized symbol-info collector must
resolve feed/effectivity, units, commission, financing, leverage, account currency,
dated sessions/corrections and independent verification; metadata alone is not
approval. No collector is connected by E4.

## Explicit versioned policy and arithmetic

`CapitalPolicy` requires risk_fraction, aggregate_risk_fraction,
daily_loss_fraction, drawdown_fraction, free_margin_reserve,
max_positions=1, max_consecutive_losses, max_cost_fraction_of_budget,
reserve_holding_seconds, adverse_gap_price, and optional **explicit**
min_reference_rr (None disables that research filter), and reference_mapping. Candidate 0.5%,1%,2% budgets
are tested research alternatives, not live settings. There is no default lot,
mandatory timer, daily profit/pip target or leverage/risk escalation.

E3 retains an unknown OHLC price basis. E4 must not silently reinterpret it as
Bid, Ask or MID. The policy therefore explicitly requires
`reference_mapping='DECLARED_SYNTHETIC_ABSTRACT_REFERENCE_TO_QUOTE_UNITS'`.
Missing or unsupported mapping blocks capital assessment. Reports retain the
original price-basis object alongside that invented mapping. This only permits
comparison of abstract synthetic levels in common instrument units; it does not
verify a real feed, broker price basis or protective-stop execution model.

Fixed decimal context: precision34, HALF_EVEN. Volume rounds **down** using FLOOR.

- Eligible capital = min(current balance, current equity), positive and ACTIVE.
- Budget = eligible capital × selected risk fraction.
- Structural reference = original authenticated SR float lower−tolerance for
  bullish / upper+tolerance for bearish. E1/E2/E3 semantics are unchanged.
- Fill-to-reference distance uses the declared side-specific synthetic entry fill.
  It must have the correct sign and meet the declared minimum distance.
- Estimated per-lot loss = (distance + declared adverse gap) × contract size +
  two-sided commission/other costs + exit slippage × contract size + financing
  reserved for explicitly declared holding seconds. Entry slippage is already in
  the entry fill and is not charged twice. Spread is not charged again.
- Theoretical volume = budget / estimated loss per lot; floor to volume step,
  cap at max volume; reject below min lot. Never move the structural reference.
- Estimated margin = volume × contract size × entry fill / declared leverage.
- An existing frozen target must still be directionally favorable to the modeled
  entry fill; otherwise reject without selecting another target. The remaining
  fill-to-target reference distance is descriptive, not executable or net R/R.
- Projected free margin includes immediate side-specific mark-to-exit loss and
  both fees, not merely notional margin. Reject below reserve or projected call.

Reject daily cumulative realized losses at the selected fraction of original
starting balance, historical maximum drawdown at its policy limit, consecutive-loss
limit, aggregate estimated exposure, concurrent-position limit and excessive
estimated costs. Daily buckets use UTC; loss budgets do not reset intraday when a
later position wins. Only one open position is supported. Drawdown is never reset
after a loss. An optional reference-RR filter is explicitly selected/versioned and
does not change confluence, E1/E2 predicates, scores or WAIT.

Risk is an estimate: quote gaps and slippage beyond assumptions can exceed the
budget and even exhaust the synthetic account. Negative balances are retained.
No stop guarantee or leverage recommendation is implied.

Outputs distinguish CAPITAL_ASSESSMENT_UNAVAILABLE, FINANCIALLY_UNSUITABLE and
HYPOTHETICAL_POSITION_ELIGIBLE. They retain source/account/policy/spec/cost/quote
hashes, reasons, theoretical/down-rounded size, minimum-lot affordability, margin
and cost exposure. `validate_capital_report` recomputes using those actual inputs.
The isolated arithmetic helper explicitly establishes no source eligibility.
E3's fill, sizing, margin, net-return and execution fields remain unchanged/null.

## Frozen invented examples

`docs/research_audits/paper-capital.synthetic.json` is reproducible with
`python tests/paper_examples.py`. Prices and specs are invented, not Exness evidence.

A: USD50,1%,budget0.50,contract100,reference distance2 → theoretical0.0025 lot.
Synthetic min0.01 → REJECT; downward grid size0, never upward0.01.

B: USD50,2%,budget1,contract100,distance1 →0.01 lot with explicitly zero costs.
Any additional positive costs can make the minimum lot unaffordable; they are not
assumed away to preserve that size.

C: actual source-bound invented E1/E2/E3 setup, toy contract1, min/step0.1,
volume0.2, entry Ask2100.1, structural threshold2097.74, later eligible Bid2090.1
after structural invalidation → modeled loss2, balance48, next1% budget0.48.
Estimated original loss0.472 did not guarantee a maximum loss. No deposit/reset
manufactures the balance. These are accounting fixtures, not strategy returns.
