# Paper trading v1 — bounded synthetic milestone

Parent PR #48 exact baseline `47c269c75520d1c373498ba8e4651353f15689cd`.
No earlier E4 PR existed. Work is on `feat/iat-v3-paper-capital-v1`, separately
stacked on PR48. Existing PRs, E1/E2/E3 contracts, session calendars, thresholds,
execution gates and private datasets are preserved.

## Implemented scope

E4.1: automated E3 adversarial review and authenticated typed synthetic quotes/
side-specific fills. E4.2: synthetic USD paper account and capital assessment under
one supported linear same-currency model. E4.3: one-position lifecycle reacting to
authenticated E2 structural target/invalidation/opposing structure. E4.4: canonical
paper journal and descriptive synthetic accounting. E4.5: blocked availability-only
live panel plus automated adversarial E4 review. **This is not the complete future
paper-trading engine**, independent human approval, live activation or historical
validation. Unsupported exits/models remain explicit below.

## Account and lifecycle

`PaperAccount(started_at=UTC, starting_balance='50')` creates an invented USD account,
not a terminal account. It records balance, unrealized hypothetical P&L, equity,
used/free margin, realized P&L, costs, peak equity, drawdown, open/closed positions,
rejections and lifecycle. Decimal precision34/HALF_EVEN; returns are detached JSON
values. No environment, network, MT5 or order dependency exists.

Opening recomputes capital eligibility and original source authenticity. The
atomic transaction records ENTRY_PENDING then ENTRY_REJECTED or
HYPOTHETICALLY_OPEN. Missing source/spec/cost/policy yields a detached BLOCKED
response without creating a position or changing the account. An active position
moves to MONITORING on eligible observations. Exit evidence records EXIT_PENDING
then HYPOTHETICALLY_CLOSED only after an eligible causal quote. State pairs in one
transaction share the final transaction's balance/equity; they are not separate
intratransaction equity observations.

Canonical position identity scopes account, setup, original source bindings,
capital and exit policy. Seen setups, entry/exit identity and terminal status
prevent duplicate fills or reopening. One open position only. Blocked failed
validation raises/returns a stable reason and leaves the transaction unchanged;
`block_observation(reason,as_of=...)` explicitly journals a quality exclusion.
An open position then becomes UNRESOLVED, with unknown equity/free margin, not a
fabricated mark or exit. Resource failures roll back all state, events and IDs.

`PaperExitPolicy` v1 explicitly selects E2 structural target, structural invalidation
(required) and opposing-structure exits. Targets and observation rules remain E2's
original frozen references. Wick contact is an observation available at candle
close, never an intrabar fill. Competing same-candle/unknown-order events stay
UNRESOLVED. The earliest observed enabled event is preserved, and the fill follows
its first-observed availability, never retrospectively its presumed occurrence.
Skipped E2 intervals, quote gaps, expiry without a reviewed fill policy and
margin-call/stop-out conditions become UNRESOLVED. There is no fake liquidation,
automatic reactivation, retroactive success or favorable event selection.

The structural invalidation threshold is distinct from an executable protective
stop. `proposed_protective_stop` and `protective_stop_fill` stay null. A structural
close can become known after the market moves through that level; the first later
eligible Bid/Ask determines the hypothetical fill. Gap-through/adverse-slippage
loss can exceed the original risk estimate. No intrabar protective-stop trigger
model or guaranteed fill at the level is claimed.

TP1 preserves E2's single frozen target. TP2/TP3 and partial exits are
NOT_IMPLEMENTED; no extra zones or subminimum fractional lots are invented.
Momentum deterioration, trailing and timer exit adapters are prepared in the
architecture, not implemented. There is no mandatory 50-second exit.

Marks use side-specific exit quotes and declared adverse exit slippage, exit fees
and elapsed financing. Entry fees affect balance once; exit fees and financing
are charged at close. Spread is already in side-specific prices. Original entry,
geometry, policy, source IDs and costs are frozen. Reported excursions are
**observed-quote-only gross excursions**, not complete continuous MFE/MAE. Gaps
are unresolved, not zero movement. Holding duration uses modeled receipt-time
fills; no seconds are inferred from M1 candle geometry.

Peak equity and maximum drawdown retain losses. Negative balance/equity from a
large gap is visible; EXHAUSTED accounts cannot automatically trade or replenish.
Explicit DEPOSIT/WITHDRAWAL events require unique references and no open position.
They do not erase loss/drawdown history; net return then becomes unavailable rather
than misrepresenting flows as performance. RESET is unsupported: create a distinct
research account/cohort if explicitly authorized; never reset the old journal.

## Journal, metrics and bounds

IAT_PAPER_JOURNAL_V1 contains IAT_PAPER_ACCOUNT_V1, UTC chained event records,
configuration/source bindings, reasons, synthetic status and safety invariants.
It freezes entry/exit evidence separately. Metrics distinguish opportunities,
qualified/capital-rejected setups, positions opened/closed, wins/losses/flats,
resolved/open/unresolved denominators and exclusions. Win rate uses resolved
closed positions only. Average win/loss, profit factor and expectancy are null
when their denominator is unavailable (profit factor null with no losses).
Equity curve values and max drawdown are accounting observations, not a strategy
performance claim. No historical metrics or analyst agreement is measured.

