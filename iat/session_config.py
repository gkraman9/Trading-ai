"""Strict v1 broker calendar configuration, compiled to existing UTC calendars."""
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from iat.sessions import SessionCalendar
from iat.calendar_assurance import source_holds

WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
MAX_BYTES = 1024 * 1024


class SessionConfigError(ValueError):
    def __init__(self, message, code='SESSION_CONFIG_INVALID'):
        super().__init__(message)
        self.code = code


def require(condition, message):
    if not condition:
        raise SessionConfigError(message)


def fields(value, required):
    require(isinstance(value, dict) and set(value) == set(required),
            'Configuration object has missing or unknown fields')


def day(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'Expected ISO date')
    return date.fromisoformat(value)


def minute(value):
    require(isinstance(value, str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value),
            'Expected HH:MM local time')
    return time.fromisoformat(value)


def local_utc(value, zone):
    """Reject nonexistent and ambiguous wall times instead of choosing a fold."""
    candidates = set()
    for fold in (0, 1):
        candidate = value.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(zone).replace(tzinfo=None) == value:
            candidates.add(candidate)
    if len(candidates) != 1:
        code = 'SESSION_TIME_AMBIGUOUS' if candidates else 'SESSION_TIME_NONEXISTENT'
        raise SessionConfigError('Session boundary is ambiguous or nonexistent in its IANA timezone', code)
    return candidates.pop()


def local_stamp(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', value),
            'Expected local YYYY-MM-DDTHH:MM timestamp')
    return datetime.fromisoformat(value)


def window_specs(value):
    require(isinstance(value, list) and len(value) <= 8, 'Expected at most eight daily session windows')
    for window in value:
        fields(window, ('open', 'close', 'close_day_offset'))
        opened, closed = minute(window['open']), minute(window['close'])
        offset = window['close_day_offset']
        require(type(offset) is int and offset in (0, 1), 'close_day_offset must be 0 or 1')
        require(offset == 1 or closed > opened, 'Session must have positive duration')
        require(offset == 0 or closed <= opened, 'Session duration cannot exceed one local day')
    return value


def subtract(windows, closures):
    for cut_start, cut_end in closures:
        remaining = []
        for start, end in windows:
            if cut_end <= start or cut_start >= end:
                remaining.append((start, end))
            else:
                if start < cut_start:
                    remaining.append((start, cut_start))
                if cut_end < end:
                    remaining.append((cut_end, end))
        windows = remaining
    return windows


def compile_session_config(config):
    """Validate all fields, then compile finite UTC windows; never infer hours."""
    try:
        if isinstance(config, dict) and type(config.get('version')) is int and config['version'] == 2:
            from iat.session_v2_config import compile_v2
            return compile_v2(config)
        return _compile(config)
    except SessionConfigError:
        raise
    except (ValueError, TypeError, OverflowError, ZoneInfoNotFoundError) as exc:
        raise SessionConfigError('Invalid broker session configuration') from exc


