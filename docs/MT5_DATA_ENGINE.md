# IAT 2.0 — MT5 Data Engine (read-only)

This module fetches only completed MT5 bars, validates UTC timestamps, strict chronology, timeframe-aligned integer epoch seconds and OHLC integrity, and rejects stale or incomplete history.

## Requirements
- Windows PC with MetaTrader 5 terminal installed and connected to a demo account
- Python 3.11 and optional `MetaTrader5` Python package installed locally
- Broker-specific symbol name, e.g. `XAUUSD` or `XAUUSDm`

The package is **not installed by CI**: tests use an injected fake provider and run offline.

## Example (Windows, demo, already connected terminal)
```python
import MetaTrader5 as mt5
from iat.mt5_data import get_closed_candles
from iat.analysis import analyze

if not mt5.initialize():
    raise RuntimeError("MT5 initialization failed")
try:
    candles = get_closed_candles(symbol="XAUUSD", timeframe="M1", count=100, mt5=mt5)
    result = analyze("XAUUSD", "M1", candles)
    print(result)  # signal is always WAIT; execution_allowed is False
finally:
    mt5.shutdown()
```

## Safety boundaries
- The provider **never** initializes a terminal, authenticates, or sends orders.
- Position 0 (the forming candle) is excluded.
- Returned bars are checked for closure using UTC clock time.
- Stale, malformed, duplicate, missing or out-of-order data raises an error.
- Trading decisions remain WAIT and execution is disabled.
- `/analyze` now uses this validator and always returns WAIT with execution disabled; see [API contract](READ_ONLY_API.md).
- Optional `session_calendar` validates explicit broker windows and detects missing bars across open sessions; see [session configuration](MARKET_SESSIONS.md).
- Without a calendar, the provider preserves the existing strict wall-clock freshness policy and now rejects every internal gap; it never assumes a hole is a scheduled closure. The HTTP endpoint requires a calendar.
- Next: independently verify actual broker session inputs, symbol metadata and broker clock alignment.

## Configured quality pipeline

`get_candle_snapshot(...)` adds structured diagnostics while
`get_closed_candles(...)` preserves the validated-list interface. See
[session configuration](SESSION_CONFIGURATION.md), [quality rules](DATA_QUALITY.md),
and [Windows demo validation](WINDOWS_DEMO_VALIDATION.md). No live broker
validation is claimed by the offline tests.