Default bounded limits: tape10,000 observations, ledger1,000 events and complete
canonical journal2,000,000 UTF-8 bytes. Constructor limits are frozen in reports;
no silent inventory eviction or resets. Exceeding event/byte caps leaves the prior
journal unchanged. `validate_paper_journal` compares with its current actual
producer; verify an old prefix by replaying that same prefix. Checksums are not
portable independent approval. There is no live/raw-data importer in this module.

## Reproduction (Windows 10, Python3.11)

Preserve local changes first. Use a fresh local branch name if this one exists.
No reset/clean/force checkout or merge is required:

```powershell
$iatRoot = 'E:\IAT2\IAT3-Live-Test'
git -C $iatRoot status --short
git -C $iatRoot fetch origin refs/heads/feat/iat-v3-paper-capital-v1
git -C $iatRoot switch --no-track -c local/iat-v3-e4-review FETCH_HEAD
git -C $iatRoot rev-parse HEAD
Set-Location $iatRoot
py -3.11 -m unittest discover -s tests -p 'test_risk_independent_review.py' -v
py -3.11 -m unittest discover -s tests -p 'test_paper*.py' -v
py -3.11 tests/paper_examples.py
py -3.11 tests/benchmark_paper_research.py
powershell.exe -NoProfile -File "$iatRoot\diagnostics\Start-IATLiveMarketView.ps1" -ValidateOnly
```

These commands do not connect the paper engine to MT5 or start B.2/B.3. Existing
requirements must already be installed. The dashboard panel is preparation only:
research starting capitalUSD50 is labeled as configuration, never actual balance;
all live paper balances, sizing, geometry, fills and performance remain NOT_RUN /
BLOCKED / PENDING. New visual/terminal validation requires operator evidence;
Windows CI is not proof of actual terminal success. Do not enable Algo/API trading.

## Validation and benchmark evidence

Twelve new E3 contract tests passed before E4 implementation; no verified critical,
high or medium E3 defect required correction. See independent review document.
New E4 tests cover long/short quotes/fills, chronology/freshness/session permissions,
forgeries, financial/spec/cost gaps, affordability, margin, source-bound gap losses,
ambiguity, limits, cash flows, replay/repeatability/prefix/future append and UI.
The initial64 E4 tests passed on Python3.11.9 (68.354s) and3.12.14 (60.495s).
A final independent-audit correction requires an explicit synthetic abstract
structure-to-quote mapping and preserves E3's unknown price basis; the65-test
focused suite and full suites are rerun after this change. Earlier in-progress
full runs were superseded, not counted as successful validation.
The12 E3 review tests also pass on each (2.058s /2.065s in the final rerun).
The inherited live-view suite passes36 tests including Node DOM isolation.
Exact completed full-suite/matrix results and head are recorded in the draft PR;
pending runs are not claimed successful. Actual PowerShell5.1 -File startup regression remains in Windows CI.
The CI job budget is explicitly40 minutes: the parent Windows3.11 attempt exhausted
25 minutes; its same-head retry passed. No market-data tolerance is widened and
no tests/checks are removed to meet a runner time budget.

Measured Linux3.11.9 tracing with prebuilt synthetic E1/E2/E3 (no context/ATR pair):
quote/fill0.502ms, capital arithmetic0.219ms, authenticated capital repeats
53.837/54.618/55.507ms (peak551,261 bytes), account opening60.758ms (548,418 bytes),
source-bound structural close55.420ms (558,484 bytes); complete example journal
11,513 bytes. Benchmark source creation is excluded; traced allocations are not
RSS or maximum-data throughput. This fixture omits optional authenticated context
and differs from E3's prior ATR benchmark, so it is not a claimed E3 speedup.
Numbers are synthetic component measurements, not Windows/MT5 latency or profit.
Run the benchmark to obtain new machine-specific timings.

## Remaining blockers and next milestone

External E3/E4 independent review; reviewed portable source bridge; legally
permitted same-feed native M1/M5 plus timestamped Bid/Ask, finalized/correction
coverage, dated sessions/holidays/maintenance, hashes/manifests, specifications,
fees/conversion/margin and independent qualification. Session/data-integrity
corrections remain a separate workstream; no assurance gate is bypassed.
Future historical replay needs warm-up/evaluation/out-of-sample separation,
predeclared matched cohorts and qualified observations. Keep private data private.

Next: independent review of this limited linear-USD synthetic account/fill model,
then separately versioned protective-stop and liquidation contracts with ambiguous
quote ordering/capture and currency/spec adapters. Do not activate live paper
research or compare historical profitability merely because toy accounting passes.

WAIT; execution_allowed=false; Exness BLOCKED; DATA_NOT_QUALIFIED;
historical_validation=PENDING; historical_comparisons=NOT_RUN. No real/demo orders,
credentials, account reads, broker/session approval, AI activation or PR merges.
