# Broker session validation and gap detection

The runtime never invents broker hours, prices, missing candles, or trade signals.
The host must supply an independently verified session calendar for each exact
broker symbol to enable read-only HTTP analysis. Broker symbols, holidays, daily
maintenance, and DST vary; there is deliberately no built-in XAUUSD schedule.
No broker credentials or account API calls are needed by this calendar code.

## Configuration contract

`iat.sessions.SessionCalendar(symbol, coverage_start, coverage_end, windows)`
contains timezone-aware datetimes with finite coverage. Windows are ordered,
disjoint, half-open intervals `[open, close)`. They must lie inside coverage;
all other covered times are explicitly closed, including holidays. An empty
window list confirms the whole coverage period is closed. Unknown times outside
coverage are rejected, rather than inferred closed or open. The calendar is
immutable and normalizes supplied times to UTC; session boundary times must
align with the requested timeframe. Broker-local input must have the correct
UTC offset, including DST and any ambiguous local times resolved by the host.

Pass verified calendars to the app factory using exact symbol keys:

```python
from main import create_app
from iat.sessions import SessionCalendar

# These inputs come from an independently verified broker calendar, not OHLC
# inference. No example broker hours or account credentials are supplied here.
calendar = SessionCalendar(symbol, coverage_start, coverage_end, verified_windows)
app = create_app(mt5=already_initialized_readonly_adapter,
                 session_calendars={symbol: calendar})
```

Refresh/replace calendars before finite coverage expires. Reconstruct the app
with renewed coverage as part of the host's configuration lifecycle. Query
parameters cannot supply or override calendars, freshness tolerance, or safety
flags. The default `main.app` has no calendar and returns 503 for valid analysis
requests until a host supplies one. Import and health checks remain offline.

## Validation behavior

- Session validation happens before MT5 access. Closed, expired, wrong-symbol,
  unknown, or timeframe-incompatible coverage fails safely.
- All returned candles must be fully contained in open windows, closed by the
  request's UTC time, ordered, unique, and valid OHLC.
- Every expected bar between the first and last supplied candle must exist.
  Count alone cannot detect an internal hole; expected open times do. Confirmed
  scheduled closures are skipped. No interpolation, forward fill, or backfill
  synthesizes missing OHLC values.
- Freshness with a calendar counts expected closed bars after the last candle,
  excluding closures and the forming bar. The existing two-bar tolerance remains
  the default. At reopening, previous-session data is tolerated until more than
  two newly expected bars are missing; closed sessions themselves return 503.
- Without a calendar, direct provider callers retain wall-clock freshness checks
  and must supply uninterrupted history. Every gap is rejected as unverified.
  This compatibility mode does not claim broker-session validation and is not
  used by the HTTP endpoint.

Calendar coverage must span the returned history through the request time, so
100 M5 candles across a weekend may require several calendar days of coverage.
The calendar's authenticity and actual live data remain subject to independent
validation. This implementation validates consistency against supplied windows;
it does not prove the windows match the broker. Trading stays disabled.

## Tests and integration limits

Offline tests use clearly marked synthetic fixtures to exercise validator
behavior; fixtures are never runtime data sources. Tests cover internal gaps,
breaks, bars inside closures, M1/M5 alignment, weekends, holidays, DST conversion,
finite coverage, freshness boundaries, HTTP error handling and safety flags.
No live terminal, broker credentials, orders, or fabricated runtime market data
are involved. Live broker session/data validation remains unperformed.
