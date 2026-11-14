# Read-only market data quality

`get_candle_snapshot(...)` fetches actual MT5 closed OHLC bars and returns a
`CandleSnapshot(candles, quality)`. The existing `get_closed_candles(...)` API is
preserved and returns the validated list alone. `assess_candles(...)` is a pure
quality engine for normalized timestamp/OHLC rows; it never fills, reorders,
interpolates, or substitutes prices. HTTP analysis requires a session calendar.

The pipeline checks session coverage/open state before provider access, uses
position 1 to exclude the forming MT5 candle, checks the requested count, parses
UTC epoch seconds without truncation, and validates chronology, uniqueness,
timeframe alignment, finite positive OHLC and high/low ranges, closure, session
membership, internal completeness and freshness. Sessions are checked again at
the time sampled after fetching. Unexpected provider exceptions are sanitized.

Data quality is fail-fast: diagnostics identify the first blocking defect, not
an exhaustive audit of every defect in a rejected batch. No failure is repaired
with invented OHLC. The API always returns WAIT and execution_allowed=false.

## Structured response

Existing response fields and error statuses are preserved. The additive `quality`
field appears on successful analysis, invalid requests, and unavailable data:

```json
{
  "signal": "WAIT",
  "execution_allowed": false,
  "quality": {
    "valid": false,
    "diagnostics": [{
      "code": "CANDLES_MISSING",
      "severity": "ERROR",
      "message": "Missing candle or candle outside a market session"
    }]
  }
}
```

Messages describe validation, never broker secrets or raw provider exceptions.
Clients should branch on stable codes and `quality.valid`, not message wording
or severity alone. A confirmed closed session has INFO severity but valid=false
and HTTP 503. This is an expected closure, not permission to use old analysis.

| Codes | Meaning |
| --- | --- |
| `INVALID_REQUEST` | Missing, duplicate or unsupported query inputs (400). |
| `SESSION_CALENDAR_UNAVAILABLE` | No calendar for the exact requested symbol. |
| `SESSION_CONFIG_INVALID` | File unreadable, unsupported version, malformed schema or conflicting source. |
| `SESSION_TIME_AMBIGUOUS`, `SESSION_TIME_NONEXISTENT` | A local configuration boundary cannot be uniquely converted to UTC. |
| `SESSION_COVERAGE_UNKNOWN`, `SESSION_ALIGNMENT_INVALID`, `SESSION_INVALID` | Calendar cannot establish the requested history/session. |
| `SESSION_CLOSED` | Verified calendar says the current market session is closed (INFO). |
| `PROVIDER_UNAVAILABLE`, `PROVIDER_DISCONNECTED`, `PROVIDER_FAILURE` | MT5 package/connection/request unavailable. |
| `HISTORY_INCOMPLETE`, `HISTORY_MALFORMED` | Wrong count or malformed provider container. |
| `TIMESTAMP_MALFORMED`, `TIMESTAMP_DUPLICATE`, `TIMESTAMP_OUT_OF_ORDER` | Timestamp integrity failure. |
| `TIMEFRAME_MISALIGNED`, `BAR_UNCLOSED`, `BAR_OUTSIDE_SESSION` | Bar cannot belong to the requested closed session/interval. |
| `OHLC_MALFORMED` | Missing, nonfinite, nonpositive or inconsistent prices. |
| `CANDLES_MISSING`, `GAP_UNVERIFIED` | Missing in-session bars, or a gap without verified closure coverage. |
| `DATA_STALE` | Too many expected closed bars missing after the latest candle. |
| `CLOCK_MOVED_BACKWARD`, `CLOCK_UNAVAILABLE` | UTC regressed or could not be established. |
| `QUALITY_POLICY_INVALID`, `QUALITY_UNESTABLISHED` | Invalid assessment policy or unknown malformed assessment input. |
| `MARKET_DATA_UNAVAILABLE` | Generic HTTP fallback when an unexpected analysis failure prevents validation. |
| `SESSION_CLOSURE_SKIPPED` | History gaps match verified scheduled closures (INFO). |
| `RECENT_BARS_MISSING` | Missing recent bars are within the explicit two-bar tolerance (WARNING). |
| `SESSION_NOT_CHECKED` | Direct library compatibility call omitted its calendar (WARNING); never the HTTP path. |
| `DATA_VALID` | All configured checks passed (INFO). This does not validate a trading strategy. |

