"""Read-only MT5 candle provider. Importing this module never connects or trades."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Callable
from itertools import islice

from dataclasses import dataclass
from iat.quality import QualityReport, assess_candles, failed
from iat.sessions import SessionCalendar, SessionValidationError

TIMEFRAMES = {"M1": 60, "M5": 300}

class MarketDataError(RuntimeError):
    """Data unavailable, incomplete, stale, or inconsistent."""
    def __init__(self, message, code="PROVIDER_FAILURE", severity="ERROR", report=None):
        super().__init__(message)
        self.report = report if report is not None else failed(code, message, severity)
        self.code = self.report.diagnostics[0].code


@dataclass(frozen=True)
class CandleSnapshot:
    candles: list[dict]
    quality: QualityReport


def get_candle_snapshot(
    symbol: str = "XAUUSD",
    timeframe: str = "M1",
    count: int = 100,
    *,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    mt5: Any = None,
    max_delay_bars: int = 2,
    session_calendar: SessionCalendar | None = None,
) -> CandleSnapshot:
    """Fetch fully closed bars only. MT5 terminal must already be initialized.

    MT5 timestamps are UTC epoch seconds and represent bar OPEN times.
    Position 0 is the forming bar and is deliberately never requested.
    A running UTC clock is sampled before and after fetching. Explicit `now`
    preserves deterministic snapshot validation; do not combine it with clock.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("A symbol is required")
    if not isinstance(timeframe, str) or timeframe not in TIMEFRAMES:
        raise ValueError("Supported timeframes: M1, M5")
    if not isinstance(count, int) or isinstance(count, bool) or count < 3 or count > 5000:
        raise ValueError("count must be an integer between 3 and 5000")
    if not isinstance(max_delay_bars, int) or isinstance(max_delay_bars, bool) or max_delay_bars < 0:
        raise ValueError("max_delay_bars must be a nonnegative integer")
    if now is not None and clock is not None:
        raise ValueError("Supply either a snapshot now or a running clock")
    if clock is not None and not callable(clock):
        raise ValueError("clock must be callable")
    if now is not None:
        read_clock = lambda snapshot=now: snapshot
    else:
        read_clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def read_now():
        value = read_clock()
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return value.astimezone(timezone.utc)

    now = request_time = read_now()
    duration = timedelta(seconds=TIMEFRAMES[timeframe])
    if session_calendar is not None:
        try:
            session_calendar.validate_request(symbol, now, duration)
        except SessionValidationError as exc:
            raise MarketDataError(str(exc), exc.code, "INFO" if exc.code == "SESSION_CLOSED" else "ERROR") from exc
    if mt5 is None:
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise MarketDataError("MetaTrader5 is not installed; use Windows MT5 terminal", "PROVIDER_UNAVAILABLE") from exc
    try:
        connected = mt5.terminal_info()
        is_connected = connected is not None and getattr(connected, "connected", False)
    except Exception as exc:
        raise MarketDataError("MT5 data request failed") from exc
    if not is_connected:
        raise MarketDataError("MT5 terminal is not connected", "PROVIDER_DISCONNECTED")
    try:
        tf = getattr(mt5, "TIMEFRAME_" + timeframe)
        rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)
    except Exception as exc:
        raise MarketDataError("MT5 data request failed") from exc
    now = read_now()
    if now < request_time:
        raise MarketDataError("UTC clock moved backwards during data request", "CLOCK_MOVED_BACKWARD")
    if rates is None:
        raise MarketDataError("Incomplete MT5 candle history", "HISTORY_INCOMPLETE")
    try:
        if len(rates) != count:
            raise MarketDataError("Incomplete MT5 candle history", "HISTORY_INCOMPLETE")
        rates = list(islice(iter(rates), count + 1))
    except MarketDataError:
        raise
    except Exception as exc:
        raise MarketDataError("Malformed MT5 history container", "HISTORY_MALFORMED") from exc
    if len(rates) != count:
        raise MarketDataError("Incomplete MT5 candle history", "HISTORY_INCOMPLETE")
    rows = []
    for rate in rates:
        try:
            epoch = rate["time"]
            seconds = int(epoch)
            if isinstance(epoch, bool) or not isfinite(float(epoch)) or epoch != seconds:
                raise ValueError("Invalid epoch seconds")
            if seconds % TIMEFRAMES[timeframe]:
                raise MarketDataError("Bar open must align with timeframe", "TIMEFRAME_MISALIGNED")
            opened = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except MarketDataError:
            raise
        except Exception as exc:
            raise MarketDataError("Malformed MT5 timestamp", "TIMESTAMP_MALFORMED") from exc
        try:
            if any(isinstance(rate[key], bool) for key in ("open", "high", "low", "close")):
                raise ValueError("Boolean prices are invalid")
            row = {"timestamp": opened.isoformat(), "open": float(rate["open"]),
                   "high": float(rate["high"]), "low": float(rate["low"]),
                   "close": float(rate["close"])}
        except Exception as exc:
            raise MarketDataError("Malformed MT5 candle", "OHLC_MALFORMED") from exc
        rows.append(row)
    report = assess_candles(rows, timeframe, now, session_calendar=session_calendar,
                            request_time=request_time, expected_count=count,
                            max_delay_bars=max_delay_bars, observed_finality=True)
    if not report.valid:
        raise MarketDataError(report.diagnostics[0].message, report=report)
    return CandleSnapshot(rows, report)


def get_closed_candles(symbol="XAUUSD", timeframe="M1", count=100, **kwargs) -> list[dict]:
    """Compatibility interface returning only validated candles, with no fill or fallback."""
    return get_candle_snapshot(symbol, timeframe, count, **kwargs).candles
