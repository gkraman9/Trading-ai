# IAT 2.0 Foundation – Phase 1

## Historical audit of the original main branch
- `main.py`: Flask GET /analyze endpoint calls decision and reasoning separately.
- `decision.py` and `reasoning.py`: hardcode [100,105,110]; therefore signals and explanations do not use live market data.
- `market_data.py`: Binance REST close-price adapter, not an MT5 XAUUSD provider.
- `trend.py`: simple three-close comparator; it cannot establish HH/HL or market structure.
- `requirements.txt`: Flask and requests only.

## New read-only module
`iat.analysis.analyze(symbol, timeframe, rows)` accepts caller-supplied, **closed** OHLC candles with timezone-aware ISO 8601 timestamps. It validates price ranges, finite positive prices, strict chronology and minimum history. It returns a short-term close trend and **WAIT** only; it does not claim a strategy edge or execute orders.

This module accepts supplied candles and never connects to MT5 itself. The development branch now integrates the MT5 closed-candle provider into `/analyze`, removes fabricated legacy signals, and keeps execution disabled. See [API contract](READ_ONLY_API.md).

## Safety
- No order placement or broker credentials.
- READ_ONLY_SHADOW is the only supported mode.
- No strategy is approved for trading.
- Tests: `python -m unittest discover -s tests -v`.

## Next milestone
Independently validate data quality, market-session and gap handling, and trading logic. No strategy or execution path is enabled by the read-only endpoint migration.
