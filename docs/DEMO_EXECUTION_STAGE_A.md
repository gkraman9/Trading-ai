# Demo execution Stage A: blocked readiness and synthetic rehearsal

Base: PR #36, `ac4a4cb283af7c11a97e9d29fd5c680848d27be0`.
This is **Stage A only**, not an activated auto-trader. The original live runner,
Gemini/OpenAI, APIs, strategies and qualification/session gates are unchanged.

## Why broker activation is deliberately unavailable

Repository inspection finds two experimental strategies (M5 trend/M1 confirmation
and sweep/M1 structure change). Both are `EXPERIMENTAL_SYNTHETIC_ONLY`. Their
research qualifications are not executable BUY/SELL signals. There is no
independently qualified historical backtest with documented executable entry,
broker-side SL/TP, sizing, invalidation and execution-cost policy. Historical
validation remains PENDING and comparisons NOT_RUN. No strategy was selected,
new indicator proven, price fabricated or WAIT relabeled as an order signal.

An ordinary MT5 Python `account_info()` check followed by sending an order is not
an atomic account binding: the terminal/account can change between operations.
An order request has no account-bound destination that this repository has
independently validated. Claiming REAL execution is impossible while supplying
that unchecked transport would be misleading. **This build provides no MT5 order
adapter or order-send call at all.** Only an explicitly synthetic transport can
exercise the state machine. `--enable-demo-auto-execution` is a readiness request
that always returns BLOCKED. Configuration, caller approval booleans and broker
permission switches cannot unlock a missing adapter or validate a strategy.

There is another compatibility blocker: the existing read-only observer requires
Algo Trading OFF and external Python trading disabled. Enabling either on its
shared terminal causes the existing observer to withhold data. Those protections
remain intact. A future Stage-C deployment needs separately reviewed terminal,
account, data and process boundaries; do not “fix” this by weakening the observer.

## Implemented rehearsal architecture

The isolated `iat/demo_execution` package implements strict configuration,
versioned policy, private persistent state, synthetic signal admission, risk
checks, mocked broker precheck, durable submission intents, result verification,
reconciliation and emergency stop. It imports no Gemini/OpenAI/provider output
and receives no live terminal capability. The only accepted rehearsal signal
source is explicitly `SYNTHETIC_TEST_ONLY`. This label does not approve a real
strategy or live dataset. The only supplied execution behavior is in unit-test
mocks; no user-facing CLI generates BUY/SELL intents or simulates market profits.

Every public report retains signal WAIT, execution_allowed=false, orders_requested=0,
Exness BLOCKED, historical PENDING/NOT_RUN and profitability_tested=false.
`SIMULATED_OPEN`, `SIMULATED_CLOSED` and similar states refer solely to synthetic
transport records, never broker executions. The original READ_ONLY_SHADOW
intelligence contracts remain intact. New rehearsal reports have a distinct mode.

## Risk policy v1

All of these gates must pass in a synthetic cycle; production readiness remains
blocked independently:

- Explicit service opt-in AND enabled configuration; new state starts stopped.
- Explicit mode 0 DEMO; REAL (2), CONTEST (1), missing/ambiguous mode rejected.
- Matching private account fingerprint and expected broker/currency; no switches.
- Connected account, terminal and API permissions; XAUUSD visible/full trade mode.
- Independently verified **new-position** session permission, not just quotations
  or close-only availability; calendar identity, data quality and finality present.
- Eligible UTC M1/M5 closes at nominal boundaries with no unfinished/future/stale
  frame, a quote no older than two seconds and a signal no older than a minute.
  A real adapter must consume existing quality/session evidence, not fabricate
  the mock snapshot's proof booleans. There is currently no such adapter.
- Fixed 0.01 volume, one exposure or pending intent maximum, at most five unique
  daily opening intents/orders. No martingale, grid, averaging down or size change.
- Broker-provided precision, tick/point, volume min/max/step, minimum stop distance,
  FOK and GTC support. Unknown/unsupported specifications fail closed; raw MT5
  filling bitmasks are not assumed equivalent to order-filling enum values.
