"""Pure, fail-closed OHLC quality assessment with stable public diagnostics."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from iat.analysis import validate_candles
from iat.sessions import SessionValidationError, utc


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    message: str

    def to_dict(self):
        return {'code': self.code, 'severity': self.severity, 'message': self.message}


@dataclass(frozen=True)
class QualityReport:
    valid: bool
    diagnostics: tuple[Diagnostic, ...]

    def to_dict(self):
        return {'valid': self.valid, 'diagnostics': [item.to_dict() for item in self.diagnostics]}


def failed(code, message, severity='ERROR'):
    return QualityReport(False, (Diagnostic(code, severity, message),))


def assess_candles(rows, timeframe, now, *, session_calendar=None, request_time=None,
                   expected_count=None, max_delay_bars=2, observed_finality=None):
    """Assess normalized UTC OHLC rows. Reports the first blocking defect.

    Caller retains the original rows; this function never fills or reorders them.
    Calendar-free callers receive strict continuity checks, not session assurance.
    """
    try:
        now = utc(now)
        if request_time is not None and now < utc(request_time):
            return failed('CLOCK_MOVED_BACKWARD', 'UTC clock moved backwards during data request')
        if timeframe not in ('M1', 'M5'):
            return failed('TIMEFRAME_UNSUPPORTED', 'Only M1 and M5 are supported')
        duration = timedelta(seconds=60 if timeframe == 'M1' else 300)
        if type(max_delay_bars) is not int or max_delay_bars < 0:
            return failed('QUALITY_POLICY_INVALID', 'Freshness tolerance must be a nonnegative integer')
        if (expected_count is not None and len(rows) != expected_count) or len(rows) < 3:
            return failed('HISTORY_INCOMPLETE', 'Incomplete candle history')
        try:
            openings = [utc(datetime.fromisoformat(str(row['timestamp']).replace('Z', '+00:00')))
                        for row in rows]
        except (KeyError, TypeError, ValueError, OverflowError):
            return failed('TIMESTAMP_MALFORMED', 'Candle timestamps must be valid timezone-aware ISO timestamps')
        if len(set(openings)) != len(openings):
            return failed('TIMESTAMP_DUPLICATE', 'Duplicate candle timestamps')
        if any(b < a for a, b in zip(openings, openings[1:])):
            return failed('TIMESTAMP_OUT_OF_ORDER', 'Candle timestamps are out of order')
        if any(opened.timestamp() % duration.total_seconds() for opened in openings):
            return failed('TIMEFRAME_MISALIGNED', 'Candle open does not align with timeframe')
        try:
            validate_candles(rows)
        except (ValueError, TypeError, OverflowError):
            return failed('OHLC_MALFORMED', 'OHLC prices must be finite, positive and consistent')
        if any(opened > now - duration for opened in openings):
            return failed('BAR_UNCLOSED', 'An unclosed or future candle was returned')
        diagnostics = []
        if session_calendar is not None:
            try:
                options = {'observed_finality': observed_finality} if getattr(session_calendar, 'version', 1) == 2 else {}
                session_calendar.validate_history(openings, now, duration, max_delay_bars, **options)
            except SessionValidationError as exc:
                return failed(exc.code, str(exc), 'INFO' if exc.code == 'SESSION_CLOSED' else 'ERROR')
            if any(b - a != duration for a, b in zip(openings, openings[1:])):
                diagnostics.append(Diagnostic('SESSION_CLOSURE_SKIPPED', 'INFO',
                                               'History gaps match verified session closures'))
            missing = next(session_calendar.expected_opens(openings[-1] + duration,
                           now - duration + timedelta(microseconds=1), duration), None)
            if missing is not None:
                diagnostics.append(Diagnostic('RECENT_BARS_MISSING', 'WARNING',
                                               'Recent closed bars are missing within configured tolerance'))
        else:
            if any(b - a != duration for a, b in zip(openings, openings[1:])):
                return failed('GAP_UNVERIFIED', 'Missing candle or unverified market-session gap')
            if now - (openings[-1] + duration) > duration * max_delay_bars:
                return failed('DATA_STALE', 'MT5 candle history is stale')
            diagnostics.append(Diagnostic('SESSION_NOT_CHECKED', 'WARNING',
                                           'No session calendar supplied; only strict continuity was checked'))
        diagnostics.append(Diagnostic('DATA_VALID', 'INFO', 'Candle data passed configured validation checks'))
        return QualityReport(True, tuple(diagnostics))
    except Exception:
        # Unknown/malformed inputs never establish quality; avoid provider detail leaks.
        return failed('QUALITY_UNESTABLISHED', 'Data quality could not be established')


class ClockValidationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.report = failed(code, message)


class ClockGuard:
    """Detect backward UTC movement across requests within one serving process."""
    def __init__(self, source):
        from threading import Lock
        self.source = source
        self.previous = None
        self.lock = Lock()

    def __call__(self):
        with self.lock:
            try:
                now = utc(self.source())
            except Exception as exc:
                raise ClockValidationError('CLOCK_UNAVAILABLE', 'A trustworthy UTC clock is unavailable') from exc
            if self.previous is not None and now < self.previous:
                raise ClockValidationError('CLOCK_MOVED_BACKWARD', 'UTC clock moved backwards')
            self.previous = now
            return now
