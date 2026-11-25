# E4.6 verification record

Baseline: PR #49, e18f6c7c61b3caebef45085a74b2aa93ba7caded, 1,951 inherited tests.
New tests: 13 independent-contract review +46 protection/scenario regressions.
This is an automated technical review, not independent human approval.

## Local results (25 November 2026)

| Check | Python | Actual result |
|---|---|---|
| Untouched-parent independent review |3.11.9|12 run,10 pass,2 reproduced failures,15.608s|
| First two defects corrected |3.11.9|12 pass,15.831s|
| Source continuity reproduction |3.11.9|1 reproduced failure|
| Source continuity corrected, all review cases |3.11.9|13 pass,17.017s|
| V1 golden plus complete review after shared-hook extraction |3.11.9|14 pass,22.498s|
| Protection contracts/scenarios |3.11.9|46 pass,53.101s|
| Protection contracts/scenarios |3.12.14|46 pass,46.882s|
| Live availability rendering and source isolation |3.11.9|36 pass,9.337s|
| Complete discovery |3.11.9|2,010 pass,791.378s|
| Complete discovery |3.12.14|2,010 pass,667.692s|

Commands: `python -m unittest discover -s tests -v`, with focused patterns
`test_paper_protection_review.py`, `test_protection*.py`, `test_live_market_view.py`.
All tests use synthetic/mocked sources. Windows/Python3.11/3.12 and the actual
PowerShell5.1 startup result must be checked in this draft PR's Actions run;
local Linux success alone does not establish Windows success.

## Worked synthetic cases and repeatability

`config/examples/protection-v1.synthetic.json` is a compact reviewed projection of
14 independently invented source-bound scenarios A–N. The diagnostic regenerates
full reports (761,824 bytes as pretty JSON). Two complete outputs were identical:
`4db1653c4de538e7c98944feb5a8c5defc1287f971606861c5c9377861955a44`.
This is the canonical report SHA field, not a file-byte checksum. Report source,
configuration and journal hashes are frozen; there is no real dataset hash claim.

| Case | Actual synthetic result |
|---|---|
| A normal stop |USD50 ->49.5044, one protective exit|
| B gap through |USD50 ->47.9, one protective exit; loss exceeds estimate|
| C delayed fill |USD49.454 after first eligible delayed row|
| D missing fill |UNRESOLVED, no fill, unknown current loss|
| E margin warning |MONITORING, no liquidation, new entries restricted|
| F stop-out |USD49.811, one liquidation, margin released|
| G structural/stop conflict |UNRESOLVED, no arbitrary precedence|
| H different liquidation/stop latencies |UNRESOLVED|
| I negative balance; J exhaustion |USD-181.021 retained; one fill with both roles|
| K minimum volume |ENTRY_REJECTED, MINIMUM_LOT_EXCEEDS_RISK_BUDGET|
| L repeated losses |Two closed losses; next entry rejected by consecutive limit|
| M recovery |USD50.7244, prior loss and historical drawdown retained|
| N missing known row |UNRESOLVED, no fabricated fill|

Toy contract1/specifications around2100 permit end-to-end USD50 accounting. The
separate requested3500.15/3499.65/3498.90 example is only arithmetic: USD0.50
price risk, USD1.25 gross loss before additional charges. Neither is Exness data.

## Descriptive benchmark

Two full14-scenario generations including E1/E2/E3 fixture construction took
18.044s and17.889s on this Linux Python3.11.9 workspace, without allocation tracing.
One prebuilt-source protected open took0.0300s; one stop observation/settlement
under tracemalloc took0.0668s, with555,542 traced peak bytes; compact final journal
25,806 bytes. One thousand isolated margin calculations took0.0182s. These are
single-workspace measurements, not latency guarantees, MT5 benchmarks or strategy
profitability. Full prefix authentication has growing history cost; bounded
journals deliberately fail transactionally at configured resource limits.

## Compatibility and remaining work

Ordinary v1 serialized journal goldens remain unchanged. Corrected invalid causal
specifications, loss-day attribution and replacement histories are intentionally
rejected/fixed. Protected production is a separate v2 contract; v1 journal validators
reject it rather than silently reinterpret it. No strategy predicates, confluence
thresholds, Session Engine files or historical qualification flags change.

External human review remains pending. No real quote capture or qualified historical
adapter was run. Unknown structural OHLC basis is explicitly mapped only in the
invented model. Margin/specifications/costs/session flags are not verified broker
terms. Different-model event reconciliation is deliberately conservative. There is
no live paper bridge, TP2/3, partial/trailing/timer exit or new entry strategy.

Recommended milestone: independent v2 contract review, then design a manifest-gated
historical adapter with independently qualified complete quote evidence. Preserve
WAIT, execution_allowed=false, Exness BLOCKED, DATA_NOT_QUALIFIED, historical
validation PENDING and historical comparisons NOT_RUN.