Provider/session failures keep the existing top-level HTTP error
`MARKET_DATA_UNAVAILABLE`; specific reasons live in quality.diagnostics. File
configuration failures expose their configuration code at both levels. Missing
and invalid data produce UNKNOWN market_state and null last_closed_candle.
`Cache-Control: no-store` remains set for `/analyze`.

## Closure and freshness policy

Within the first-to-last returned bar interval, every expected session bar must
exist. Verified breaks, weekends, holidays and exceptional closures are skipped;
a gap in a verified open interval is rejected. A candle inside a closure is
rejected. Bars are never inferred from a requested count alone.

Freshness counts expected **closed market bars** after the latest candle. The
preserved default tolerance is two bars; a tolerated lag emits a warning. At
reopening, previous-session data may therefore remain acceptable until more than
two newly closed bars are missing. Choose a stricter library policy (zero) for
consumers requiring the latest close; HTTP currently retains the existing
fixed two-bar policy and query parameters cannot weaken it. Trading is disabled
regardless of quality status.

A running UTC clock is checked before/after each fetch. The HTTP app also uses a
locked ClockGuard across requests within one process. Backward movement fails
closed until UTC catches up. This guard is not persisted or shared between
workers, and cannot prove clock synchronization against an external authority.
Direct library `now=` retains fixed-time replay/testing semantics; live callers
should use the default clock or `clock=`, not a frozen timestamp. `now` and clock
cannot be combined.

Direct legacy provider calls without a calendar preserve strict wall-clock
freshness and reject every internal gap. They explicitly warn that session
validation was omitted; they do not establish a verified broker session. The
HTTP path never accepts this compatibility mode.

## Validation evidence and remaining limits

The full offline suite passes **173 tests** on Python **3.11.18** and **3.12.14**.
CI repeats the suite on both 3.11 and 3.12 on Linux and Windows, including
PowerShell fail-closed preflight checks. Coverage includes v1 file parsing,
unknown/duplicate/missing fields, weekday/break/weekend/holiday/exception rules,
overnight carry-in, DST folds/gaps and M1/M5 continuity through both transitions,
provider errors, malformed OHLC, chronology, gaps, stale/forming/aligned bars,
slow fetches, clock movement within/across requests, HTTP compatibility and
mocked diagnostic demo-only lifecycle checks.

All fixtures are explicitly synthetic offline test inputs. No real terminal or
broker schedule was verified here. Broker configuration provenance is operator
metadata; independently verify it before use. MT5 data correctness relative to
the actual terminal, broker timestamp conventions and sparse/tick-free minutes
remain integration questions. There is no persistent quality history, signed
calendar provenance, distributed clock guard or trading strategy validation.

## Local evidence package

The [Windows runner](WINDOWS_DEMO_VALIDATION.md) adds demo-only safety gates and
[atomic redacted evidence](VALIDATION_EVIDENCE.md). Optional
[broker metadata comparison](BROKER_SESSION_METADATA.md) reports independent
source differences and uncertainty. The API and validated-list provider remain
unchanged. No real-terminal validation is claimed by these offline checks.

## Explicit Session Engine v2

The v1 contract remains unchanged. See [Session Engine v2](SESSION_ENGINE_V2.md)
for the opt-in seconds/phase model and [local research procedure](SESSION_V2_LOCAL_VALIDATION.md)
for blocked Exness evidence and Windows instructions.

## Market Intelligence v1

See [Phase 7 intelligence](MARKET_INTELLIGENCE_V1.md) for the additive
read-only research endpoint, causal swing/break definitions and offline replay.
Existing session/data-quality gates and execution restrictions remain enforced.