- Mandatory supplied SL/TP, on the correct sides, tick/digit aligned and outside
  minimum distance; configured maximum spread and permitted deviation in points.
- A broker-checked, account-currency stop-loss-and-cost bound fits the remaining
  daily budget; no invented tick value, contract size or commission assumption.

Spread/slippage tolerances in the default template are **zero**, not a verified
Exness recommendation. Currency USD is an example declaration that must match a
future verified account. Both are configuration declarations, never assurances.
No padding/rounding of invalid prices or silent substitution of order policies.

### Day and loss accounting

Days are UTC [00:00, next 00:00), not broker wall-clock dates. Starting equity
requires a complete, verified opening mark and full cost/cashflow history. Starting
midday cannot silently treat the current equity as midnight equity. The synthetic
snapshot contract requires:

`daily_net = realized_profit + commissions + swaps + fees + current_unrealized - opening_unrealized`

`current_equity = starting_equity + net_external_cashflows + daily_net`

Commissions, swaps and fees are signed ledger entries and must be included once;
accrued open-position costs must be covered by the verified mark/cost contract.
Deposits and withdrawals are cashflows, not profit and not a new loss allowance.
Unknown credit/correction categories, missing overnight marks, changed day-start
values or incomplete history block admission. The opening baseline is persisted
and cannot be revised to increase the budget. At a 1% loss (inclusive), the
persistent emergency stop latches even if equity subsequently recovers.
Projected stop loss/cost equal to the remaining budget also blocks a new intent.
A separate dated loss-latch event prevents a stop reset from bypassing the UTC-day
loss lock. A new UTC day still needs a verified new baseline and explicit stop reset.

Broker history and local reserved client IDs are unioned to count new opening
orders, including manual/external orders and unresolved submissions. Partial deals
of the same client ID count once. Rejected reserved submissions conservatively
consume a slot until the next UTC day. A real transport must provide a reliable
complete identity mapping; ordinary broker comments alone are not an established
idempotency guarantee. Pending/manual positions are never averaged into or
modified by this service.

A 1% **admission/latch rule is not a guarantee that market loss cannot exceed 1%**.
SLs can gap/slip and commission estimates can be wrong. Hard bounded-loss assurance
would need additional validated broker/instrument guarantees. There is no
performance, win-rate, expectancy or profit-factor claim in this milestone.

## Durable state, concurrency and uncertainty

Private SQLite transactions use BEGIN IMMEDIATE and synchronous FULL to serialize
admission across processes. A hash-chained audit and mirrored order records are
verified before admission. Configuration identity is bound to the ledger. The
service commits PREPARED and SUBMITTING before a possible mocked side effect.
Each intent records the synthetic strategy/rule/anchor/invalidation references and
qualification snapshot hash. Every audit event is marked SYNTHETIC_REHEARSAL_ONLY
with execution disabled and zero actual orders. Unique setup identity binds
account fingerprint, strategy/rule version, XAUUSD,
direction and canonical anchor IDs; changing a quote or SL does not re-arm a setup.
A different anchor/version/direction can form a distinct setup, still subject to
all limits. No window-relative event ID is substituted for canonical evidence.

Timeout/disconnection/uncertain result leaves UNKNOWN and a persistent stop;
there is **no automatic resend**. Startup reconciliation uses an exact client-ID
lookup. No match is not proof that an order never executed. OPEN/PARTIAL/UNKNOWN
and in-progress reservations prevent another admission. Known rejection and
verified close are explicit terminal states. Partial exposure is never topped up.
A full fill with bad protection/slippage is UNKNOWN, stopped and requires operator
reconciliation. Broker result changes contradicting an already-known fill are
rejected. A successful result is not returned until the result/audit commit succeeds.

Audit/disk/SQLite/corruption failures fail closed, without printing raw exceptions.
A committed unknown submission remains a restart barrier even if final auditing
fails. Persistent stop prevents new admissions; it does **not** cancel in-flight
requests, close positions, remove SL/TP or issue an emergency market order. The
provided build cannot issue any of those broker actions. Reset requires explicit
rehearsal acknowledgement and no unresolved exposure. Never delete the state to
bypass limits or uncertainty. Hash chains detect accidental corruption; they are
not signatures or protection against a malicious local administrator.

