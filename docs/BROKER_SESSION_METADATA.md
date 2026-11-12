# Broker session metadata collection and uncertainty

The standard official **Python MetaTrader5 package normally exposes no symbol
trading-session schedule API**. `symbol_info` counters/trade modes are not a
weekly calendar. The collector does not invent such a method, infer broker hours
from prices, or assume that configured hours prove actual broker hours.

`iat.broker_sessions.compare_broker_sessions` supports two explicit sources:

1. A private local metadata JSON export passed with `--broker-metadata` (or the
   PowerShell `-BrokerMetadata` option).
2. An independently reviewed read-only adapter extension
   `iat_session_metadata(symbol, coverage_start_utc, coverage_end_utc)` returning
   the same JSON document structure. This hook is **not** claimed to be native
   to standard Python MT5. No third-party bridge is automatically downloaded,
   imported or enabled. Without either source, report WARN with
   `BROKER_SESSIONS_UNAVAILABLE`.

## Native weekly exporter

`diagnostics/Export-IATSymbolSessions.mq5` is reviewed local source using the
actual MQL5 `SymbolInfoSessionTrade` API. It is not an EA, has no OnTick strategy,
and has no order, login or execution-enable code. It requires a connected demo
terminal with Algo Trading disabled. It checks at most eight sessions per weekday
and stops on API errors, excessive sessions, non-minute boundaries or ambiguous
zero-duration/full-day output. It never prints raw symbol names or terminal data.

To use locally, open this source in MetaEditor under Scripts, review it, compile
it, and run it against the prepared demo terminal with trading disabled. Supply
the exact configured symbol and an independently confirmed **IANA timezone** in
the input dialog. The trading-session API supplies wall times, not an IANA zone;
the exporter does not guess one. If compilation/execution is unavailable or
requires trading permission, stop and retain metadata-unavailable WARN. Native
compilation/execution was not performed in cloud tests.

On successful collection it writes a uniquely named `iat-sessions-*.json` in the
terminal's MQL5 Files directory and prints only that generated basename. Do not
mistake an older file for this run. Copy the new file to a private local metadata
folder and pass its path to the runner. The exact symbol is present privately to
prevent cross-symbol comparison; it is omitted from the evidence report. No
account ID, server, password or token is exported. The Python reader is bounded
to 1 MiB, rejects duplicate keys/nonfinite values, and accepts UTF-8 with/without
BOM for native/Windows exports.

## Weekly protocol, version 1

All fields are required; unknown fields and wrong types are rejected. This shape
is illustrative only; no broker hours are bundled:

```json
{
  "version": 1,
  "kind": "WEEKLY",
  "symbol": "EXACT_LOCAL_CONFIGURED_SYMBOL",
  "collected_at_utc": "2026-11-12T10:30:00Z",
  "timezone": "INDEPENDENTLY_CONFIRMED_IANA_ZONE",
  "weekdays": {
    "mon": [], "tue": [], "wed": [], "thu": [],
    "fri": [], "sat": [], "sun": []
  }
}
```

Weekday arrays use the existing v1 `open`, `close`, `close_day_offset` window
schema. Multiple windows represent breaks; overnight closes have explicit day
offset 1. Collection time must not be in the future or older than 24 hours.
The exact symbol must match configuration. An absent/ambiguous timezone or
ambiguous/nonexistent DST boundary rejects metadata instead of shifting times.

Weekly baseline comparison removes configured holidays, overrides and closures
**from the baseline only**, then compares configured and observed baseline hours
on their common finite UTC coverage. This handles overnight sessions and known
IANA DST rules without treating a configured holiday as a weekly mismatch.
Different hours/breaks/timezone-converted intervals produce
`BROKER_SESSION_MISMATCH`/FAIL. Matching weekly hours produce WARN with
`BROKER_EXCEPTIONS_UNVERIFIED`: a weekly API cannot prove dated holidays,
emergency closures, future schedule changes or the operator-supplied timezone's
provenance. The report records the number of configured exception rules requiring
independent evidence; it never treats them as broker-confirmed automatically.

## Dated protocol for explicitly supported providers

An independently reviewed provider with actual dated metadata can return:

```json
{
  "version": 1,
  "kind": "DATED",
  "symbol": "EXACT_LOCAL_CONFIGURED_SYMBOL",
  "collected_at_utc": "2026-11-12T10:30:00Z",
  "coverage_start": "2026-11-09T00:00:00Z",
  "coverage_end": "2026-11-16T00:00:00Z",
  "complete": true,
  "windows": []
}
```

`windows` contains ordered, disjoint objects with aware `start`/`end` timestamps
for actual open intervals; values are normalized to UTC. Up to 4096 windows are
accepted. Complete coverage must enclose the configured coverage. Every omitted
covered time is explicitly closed, including holidays and emergencies; do not
set `complete=true` if the provider cannot establish that claim. Unknown/missing
coverage, wrong symbol, stale/future collection time, unknown fields, overlap,
unaligned/malformed intervals or incomplete attestation produce FAIL.

The native exporter above supplies **WEEKLY only**, not this dated protocol.
No standard MT5 feature or holiday-aware bridge is claimed to exist. Dated
metadata can yield scoped comparison MATCH/PASS if both intervals and all other
checks match, but neither syntactic validation nor a provider's completeness
assertion authenticates its origin. The report always sets
`independent_broker_certification=false`. Independently verify the source.

## Redacted comparison

Evidence contains scope, comparison state, window counts, mismatch interval
count, configured exception-rule count, metadata age and reason codes. It does
not include raw timezone labels, exact symbols, source text, schedule objects,
provider exceptions, account fields or server identifiers. Mismatch counts are
**unmatched session intervals**, not missing OHLC counts. Missing OHLC counts are
reported separately and remain null when quality cannot be established.
