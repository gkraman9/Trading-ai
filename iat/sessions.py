"""Explicit broker session windows; no inferred hours or market-price generation."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class SessionValidationError(ValueError):
    """Session coverage is unknown, inconsistent, or currently closed."""
    def __init__(self, message, code="SESSION_INVALID"):
        super().__init__(message)
        self.code = code


def utc(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise SessionValidationError("Session times must be timezone-aware")
    return value.astimezone(timezone.utc)


def duration_seconds(duration):
    if not isinstance(duration, timedelta):
        raise SessionValidationError("Bar duration must be a positive whole number of seconds")
    seconds = duration.total_seconds()
    if seconds < 1 or not seconds.is_integer():
        raise SessionValidationError("Bar duration must be a positive whole number of seconds")
    return int(seconds)


@dataclass(frozen=True)
class SessionCalendar:
    """Authoritative, finite coverage for one exact broker symbol.

    Windows are half-open [start, end) UTC intervals. Within coverage, times
    outside windows are explicitly closed (including breaks and holidays).
    The host supplies independently verified broker windows, including DST.
    """
    symbol: str
    coverage_start: datetime
    coverage_end: datetime
    windows: tuple[tuple[datetime, datetime], ...]

    def __post_init__(self):
        start, end = utc(self.coverage_start), utc(self.coverage_end)
        if not isinstance(self.symbol, str) or not self.symbol.strip() or start >= end:
            raise SessionValidationError("Invalid session coverage")
        try:
            windows = tuple((utc(a), utc(b)) for a, b in self.windows)
        except (TypeError, ValueError) as exc:
            raise SessionValidationError("Each session window must contain two aware datetimes") from exc
        previous = start
        for a, b in windows:
            if a < previous or a < start or a >= b or b > end:
                raise SessionValidationError("Session windows must be ordered, disjoint and within coverage")
            previous = b
        object.__setattr__(self, "coverage_start", start)
        object.__setattr__(self, "coverage_end", end)
        object.__setattr__(self, "windows", windows)

    def validate_request(self, symbol, now, duration):
        now = utc(now)
        if symbol != self.symbol or not self.coverage_start <= now < self.coverage_end:
            raise SessionValidationError("Session calendar does not cover this symbol and time", "SESSION_COVERAGE_UNKNOWN")
        seconds = duration_seconds(duration)
        if any(boundary.timestamp() % seconds for window in self.windows for boundary in window):
            raise SessionValidationError("Session boundaries must align with the requested timeframe", "SESSION_ALIGNMENT_INVALID")
        if not any(a <= now < b for a, b in self.windows):
            raise SessionValidationError("Market session is closed", "SESSION_CLOSED")

    def expected_opens(self, start, end, duration):
        """Yield fully covered bar opens in [start, end), skipping confirmed closures."""
        seconds = duration_seconds(duration)
        start, end = utc(start), utc(end)
        for a, b in self.windows:
            cursor = max(start, a)
            remainder = cursor.timestamp() % seconds
            if remainder:
                cursor += timedelta(seconds=seconds - remainder)
            while cursor < end and cursor + duration <= b:
                yield cursor
                cursor += duration

    def validate_history(self, openings, now, duration, max_delay_bars):
        now = utc(now)
        self.validate_request(self.symbol, now, duration)
        if not isinstance(max_delay_bars, int) or isinstance(max_delay_bars, bool) or max_delay_bars < 0:
            raise SessionValidationError("max_delay_bars must be a nonnegative integer")
        try:
            openings = tuple(utc(opened) for opened in openings)
        except TypeError as exc:
            raise SessionValidationError("Candle openings must be an iterable of aware datetimes") from exc
        if not openings:
            raise SessionValidationError("Candle history must not be empty")
        if any(b <= a for a, b in zip(openings, openings[1:])):
            raise SessionValidationError("Candle openings must be chronological and unique")
        if any(opened > now - duration for opened in openings):
            raise SessionValidationError("Candle history contains an unclosed or future bar")
        if openings[0] < self.coverage_start:
            raise SessionValidationError("History extends outside verified session coverage", "SESSION_COVERAGE_UNKNOWN")
        expected = iter(self.expected_opens(openings[0], openings[-1] + duration, duration))
        for opened in openings:
            if next(expected, None) != opened:
                raise SessionValidationError("Missing candle or candle outside a market session",
                    "BAR_OUTSIDE_SESSION" if not any(a <= opened and opened + duration <= b
                                                    for a, b in self.windows) else "CANDLES_MISSING")
        if next(expected, None) is not None:
            raise SessionValidationError("Missing candle", "CANDLES_MISSING")
        # Count missing *closed market bars*, excluding scheduled closures and
        # the still-forming bar, rather than charging weekends as data delay.
        missing = self.expected_opens(openings[-1] + duration,
                                      now - duration + timedelta(microseconds=1), duration)
        for index, _ in enumerate(missing, 1):
            if index > max_delay_bars:
                raise SessionValidationError("MT5 candle history is stale", "DATA_STALE")