## Windows Stage-A deployment (no orders)

Stop only the old service you intend to update. Preserve local changes first.
Keep both trading permissions disabled. Run each command individually:

```powershell
Set-Location 'E:\IAT2\IAT2-Latest'
git status --short
git fetch origin refs/heads/feat/iat-v3-demo-execution-stage-a
$branch = 'local/iat-demo-stage-a-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
git switch --no-track -c $branch FETCH_HEAD
$private = 'E:\IAT2\IAT2-DemoStageA'
New-Item -ItemType Directory -Force -Path $private | Out-Null
$config = Join-Path $private 'disabled-config.json'
$state = Join-Path $private ('state-' + [Guid]::NewGuid().ToString('N'))
py -3.11 .\diagnostics\demo_execution.py --write-template $config
py -3.11 .\diagnostics\demo_execution.py --config $config --state-directory $state --initialize-state
```

Exit **3** / BLOCKED is the expected result, including when a template or stopped
state was created successfully. Config files and state are outside Git, never
silently overwritten. Use a private directory with an appropriate local user ACL.
Normal Stage-A commands use the standard library/project dependencies, no terminal
or credentials. An existing config is preserved; use a new filename if required.
Do not change its risk limits or enabled flag to attempt activation.

Optional read-only readiness inspection on Windows Python 3.11 with the existing
optional MT5 package and an already-open authorized demo terminal:

```powershell
py -3.11 .\diagnostics\demo_execution.py --config $config --inspect-demo-terminal
```

It attaches without login/password/server arguments; never switches an account,
selects a symbol automatically or changes trading permissions. It reports only
redacted demo/permission/symbol declarations and remains BLOCKED. Account identity
is unverified while the template fingerprint is empty. To obtain an opaque
fingerprint **locally only**, explicitly request it:

```powershell
py -3.11 .\diagnostics\demo_execution.py --inspect-demo-terminal --print-demo-fingerprint
```

Raw account number, server label, account name, credentials and balances are not
printed. No cloud terminal validation has occurred. Local metadata is not broker
certification. Private identity declarations must be reviewed before a future
Stage-B configuration; changing the current template cannot unlock this build.

### Emergency stop and activation refusal

```powershell
py -3.11 .\diagnostics\demo_execution.py --config $config --state-directory $state --emergency-stop
py -3.11 .\diagnostics\demo_execution.py --config $config --state-directory $state --reset-emergency-stop --acknowledge-rehearsal-only
py -3.11 .\diagnostics\demo_execution.py --config $config --enable-demo-auto-execution
```

Stop persists across restarts. Reset is available only for disabled rehearsal
configuration with no unresolved records and explicit acknowledgement; it does
not enable trading. The activation request always returns
ACTIVATION_REFUSED_STAGE_A_NO_BROKER_ADAPTER and zero requested orders.
Do not enable the terminal's trading permissions to “fix” this refusal.

## Remaining Stage B/C/D requirements

1. Independently qualified XAUUSD source/calendar/finality evidence and causal
   execution-cost backtests for an explicitly versioned entry/SL/TP/invalidation
   policy. Current experimental research qualifications are insufficient.
2. A verified Exness demo identity and dated new-position session permissions,
   current symbol constraints and actual complete history/cost/opening-equity marks.
3. A reviewed transport/protocol that can enforce account binding, one-position
   admission and idempotency at the actual execution boundary. A pre-send account
   check alone cannot establish the requested REAL-impossibility guarantee.
4. A separately reviewed terminal/process architecture compatible with the
   existing read-only permission requirements. No weakening of the current runner.
5. Controlled local demo pilot only after those gates pass and separate explicit
   operator activation, with broker-result/position verification and private audit.
6. Stage-D actual entries/exits/costs/spread/slippage/drawdown and outcome metrics
   only from such a pilot. These remain unmeasured; synthetic tests are not returns.

The code includes mocked BUY/SELL cycles, losses, limits, concurrency, restart,
rejection, partial execution and audit failure tests. These validate software
behavior only. No demo or real broker order was sent and no PR was merged.