def _compile(config):
    fields(config, ('version', 'symbol', 'timezone', 'coverage', 'verification',
                    'weekdays', 'holidays', 'exceptions', 'closures'))
    require(type(config['version']) is int and config['version'] == 1, 'Only configuration version 1 is supported')
    symbol = config['symbol']
    require(isinstance(symbol, str) and 0 < len(symbol) <= 128 and
            not any(c.isspace() or ord(c) < 32 for c in symbol), 'Expected exact broker symbol')
    require(isinstance(config['timezone'], str) and bool(config['timezone']), 'Expected an IANA timezone')
    zone = ZoneInfo(config['timezone'])
    fields(config['coverage'], ('start', 'end'))
    start_day, end_day = day(config['coverage']['start']), day(config['coverage']['end'])
    require(0 < (end_day - start_day).days <= 366, 'Coverage must be between 1 and 366 local days')
    start = local_utc(datetime.combine(start_day, time()), zone)
    end = local_utc(datetime.combine(end_day, time()), zone)
    fields(config['verification'], ('source', 'verified_at'))
    source, verified_at = config['verification']['source'], config['verification']['verified_at']
    require(isinstance(source, str) and 0 < len(source.strip()) <= 512, 'Verification source is required')
    require(isinstance(verified_at, str) and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', verified_at),
        'Expected an explicit-offset ISO verification timestamp')
    stamp = datetime.fromisoformat(verified_at.replace('Z', '+00:00'))
    require(stamp.utcoffset() is not None, 'Verification timestamp must include an offset')
    fields(config['weekdays'], WEEKDAYS)
    weekly = {key: window_specs(config['weekdays'][key]) for key in WEEKDAYS}
    holidays = config['holidays']
    require(isinstance(holidays, list) and len(holidays) <= 366, 'Expected holiday date list')
    holiday_days = [day(value) for value in holidays]
    require(len(set(holiday_days)) == len(holiday_days), 'Duplicate holiday dates')
    exceptions = config['exceptions']
    require(isinstance(exceptions, dict) and len(exceptions) <= 366, 'Expected dated session exceptions')
    overrides = {day(key): window_specs(value) for key, value in exceptions.items()}
    require(not set(holiday_days) & set(overrides), 'Holiday and exception cannot specify the same date')
    require(all(start_day <= value < end_day for value in holiday_days + list(overrides)),
            'Holiday or exception outside coverage')
    closures = []
    require(isinstance(config['closures'], list) and len(config['closures']) <= 366, 'Expected closure list')
    for closure in config['closures']:
        fields(closure, ('start', 'end'))
        a = local_utc(local_stamp(closure['start']), zone)
        b = local_utc(local_stamp(closure['end']), zone)
        require(start <= a < b <= end, 'Closure must lie within coverage and have positive duration')
        closures.append((a, b))
    # Include the preceding start day to account for an overnight carry-in.
    windows = []
    current = start_day - timedelta(days=1)
    while current < end_day:
        specs = overrides.get(current, weekly[WEEKDAYS[current.weekday()]])
        for spec in specs:
            if current < start_day and spec['close_day_offset'] == 0:
                continue
            a = local_utc(datetime.combine(current, minute(spec['open'])), zone)
            b = local_utc(datetime.combine(current + timedelta(days=spec['close_day_offset']),
                                           minute(spec['close'])), zone)
            require(a < b, 'Session duration must remain positive after timezone conversion')
            if a < end and b > start:
                windows.append((max(a, start), min(b, end)))
        current += timedelta(days=1)
    windows.sort()
    require(all(a[1] <= b[0] for a, b in zip(windows, windows[1:])), 'Session windows overlap')
    for holiday in holiday_days:
        closures.append((local_utc(datetime.combine(holiday, time()), zone),
                         local_utc(datetime.combine(holiday + timedelta(days=1), time()), zone)))
    windows = subtract(windows, sorted(closures))
    # Merge adjacent windows so a civil-day split is not a false boundary.
    merged = []
    for a, b in windows:
        if merged and merged[-1][1] == a:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return SessionCalendar(symbol, start, end, tuple(merged), source_holds(source))


def reject_constant(_):
    raise SessionConfigError('Nonfinite JSON value')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON object key')
        result[key] = value
    return result


def load_session_bundle(path):
    """Read one non-secret JSON config; bound its size and reject duplicate keys."""
    try:
        with Path(path).open('rb') as handle:
            raw = handle.read(MAX_BYTES + 1)
        require(len(raw) <= MAX_BYTES, 'Session configuration exceeds 1 MiB')
        config = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object,
                            parse_constant=reject_constant)
        return config, compile_session_config(config)
    except SessionConfigError:
        raise
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise SessionConfigError('Session configuration could not be read or parsed') from exc


def load_session_config(path):
    """Compatibility loader returning the compiled UTC calendar alone."""
    return load_session_bundle(path)[1]
