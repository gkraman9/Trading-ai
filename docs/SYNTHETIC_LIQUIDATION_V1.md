# Synthetic Liquidation v1

Research-only; WAIT; execution_allowed=false; Exness BLOCKED; DATA_NOT_QUALIFIED;
historical validation PENDING; historical comparisons NOT_RUN. No broker behavior
or broker permission is established by this model.

## Explicit assumptions

`LiquidationPolicy` v1 supports only SYNTHETIC_EQUITY_OVER_FROZEN_ENTRY_MARGIN,
NET_LIQUIDATION_EQUITY_WITH_DECLARED_COSTS, and SYNTHETIC_EXIT_ON_STOP_OUT_ONLY.
Thresholds come from the authenticated dated invented specification; no actual
Exness thresholds are assumed. Initial margin stays frozen at entry notional /
declared leverage for this version. Equity uses current side-specific liquidation
price, declared adverse exit slippage, entry/exit charges and elapsed financing.
Margin level = equity / used margin *100. Free margin = equity - used margin.
Zero used margin has no finite level and no margin warning or stop-out. Negative
equity/free margin/level remain negative. Threshold ratios are converted to percent
for displayed comparison; exact contact uses <=.

A margin-call warning records an event and restricts new entries. It never closes
an existing position. Recovery clears the current restriction without erasing the
warning, losses or historical drawdown. Stop-out creates a causal pending intent;
only an eligible authenticated quote can close it. Latency/trigger-row fill policy
is explicit and frozen. Long liquidation uses Bid, short liquidation Ask; adverse
slippage, commission, financing and other charges use the same settlement path
as protective/structural exits, once only. Closure releases used margin.

Coincident stop/liquidation roles share one fill only when their independently
frozen execution policies imply the identical result. Different latencies or
unresolved competing E2 evidence leave UNRESOLVED; no favorable precedence.
Missing/incomplete observations remain unresolved. A cutoff review records this
separately and does not pretend a quote was observed at end of input.

## Adverse accounting

Negative ending balance is retained, with account exhaustion and entry rejection.
There is no deposit, martingale, automatic risk escalation, forced zero floor or
assumed negative-balance protection. The observed equity watermark preserves
maximum drawdown across later profitable recovery. Loss-day attribution uses the
modeled fill UTC date, not delayed caller processing time. Existing minimum-lot,
daily loss and consecutive-loss checks remain in force.

The USD50 synthetic examples A–N cover stop/gap/delay/missing fills, margin warning,
stop-out, structural and liquidation conflicts, negative/exhausted accounts,
minimum-lot rejection, repeated losses, recovery and missing intervals. They are
accounting fixtures, not profitability evidence. The live panel exposes availability
labels only (BLOCKED / NOT_RUN / PENDING), never these synthetic balances.

## Remaining qualification

Actual quote completeness, provider basis, dated specification/cost/session evidence,
finality/corrections, source permission and independent approval remain outstanding.
No historical replay/qualification claim is made. Next milestone: independent
review of v2 semantics and qualified synthetic-to-historical import design, without
activating live computation or altering any assurance gate.
