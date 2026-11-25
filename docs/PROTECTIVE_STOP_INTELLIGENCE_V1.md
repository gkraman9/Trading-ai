# Protective Stop Intelligence v1 (E4.6)

This is invented, offline research, not broker execution simulation certification.
Every report preserves WAIT, execution_allowed=false, Exness BLOCKED,
DATA_NOT_QUALIFIED, historical_validation=PENDING and comparisons=NOT_RUN.
There is no live evaluator, terminal connection, credential lookup or order call.

## Contract and causal transaction

`protection_contracts.assess_protection_plan` authenticates the original E1/E2/E3
producers and the unchanged Capital Intelligence calculation. `ProtectedPaperAccount`
is a separate producer with journal/report version 2. Ordinary `PaperAccount` and
DecisionLog/Strategy Replay contracts retain their versions and meanings.

`ProtectiveStopPolicy` v1 requires an explicit
`DECLARED_SYNTHETIC_STRUCTURE_TO_QUOTE_STOP` mapping, `LONG_BID_SHORT_ASK`
trigger basis, latency in milliseconds and triggering-quote fill permission.
Unknown E3 OHLC basis stays UNKNOWN: this declaration does not establish real
Bid/Ask correspondence. Unsupported/missing mappings fail closed. The original
structural threshold is frozen exactly; it must lie on the specification tick
lattice, on the adverse side of the current trigger-side quote and beyond the
minimum stop distance. We never round/tighten it for affordability.

The plan is established at the entry quote's receipt. The versioned journal orders
PROTECTIVE_STOP_ESTABLISHED before ENTRY_PENDING/HYPOTHETICALLY_OPEN in the same
atomic receipt transaction. This is an explicit synthetic zero-extra-establishment-
delay assumption; timestamps can be equal while logical order is fixed. Failed
entry transactions leave no established/open position or partial history update.
The plan freezes source/report/specification/cost/policy/configuration hashes,
original threshold, entry risk budget and source clock. There is no stop modification.

Eligible Bid <= threshold activates a long; eligible Ask >= threshold activates a
short. Occurrence, receipt/decision availability, triggering quote, latency deadline,
first eligible fill row, adverse slippage and costs are distinct fields. A triggering
row can fill only under the explicitly selected zero-latency/can-fill policy.
Otherwise the first authenticated post-trigger eligible observation after the
occurrence deadline is used. There is no invented threshold-price fill, best-price
selection or guaranteed maximum loss. Recovery during pending latency does not
cancel/reprice a triggered exit.

## Observation completeness and uncertainty

Consume every source quote once, at its receipt, in sequence. All prior consumed
producer rows are privately authenticated, not just the latest row/labels. Duplicates
are idempotent; missing known sequence rows, gaps beyond the existing FillPolicy,
closed quotation sessions or stale structural analysis produce UNRESOLVED.
Invalid/future/stale/forged input is rejected without advancing state. Existing
freshness/analysis-age limits are not widened. A long-running experiment must
supply refreshed authenticated causal E2/E3 observations; stale analysis is not
silently authorized just because the stop is frozen.

New E2 observations retain their closed-bar availability and intervals. Ambiguous
E2 or distinct stop/structural/liquidation exits in one callback or during pending
fill remain unresolved; we do not introduce event precedence. The only coalescing
case is stop and liquidation triggered on the same row/time with exactly identical
latency, fill-row permission, side and cost function. That has one fill/one expense
and two recorded roles. There is no general cross-model event-order adapter.
`review_cutoff` is a separate immutable end-of-input review; missing exit horizon
stays unresolved, never a fabricated forced close. Later quotes may add journal
records without changing the previously returned review or journal prefix.

## Exposure and metrics

Sizing reuses the original side-specific entry, adverse-gap allowance, slippage,
fees, financing reserve, minimum volume/step, free margin, daily/drawdown/consecutive
loss rules and downward rounding. Estimated exposure is not a loss guarantee.
Per-closed-position metrics retain estimated risk, realized loss, entry-budget
exceedance and stop-to-fill adverse displacement. The latter includes latency/
slippage price effects; it is descriptive and is not charged again as a cost.
Resolved and unresolved denominators stay separate; unresolved P&L is unknown.

The isolated invented arithmetic example uses entry Ask3500.15, stop3499.65,
0.01lot and contract100: estimated price risk USD0.50; first eligible Bid3498.90
implies gross loss USD1.25, USD0.75 beyond the stop-price risk, before additional
costs. It is arithmetic, not an authenticated opportunity or historical result.
End-to-end fixtures use different invented E1/E2 structure around2100 and a toy
contract1 to exercise a USD50 book. No fixture is an Exness specification.

## Reproduction and limits

Run `python diagnostics/protection_synthetic_examples.py --output new-examples.json
--benchmark` from the project root. Output must not already exist. It constructs
14 labeled A–N scenarios from actual synthetic source producers; never reads MT5 or
private datasets. See tests/test_protection*.py and the independent review document.

Resource/event/byte limits roll back each transaction, including private source
proofs. In-process producers are not a security sandbox or signed external evidence.
A qualified historical source/capture and a separately reviewed import adapter are
still required; this function is not a manifest-gate bypass. No live paper bridge,
TP2/TP3, partial/trailing/timer exits, new strategy or broker calendar changes exist.
