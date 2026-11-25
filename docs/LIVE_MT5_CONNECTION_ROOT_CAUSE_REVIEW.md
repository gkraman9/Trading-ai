# Live MT5 connection root-cause review

Parent: draft PR50, `5c9b965fe9fa3c6b50122f566620605d18e6aaae`.
The operator's Windows observations establish that an independent process could
attach while the dashboard could not. They do not establish that either process
used the same interpreter, package binary, terminal attachment or IPC state.
No actual Windows terminal was accessed in this cloud investigation.

## Confirmed source defects and controlled reproductions

The exact committed parent runner was loaded from its Git blob and executed with
an isolated synthetic SDK and mocked Flask server, without terminal/network access.
`initialize()` returned False. Startup nevertheless returned exit0, initialized
once only and proceeded to polling. Initialization/shutdown used the caller thread;
the terminal read used another thread (two distinct thread identities observed).
There was no explicit recovery attempt. This proves ignored initialization failure
and split ownership, NOT that MT5 requires same-thread operation.

A separate exact-parent provider reproduction returned terminal_info=None. The
report labeled PROVIDER_DISCONNECTED and both permission checks False despite
having no terminal information. These unknown checks are now null. Confirmed
unsafe settings and confirmed non-demo modes remain explicit safety blocks.

A controlled acquisition failure exposed another defect: get_candle_snapshot
wrapped an already typed IPC failure into generic PROVIDER_FAILURE. Existing
MarketDataError codes now propagate unchanged; other exceptions remain sanitized.
The new IPC regression failed before that correction and passes afterward.

## Corrected mechanisms, not a certified Windows diagnosis

One serialized worker now owns module loading, initialization, all data reads,
re-attachment and shutdown. Initialization False/exception captures numeric native
last_error immediately, before cleanup can overwrite it. Raw SDK messages are not
published. Retry scheduling is bounded, visible and interruptible between calls.
Re-attachment increments a generation and rechecks demo, disabled trading/API
permissions, XAUUSD visibility, fresh quotes and closed native M1/M5 bars. A fresh
acquisition is required before a recovered publication. Stop/start clears prior
analysis/cache state as well. HTTP threads only consume memory snapshots.

The old runner's weaknesses are corrected. Their contribution to the operator's
specific November25 failure remains UNVERIFIED until the local comparison is run.
Potential causes still include distinct interpreters/packages/terminals, unavailable
terminal information, IPC timeout, terminal restart and transient disconnection.
No evidence currently establishes an MT5 same-thread requirement. Default terminal
selection remains explicitly unverified; explicit selection is checked against the
reported terminal installation path and safely blocked when it cannot be verified.

## Evidence boundaries

No account identifiers, server labels, login state identifiers or credentials are
read or reported. The probe compares runtime versions, executable/package binary
hashes and an ephemeral keyed terminal-path comparison token; PowerShell removes
the token and reports only equality/unknown. No sensitive path is published. The
comparison is prospective: the operator must select the actual interpreters used;
it cannot authenticate the identity of an earlier running process automatically.

GAP_UNVERIFIED and session assurance are independent of connectivity. No calendar,
quote-age limit, candle count, strategy, paper-account gate or qualification approval
is changed. Recovered connectivity can legitimately reveal a data-quality failure.
