# MT5 connection lifecycle v1

`iat.mt5_connection.MT5Connection` is a serialized read-only attachment facade used
by the existing LiveObserver. The standalone ReadOnlyMarketData API remains usable
for already initialized clients. No order/login/account-selection/permission-change
capability is exposed. The runner imports/attaches on the observer worker, never on
HTTP or startup request threads. Shutdown runs in that worker's finally block.

## Ownership, retry and shutdown

Initialization uses the existing10,000ms timeout and checks literal True. Optional
`--terminal-path` / PowerShell `-TerminalPath` is explicit local selection only; no
account, server, password, automatic login or permission argument is supplied.
The facade retains read callables and lifecycle callables, not the SDK module or
order capabilities. Cross-thread reads fail before a native call.

Failure captures a bounded signed integer last_error code immediately, before
shutdown/another native call. Exception text and SDK descriptions are never report
fields. Missing module/API capabilities, failed/exceptional initialize, missing
terminal info, disconnected terminal and recognized IPC error codes are distinct.
Cleanup precedes retries; failed native shutdown is separately reported with a sanitized code, never hidden as successful cleanup. Delays are2,4,8,16,32,60,60...seconds by default; repeated
attempts are unlimited in total but each delay and initialization timeout is capped.
The worker uses Event.wait, not busy polling, and can stop during backoff. Healthy
attachment with unavailable/invalid market data uses the normal polling interval,
not an expired retry timer. Only a complete fresh acquisition resets failure backoff.

All SDK operations use one owner. Start refuses a second live worker. Stop joins
for at most12seconds and never calls shutdown concurrently from the caller thread.
A subsequent start is refused while the old owner remains alive. A stopped observer
may restart; cache, previous scenario and publication state are cleared first.
Private journals remain append-only in the existing new-directory architecture.

## Native-call limitation

Python threads cannot cancel arbitrary blocking SDK/native reads. The SDK's
initialize timeout is supplied but cannot be independently enforced inside native
code. Calls over the existing10second acquisition budget expose NATIVE_CALL_OVERDUE;
HTTP returns no quote/analysis. Any returned late acquisition is rejected. HTTP and
close remain bounded; no competing thread is started or native shutdown forced.
An indefinitely blocked native call can leave the daemon owner alive until the
process exits. A killable subprocess transport is deferred, not represented as
implemented. Do not start overlapping dashboards to compensate for a stuck owner.
This limitation and actual Windows behavior require operator verification.

## Versioned additive diagnostics

Legacy snapshot versions and existing fields remain intact. Optional `connection`
and `runtime.connection` add connection_version1 with bounded allowlisted fields:
state/status_reason_code, owner_state, local attachment connected status,
last_successful_connection_utc, last_successful_acquisition_utc,
last_connection_failure_reason, numeric mt5_error_code, attempt count, next retry,
generation, demo/trading/API/symbol verification and numeric package/runtime labels.
Unknown safety checks are null, including missing or unsupported flag types.

States: INITIALIZING, CONNECTED, INITIALIZATION_FAILED, DISCONNECTED, RECONNECTING,
SAFETY_BLOCKED, MARKET_DATA_UNAVAILABLE, DATA_QUALITY_BLOCKED. Owner state separately
reports startup, serialized ownership, native activity/overdue and stopped. Generation
counts successful initialize calls, not qualified data. Connection/acquisition times
are different; terminal initialization alone never establishes acquisition success.
Last failure reason remains historical after recovery; current status is separate.
HTTP reads diagnostics from memory, including during initialization or failure.

Connection failure, generation change or overdue calls immediately withhold old
published observations. Acquisition and fresh-quote age budgets remain10s/30s for
this legacy observer (B.2's separate policy is untouched). Native position1 requests
remain500 M1 and100 M5. Both frames, causal context, M1/M5 comparison, existing
freshness/future checks and session gates remain required. Final safety checks
repeat after history acquisition and cannot publish a slow/stale recovery.

A healthy connection can yield descriptive unqualified observations while the
formal session context stays blocked. No connection state establishes broker
certification, qualified history, trade eligibility or execution permission.
AI remains opt-in, and no live strategy, E1/E2/E3/E4 or paper execution is activated.
All outputs retain READ_ONLY_SHADOW, WAIT, execution_allowed=false, Exness BLOCKED,
DATA_NOT_QUALIFIED, historical validation PENDING and comparisons NOT_RUN.
