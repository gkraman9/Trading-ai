"""Read-only MT5 candle provider. Importing this module never connects or trades."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from iat.analysis import validate_candles

TIMEFRAMES = {"M1": 60, "M5": 300}

class MarketDataError(RuntimeError):
    """Data unavailable, incomplete, stale, or inconsistent."""

def get_closed_candles(
    symbol: str = "XAUUSD",
    timeframe: str = "M1",
    count: int = 100,
    *,
    now: datetime | None = None,
    mt5: Any = None,
    max_delay_bars: int = 2,
) -> list[dict]:
    """Fetch fully closed bars only. MT5 terminal must already be initialized.

    MT5 timestamps are UTC epoch seconds and represent bar OPEN times.
    Position 0 is the forming bar and is deliberately never requested.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("A symbol is required")
    if not isinstance(timeframe, str) or timeframe not in TIMEFRAMES:
        raise ValueError("Supported timeframes: M1, M5")
    if not isinstance(count, int) or isinstance(count, bool) or count < 3 or count > 5000:
        raise ValueError("count must be an integer between 3 and 5000")
    if not isinstance(max_delay_bars, int) or isinstance(max_delay_bars, bool) or max_delay_bars < 0:
        raise ValueError("max_delay_bars must be a nonnegative integer")
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if mt5 is None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise MarketDataError("MetaTrader5 is not installed; use Windows MT5 terminal") from exc
    try:
        connected = mt5.terminal_info()
        if connected is None or not getattr(connected, "connected", False):
            raise MarketDataError("MT5 terminal is not connected")
        tf = getattr(mt5, "TIMEFRAME_" + timeframe)
        rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)
    except MarketDataError:
        raise
    except Exception as exc:
        raise MarketDataError("MT5 data request failed") from exc
    if rates is None or len(rates) != count:
        raise MarketDataError("Incomplete MT5 candle history")
    rows = []
    duration = timedelta(seconds=TIMEFRAMES[timeframe])
    for rate in rates:
        try:
            epoch = rate["time"]
            seconds = int(epoch)
            if isinstance(epoch, bool) or not isfinite(float(epoch)) or epoch != seconds:
                raise ValueError("Invalid epoch seconds")
            if seconds % TIMEFRAMES[timeframe]:
                raise ValueError("Bar open must align with timeframe")
            if any(isinstance(rate[key], bool) for key in ("open", "high", "low", "close")):
                raise ValueError("Boolean prices are invalid")
            opened = datetime.fromtimestamp(seconds, tz=timezone.utc)
            row = {"timestamp": opened.isoformat(), "open": float(rate["open"]),
                   "high": float(rate["high"]), "low": float(rate["low"]),
                   "close": float(rate["close"])}
        except (KeyError, IndexError, TypeError, ValueError, OverflowError, OSError) as exc:
            raise MarketDataError("Malformed MT5 candle") from exc
        if opened + duration > now:
            raise MarketDataError("MT5 returned an unclosed or future candle")
        rows.append(row)
    try:
        validate_candles(rows)
    except ValueError as exc:
        raise MarketDataError("MT5 candle validation failed") from exc
    last_open = datetime.fromisoformat(rows[-1]["timestamp"])
    if now - (last_open + duration) > duration * max_delay_bars:
        raise MarketDataError("MT5 candle history is stale")
    return rows
