# IAT 2.0 Foundation – Phase 1

## Audit of existing main branch
- `main.py`: Flask GET /analyze endpoint calls decision and reasoning separately.
- `decision.py` and `reasoning.py`: hardcode [100,105,110]; therefore signals and explanations do not use live market data.
- `market_data.py`: Binance REST close-price adapter, not an MT5 XAUUSD provider.
- `trend.py`: simple three-close comparator; it cannot establish HH/HL or market structure.
- `requirements.txt`: Flask and requests only.

## New read-only module
`iat.analysis.analyze(symbol, timeframe, rows)` accepts caller-supplied, **closed** OHLC candles with timezone-aware ISO 8601 timestamps. It validates price ranges, finite positive prices, strict chronology and minimum history. It returns a short-term close trend and **WAIT** only; it does not claim a strategy edge or execute orders.

This module intentionally does not connect to MT5, fetch data, or replace the existing Flask endpoint. Future work must integrate a verified MT5 provider with a closed-candle guarantee and prevent the old hardcoded BUY/SELL endpoint from being used as a trading signal.

## Safety
- No order placement or broker credentials.
- READ_ONLY_SHADOW is the only supported mode.
- No strategy is approved for trading.
- Tests: `python -m unittest discover -s tests -v`.

## Next milestone
Add provider abstraction, MT5 Windows adapter, explicit data freshness/closed-bar checks, risk gates, and an endpoint migration plan. Keep existing production interfaces untouched until compatibility and safety tests pass.
