"""Compare explicit phase-capable metadata; coarse weekly data cannot certify it."""
from datetime import datetime, timezone

from iat.session_config import compile_session_config
from iat.broker_sessions import aware, difference, require
from iat.session_v2 import merge, STATES


def compare_v2_metadata(metadata, config, calendar, summary, now):
    require(isinstance(metadata, dict) and type(metadata.get('version')) is int)
    require(metadata.get('symbol') == calendar.symbol)
    age = ((datetime.now(timezone.utc) if now is None else now) - aware(metadata.get('collected_at_utc'))).total_seconds()
    if not 0 <= age <= 86400:
        summary.update(comparison='INVALID', codes=['BROKER_METADATA_STALE'])
        return summary
    summary['metadata_age_seconds'] = age
    if metadata['version'] == 1:
        kind = metadata.get('kind')
        if kind == 'DATED':
            require(set(metadata) == {'version', 'kind', 'symbol', 'collected_at_utc', 'coverage_start', 'coverage_end', 'complete', 'windows'})
            require(metadata['complete'] is True)
            from iat.sessions import SessionCalendar
            require(isinstance(metadata['windows'], list) and len(metadata['windows']) <= 4096)
            windows = []
            for item in metadata['windows']:
                require(isinstance(item, dict) and set(item) == {'start', 'end'})
                windows.append((aware(item['start']), aware(item['end'])))
            broker = SessionCalendar(calendar.symbol, aware(metadata['coverage_start']), aware(metadata['coverage_end']), tuple(windows))
            require(broker.coverage_start <= calendar.coverage_start and broker.coverage_end >= calendar.coverage_end)
        elif kind == 'WEEKLY':
            require(set(metadata) == {'version', 'kind', 'symbol', 'collected_at_utc', 'timezone', 'weekdays'})
            coarse = {'version':1,'symbol':calendar.symbol,'timezone':metadata['timezone'],'coverage':config['coverage'],
                      'verification':{'source':'COARSE METADATA STRUCTURE ONLY','verified_at':metadata['collected_at_utc']},
                      'weekdays':metadata['weekdays'],'holidays':[],'exceptions':{},'closures':[]}
            broker = compile_session_config(coarse)
        else:
            raise ValueError('Unsupported coarse metadata')
        summary.update(scope=kind, comparison='UNCERTAIN', broker_window_count=len(broker.windows),
                       codes=['BROKER_PHASE_METADATA_UNVERIFIED', 'BROKER_EXCEPTIONS_UNVERIFIED'])
        return summary
    require(metadata['version'] == 2 and metadata.get('kind') == 'PHASES_V2')
    require(set(metadata) == {'version', 'kind', 'symbol', 'collected_at_utc', 'calendar'})
    broker = compile_session_config(metadata['calendar'])
    require(getattr(broker, 'version', 1) == 2 and broker.symbol == calendar.symbol)
    require(not set(broker.assurance_codes) - {'CANDLE_FINALITY_UNCERTAIN'})
    require(broker.coverage_start <= calendar.coverage_start and broker.coverage_end >= calendar.coverage_end)
    require(aware(metadata['collected_at_utc']) < broker.expires_at)
    require((datetime.now(timezone.utc) if now is None else now) < broker.expires_at)
    clip = lambda windows: [(max(a, calendar.coverage_start), min(b, calendar.coverage_end))
                            for a, b in windows if a < calendar.coverage_end and b > calendar.coverage_start]
    count = difference(merge(calendar.windows), merge(clip(broker.windows)))
    for state in STATES:
        left = merge((p.start, p.end) for p in calendar.phases if p.state == state)
        right = merge(clip([(p.start, p.end) for p in broker.phases if p.state == state]))
        count += difference(left, right)
    summary.update(scope='PHASES_V2', comparison='MISMATCH' if count else 'MATCH',
                   broker_window_count=len(broker.windows), mismatch_intervals=count,
                   dated_exceptions_covered=True,
                   codes=['BROKER_SESSION_MISMATCH'] if count else ['BROKER_SESSIONS_MATCH'])
    return summary
