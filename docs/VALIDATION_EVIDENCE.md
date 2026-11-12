# Redacted validation evidence, version 1

The diagnostic constructs a fresh report using a closed field set. Before
publication, `iat.evidence.validate_report` rejects schema drift, raw/free-form
strings, unknown explanations, nonfinite values, unsafe flags and incomplete
PASS outcomes. Diagnostic explanations come only from a fixed code vocabulary;
provider exception text is never copied. Reports never serialize terminal,
account, symbol or bridge objects or read account properties other than demo
`trade_mode`. Python provider stdout/stderr is suppressed; the Windows runner
also discards all child output, including possible native-library console data.

## Fields

| Field | Contents |
| --- | --- |
| `report_version`, `run_id` | Integer 1 and a random per-run UUID, unrelated to account identity. |
| `started_at_utc`, `finished_at_utc` | Aware UTC test times; null when a trustworthy clock is unavailable. |
| `status`, `diagnostics` | PASS/WARN/FAIL plus allowlisted code, severity and explanation. |
| `runtime` | Numeric Python and installed MT5 package version strings; no host/user/path/server metadata. |
| `symbol` | Fixed anonymous alias SYMBOL_1, requested generic XAUUSD scope, visibility, currency-metadata match and digits; no actual broker symbol/suffix. |
| `terminal` | Connectivity, confirmed demo mode, Algo Trading disabled and external API trading disabled booleans. |
| `calendar` | Metadata scope/comparison, window and exception-rule counts, metadata age, mismatch interval count, dated-exception coverage flag and reason codes. |
| `timeframes.M1`, `.M5` | Requested/validated counts, last closed bar open/close UTC, age, recent missing-bar count, unexpected/scheduled gap counts and quality codes. No raw OHLC prices. |
| `safety` | WAIT, execution_allowed=false, zero orders requested, no credentials/login requested, binding initialization and shutdown state, independent_broker_certification=false. |

Failure or unperformed count/freshness/gap fields are **null**, never invented
zeros. Zero unexpected gaps is emitted only after actual returned rows pass the
quality pipeline. Both timeframes are attempted independently after terminal
safety gates; one successful timeframe cannot hide another's failure.

## Outcome meanings

- PASS (exit 0): all scoped terminal, data and complete dated-comparison checks
  passed, version metadata is available, and shutdown succeeded. It is not proof
  of strategy validity or independent broker certification.
- WARN (exit 2): no blocking error, but unresolved uncertainty exists. Typical
  examples are unsupported schedule collection, weekly-only metadata, missing
  asset/version metadata, tolerated recent missing bars, or a known closed
  session where current validation must be rerun. WARN never permits execution.
- FAIL (exit 1): a blocking safety, config, terminal, provider, candle, calendar,
  clock, interruption, shutdown or report-publication problem occurred.

The existing two-bar freshness tolerance is retained; any tolerated missing
recent bars produce WARN. A confirmed session closure is distinguished from
missing in-session bars. Backward clock movement and stale/malformed data fail
closed. All explanations and codes are defined in `iat/evidence.py`; unknown
codes become `QUALITY_UNESTABLISHED`, never arbitrary provider strings.

The report describes this diagnostic's actions, not a full audit of other
programs/strategies running on the machine. It requires execution to be disabled
rather than changing terminal settings. The software never invokes login or
order APIs, never enables trading, and never requests/stores credentials.

## Atomic publication and failure guarantees

With `--report-path`, the target must be a **new** filename. Existing files are
refused before terminal access. A RUN_INCOMPLETE/FAIL report is reserved using
exclusive creation and flushed before the terminal is touched. After checks and
shutdown, the final allowlisted JSON is written to a same-directory temporary
file, flushed/fsynced, and atomically replaced into the reserved path.

A crash, interruption or final publication failure therefore leaves an explicit
incomplete failure (or invalid/incomplete JSON during initial reservation), not
an earlier successful result labeled as this run. Hidden temporary files are not
completed evidence and must not be shared as such. An existing filename is a
previous run, never a result of a refused invocation. The runner always chooses a
new UTC/UUID filename. Inspect run_id/timestamps and process exit status rather
than relying on a previous file. Filesystem durability/ACL behavior remains
subject to Windows and the chosen filesystem; use a private local directory.

Final publication happens **after** terminal shutdown. A shutdown error prevents
PASS. If publication fails, stdout contains only a fixed failure code; the
reserved report remains RUN_INCOMPLETE/FAIL. No PASS is printed first. The
PowerShell runner prints only a fixed status and generated basename, not raw
package/native logs, configuration contents or personal filesystem paths.

Runner failures before the Python diagnostic starts (wrong Python, missing file,
installation failure) use a small separate JSON envelope with
`scope=RUNNER_PREFLIGHT`, FAIL, a fixed code, UTC timestamp, WAIT and execution
false. It is atomically created at a unique filename and does not claim any
terminal checks occurred. If the filesystem itself cannot store a report, the
runner exits 1 with a fixed failure code and does not reuse another run's file.

## Evidence remaining to collect

Offline tests validate control flow, redaction and publication, not a broker.
Actual MT5 build behavior, native MQL5 exporter compilation, real published
sessions, DST conventions, holiday accuracy, OHLC comparisons and sparse/tick-free
minutes remain unverified until an authorized Windows demo operator runs the
package. The optional bridge's provenance/completeness claims are not signed or
automatically authenticated. A matching imported schedule is evidence to review,
not automatic acceptance of the configured calendar as authoritative.
