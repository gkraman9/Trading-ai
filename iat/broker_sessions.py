"""Optional read-only broker session metadata collection and bounded comparison.

The official Python MT5 package normally has no trading-session schedule API.
A reviewed local bridge may expose iat_session_metadata(symbol, start, end).
This extension is explicitly not assumed to exist in the standard package.
"""
from datetime import datetime, timezone

from iat.session_config import compile_session_config, subtract
from iat.sessions import SessionCalendar


UNSET = object()


class MetadataError(ValueError):
    pass


def require(condition):
    if not condition:
        raise MetadataError('Malformed or incomplete broker session metadata')


def aware(value):
    require(isinstance(value, str))
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.utcoffset() is not None)
    return result.astimezone(timezone.utc)


def difference(left, right):
    """Count disjoint unmatched intervals, not inferred missing OHLC bars."""
    return len(subtract(list(left), right)) + len(subtract(list(right), left))


def compare_broker_sessions(mt5, config, calendar, metadata_document=UNSET, *, now=None):
    """Collect optional metadata, reject unknown schema, return redacted summaries.

    DATED metadata must explicitly attest complete coverage, including closures.
    WEEKLY metadata can compare baseline hours but cannot verify holidays/DST
    exceptions; it always carries uncertainty even when baseline hours match.
    No raw bridge values, symbol strings, timezone labels or provider messages
    are included in this result.
    """
    summary = {'scope': 'UNAVAILABLE', 'comparison': 'UNAVAILABLE',
               'configured_window_count': len(calendar.windows), 'broker_window_count': None,
               'configured_exception_rules': sum(len(config.get(name, [])) for name in ('holidays', 'exceptions', 'closures', 'maintenance')),
               'metadata_age_seconds': None, 'mismatch_intervals': None, 'dated_exceptions_covered': False, 'codes': []}
    try:
        if metadata_document is UNSET:
            collect = getattr(mt5, 'iat_session_metadata', None)
            if not callable(collect):
                summary['codes'] = ['BROKER_SESSIONS_UNAVAILABLE']
                return summary
            metadata = collect(calendar.symbol, calendar.coverage_start, calendar.coverage_end)
        else:
            metadata = metadata_document
        if getattr(calendar, 'version', 1) == 2:
            from iat.broker_phases import compare_v2_metadata
            return compare_v2_metadata(metadata, config, calendar, summary, now)
        require(isinstance(metadata, dict) and type(metadata.get('version')) is int and metadata['version'] == 1)
        require(metadata.get('symbol') == calendar.symbol)
        collected = aware(metadata.get('collected_at_utc'))
        age = ((datetime.now(timezone.utc) if now is None else now) - collected).total_seconds()
        if not 0 <= age <= 86400:
            summary['codes'] = ['BROKER_METADATA_STALE']
            summary['comparison'] = 'INVALID'
            return summary
        summary['metadata_age_seconds'] = age
        kind = metadata.get('kind')
        require(kind in ('DATED', 'WEEKLY'))
        if kind == 'DATED':
            require(set(metadata) == {'version', 'kind', 'symbol', 'collected_at_utc', 'coverage_start', 'coverage_end', 'complete', 'windows'})
            require(metadata['complete'] is True)
            start, end = aware(metadata['coverage_start']), aware(metadata['coverage_end'])
            require(start <= calendar.coverage_start and end >= calendar.coverage_end)
            require(isinstance(metadata['windows'], list) and len(metadata['windows']) <= 4096)
            windows = []
            for window in metadata['windows']:
                require(isinstance(window, dict) and set(window) == {'start', 'end'})
                windows.append((aware(window['start']), aware(window['end'])))
            broker = SessionCalendar(calendar.symbol, start, end, tuple(windows))
            clipped = [(max(a, calendar.coverage_start), min(b, calendar.coverage_end))
                       for a, b in broker.windows if a < calendar.coverage_end and b > calendar.coverage_start]
            require(all(boundary.timestamp() % 60 == 0 for pair in clipped for boundary in pair))
            mismatch = difference(calendar.windows, clipped)
            summary.update(scope=kind, comparison='MISMATCH' if mismatch else 'MATCH',
                           broker_window_count=len(clipped), mismatch_intervals=mismatch,
                           dated_exceptions_covered=True,
                           codes=['BROKER_SESSION_MISMATCH'] if mismatch else ['BROKER_SESSIONS_MATCH'])
        else:
            require(set(metadata) == {'version', 'kind', 'symbol', 'collected_at_utc', 'timezone', 'weekdays'})
            # A timezone is mandatory in the bridge output; never assume server
            # wall times are UTC or share the configured calendar's timezone.
            baseline = dict(config, holidays=[], exceptions={}, closures=[])
            configured = compile_session_config(baseline)
            observed = compile_session_config(dict(baseline, timezone=metadata['timezone'],
                                                   weekdays=metadata['weekdays']))
            # Civil-day coverage in different zones can clip different edges.
            # Compare only their common UTC coverage, never invent edge hours.
            start = max(configured.coverage_start, observed.coverage_start)
            end = min(configured.coverage_end, observed.coverage_end)
            require(start < end)
            clip = lambda values: [(max(a, start), min(b, end)) for a, b in values if a < end and b > start]
            mismatch = difference(clip(configured.windows), clip(observed.windows))
            summary.update(scope=kind, comparison='MISMATCH' if mismatch else 'UNCERTAIN',
                           broker_window_count=len(observed.windows), mismatch_intervals=mismatch,
                           codes=(['BROKER_SESSION_MISMATCH'] if mismatch else ['BROKER_WEEKLY_MATCH']) +
                                 ['BROKER_EXCEPTIONS_UNVERIFIED'])
    except Exception:
        summary.update(comparison='INVALID', codes=['BROKER_METADATA_INVALID'])
    return summary
