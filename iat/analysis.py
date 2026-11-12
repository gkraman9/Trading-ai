"""Deterministic, read-only market analysis from supplied CLOSED candles."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Mapping, Sequence

@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float

def validate_candles(rows: Sequence[Mapping]) -> list[Candle]:
    if len(rows) < 3:
        raise ValueError("At least three closed candles are required")
    result = []
    previous = None
    for row in rows:
        try:
            timestamp = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
            prices = [row[k] for k in ("open", "high", "low", "close")]
            if any(isinstance(value, bool) for value in prices):
                raise ValueError("Boolean prices are invalid")
            values = [float(value) for value in prices]
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Invalid candle fields") from exc
        if timestamp.tzinfo is None:
            raise ValueError("Timestamps must include a timezone")
        timestamp = timestamp.astimezone(timezone.utc)
        o, h, l, c = values
        if not all(isfinite(v) and v > 0 for v in values):
            raise ValueError("Prices must be finite and positive")
        if h < max(o, c, l) or l > min(o, c, h):
            raise ValueError("Invalid OHLC range")
        if previous is not None and timestamp <= previous:
            raise ValueError("Candles must be strictly chronological and unique")
        previous = timestamp
        result.append(Candle(timestamp, o, h, l, c))
    return result

def analyze(symbol: str, timeframe: str, rows: Sequence[Mapping]) -> dict:
    if not symbol or not timeframe:
        raise ValueError("Symbol and timeframe are required")
    candles = validate_candles(rows)
    closes = [c.close for c in candles]
    if closes[-1] > closes[-2] > closes[-3]:
        trend = "BULLISH"
    elif closes[-1] < closes[-2] < closes[-3]:
        trend = "BEARISH"
    else:
        trend = "RANGE"
    return {
        "symbol": symbol, "timeframe": timeframe, "market_state": trend,
        "signal": "WAIT", "execution_allowed": False, "mode": "READ_ONLY_SHADOW",
        "last_closed_candle": candles[-1].timestamp.isoformat(),
        "reasoning": [
            f"Last three closing prices indicate {trend.lower()} short-term movement.",
            "Three closes do not establish full market structure or a validated trading edge.",
            "Trade proposals are disabled until strategy and risk validation."
        ],
    }
