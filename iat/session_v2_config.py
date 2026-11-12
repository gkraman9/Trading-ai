"""Strict v2 config compiler. v1 parsing and minute semantics are unchanged."""
from datetime import datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from iat.session_config import fields, require, day, local_utc, SessionConfigError, WEEKDAYS
from iat.session_v2 import Phase, SessionCalendarV2, STATES
from iat.sessions import SessionValidationError

V2_HOLDS = ('CALENDAR_COVERAGE_UNVERIFIED', 'SESSION_PHASE_UNKNOWN', 'HOLIDAY_COVERAGE_UNKNOWN',
            'MAINTENANCE_COVERAGE_UNKNOWN', 'CANDLE_FINALITY_UNCERTAIN', 'CALENDAR_SCHEDULE_CONFLICT')
VERIFIED_FIELDS = ('quote_schedule_verified', 'trade_schedule_verified', 'holidays_verified', 'maintenance_verified')


def stamp(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})', value), 'Expected aware second-level timestamp')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.utcoffset() is not None, 'Timezone required')
    return result.astimezone(timezone.utc)


def wall(value):
    require(isinstance(value, str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d', value), 'Expected HH:MM:SS')
    return time.fromisoformat(value)


def convert(value, zone):
    try:
        return local_utc(value, zone)
    except SessionConfigError as exc:
        code = 'TIMEZONE_AMBIGUOUS' if exc.code == 'SESSION_TIME_AMBIGUOUS' else 'TIMEZONE_NONEXISTENT'
        raise SessionConfigError('Local phase boundary is not uniquely convertible to UTC', code) from exc


def specs(value):
    fields(value, ('quotes', 'phases'))
    for kind in ('quotes', 'phases'):
        require(isinstance(value[kind], list) and len(value[kind]) <= 32, 'At most 32 quote/phase intervals per start day')
        for spec in value[kind]:
            fields(spec, ('open', 'close', 'close_day_offset') + (('state',) if kind == 'phases' else ()))
            opened, closed = wall(spec['open']), wall(spec['close'])
            offset = spec['close_day_offset']
            require(type(offset) is int and offset in (0, 1), 'Explicit day offset required')
            require((offset == 0 and closed > opened) or (offset == 1 and closed <= opened), 'Duration must be positive and at most one local day')
            if kind == 'phases':
                require(spec['state'] in STATES, 'Unknown phase state')
    return value


def cut_quotes(values, a, b):
    result = []
    for x, y in values:
        if y <= a or x >= b:
            result.append((x, y))
        else:
            if x < a:
                result.append((x, a))
            if b < y:
                result.append((b, y))
    return result


def cut_phases(values, a, b):
    return [Phase(x, y, p.state, p.origin) for p in values for x, y in cut_quotes([(p.start, p.end)], a, b)]


def compile_v2(config):
    try:
        return _compile(config)
    except SessionConfigError:
        raise
    except SessionValidationError as exc:
        raise SessionConfigError(str(exc), exc.code) from exc
    except Exception as exc:
        raise SessionConfigError('Invalid v2 calendar', 'SESSION_CONFIG_INVALID') from exc


def _compile(config):
    fields(config, ('version', 'symbol', 'timezone', 'coverage', 'verification', 'candle_finality',
                    'weekdays', 'holidays', 'exceptions', 'maintenance', 'closures', 'assurance_holds'))
    require(type(config['version']) is int and config['version'] == 2, 'Only v2 is accepted here')
    require(isinstance(config['symbol'], str) and 0 < len(config['symbol']) <= 128 and
            not any(c.isspace() or ord(c) < 32 for c in config['symbol']), 'Exact symbol required')
    require(isinstance(config['timezone'], str), 'IANA zone required')
    zone = ZoneInfo(config['timezone'])
    fields(config['coverage'], ('start', 'end'))
    first, last = day(config['coverage']['start']), day(config['coverage']['end'])
    require(0 < (last - first).days <= 366, 'Coverage must be 1-366 local days')
    midnight = lambda date: convert(datetime.combine(date, time()), zone)
    start, end = midnight(first), midnight(last)
    verification = config['verification']
    fields(verification, VERIFIED_FIELDS + ('expires_at', 'provenance'))
    require(all(type(verification[key]) is bool for key in VERIFIED_FIELDS), 'Verification flags must be booleans')
    expiry = stamp(verification['expires_at'])
    require(start < expiry <= end, 'Explicit verification expiry must lie within coverage')
    provenance = verification['provenance']
    require(isinstance(provenance, list) and 0 < len(provenance) <= 32, 'Dated provenance required')
    ids, kinds = set(), []
    for source in provenance:
        fields(source, ('id', 'kind', 'reference', 'captured_at'))
        require(isinstance(source['id'], str) and re.fullmatch('[A-Za-z0-9_-]{1,64}', source['id']) and source['id'] not in ids, 'Unique provenance ID required')
        require(source['kind'] in ('PUBLISHED', 'LOCAL_OBSERVATION', 'SYNTHETIC_TEST'), 'Unsupported provenance kind')
        require(isinstance(source['reference'], str) and 0 < len(source['reference'].strip()) <= 1024, 'Provenance reference required')
        require(stamp(source['captured_at']) < expiry, 'Provenance cannot postdate expiry')
        ids.add(source['id'])
        kinds.append(source['kind'])
    fields(config['candle_finality'], ('policy', 'verified'))
    require(config['candle_finality']['policy'] == 'MT5_POSITION_1_ELAPSED' and type(config['candle_finality']['verified']) is bool, 'Explicit finality contract required')
    holds = config['assurance_holds']
    require(isinstance(holds, list) and len(holds) == len(set(holds)) and all(code in V2_HOLDS for code in holds), 'Unsupported assurance holds')
    holds = list(holds)
    for flag, code in zip(VERIFIED_FIELDS, ('CALENDAR_COVERAGE_UNVERIFIED', 'SESSION_PHASE_UNKNOWN', 'HOLIDAY_COVERAGE_UNKNOWN', 'MAINTENANCE_COVERAGE_UNKNOWN')):
        if not verification[flag] and code not in holds:
            holds.append(code)
    if not config['candle_finality']['verified'] and 'CANDLE_FINALITY_UNCERTAIN' not in holds:
        holds.append('CANDLE_FINALITY_UNCERTAIN')
    fields(config['weekdays'], WEEKDAYS)
    weekly = {key: specs(config['weekdays'][key]) for key in WEEKDAYS}
    holidays = config['holidays']
    require(isinstance(holidays, list) and len(holidays) <= 366, 'Holiday date list required')
    holiday_days = [day(value) for value in holidays]
    require(len(holiday_days) == len(set(holiday_days)), 'Duplicate holidays')
    require(isinstance(config['exceptions'], dict) and len(config['exceptions']) <= 366, 'Dated overrides required')
    overrides = {day(key): specs(value) for key, value in config['exceptions'].items()}
    require(not set(holiday_days) & set(overrides), 'Holiday/exception conflict')
    require(all(first <= date < last for date in holiday_days + list(overrides)), 'Override outside coverage')
    quotes, phases = [], []

    def expand(date, schedule, origin):
        q, p = [], []
        for kind in ('quotes', 'phases'):
            for spec in schedule[kind]:
                a = convert(datetime.combine(date, wall(spec['open'])), zone)
                b = convert(datetime.combine(date + timedelta(days=spec['close_day_offset']), wall(spec['close'])), zone)
                require(a < b, 'Phase duration must remain positive in UTC')
                if a < end and b > start:
                    a, b = max(a, start), min(b, end)
                    (q if kind == 'quotes' else p).append((a, b) if kind == 'quotes' else Phase(a, b, spec['state'], origin))
        q.sort()
        p.sort(key=lambda value: value.start)
        if any(a[1] > b[0] for a, b in zip(q, q[1:])) or any(a.end > b.start for a, b in zip(p, p[1:])):
            raise SessionConfigError('Contradictory overlapping definitions', 'PHASE_CONFLICT')
        return q, p

    current = first - timedelta(days=1)
    while current < last:
        schedule = weekly[WEEKDAYS[current.weekday()]]
        if current < first:
            schedule = {key: [item for item in schedule[key] if item['close_day_offset'] == 1] for key in schedule}
        q, p = expand(current, schedule, 'WEEKLY')
        quotes.extend(q)
        phases.extend(p)
        current += timedelta(days=1)
    # Reject base overlaps before overlays; defined overlay precedence is the
    # only permitted replacement, never ordering-dependent raw phase overlap.
    quotes.sort()
    phases.sort(key=lambda value: value.start)
    if any(a[1] > b[0] for a, b in zip(quotes, quotes[1:])) or any(a.end > b.start for a, b in zip(phases, phases[1:])):
        raise SessionConfigError('Weekly intervals overlap across dates', 'PHASE_CONFLICT')
    for date, schedule in sorted(overrides.items()):
        q, p = expand(date, schedule, 'EXCEPTION')
        cuts = [(midnight(date), midnight(date + timedelta(days=1)))] + q + [(v.start, v.end) for v in p]
        for a, b in cuts:
            quotes, phases = cut_quotes(quotes, a, b), cut_phases(phases, a, b)
        quotes.extend(q)
        phases.extend(p)
    for date in holiday_days:
        a, b = midnight(date), midnight(date + timedelta(days=1))
        quotes, phases = cut_quotes(quotes, a, b), cut_phases(phases, a, b)
        phases.append(Phase(a, b, 'CLOSED', 'HOLIDAY'))
    for kind in ('closures', 'maintenance'):
        require(isinstance(config[kind], list) and len(config[kind]) <= 366, 'Bounded closure intervals required')
        for cut in config[kind]:
            fields(cut, ('start', 'end'))
            def local(value):
                require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value), 'Local second-level timestamp required')
                return convert(datetime.fromisoformat(value), zone)
            a, b = local(cut['start']), local(cut['end'])
            require(start <= a < b <= end, 'Closure outside coverage')
            quotes, phases = cut_quotes(quotes, a, b), cut_phases(phases, a, b)
            phases.append(Phase(a, b, 'CLOSED', 'MAINTENANCE' if kind == 'maintenance' else 'CLOSURE'))
    phases.sort(key=lambda value: value.start)
    if verification['trade_schedule_verified']:
        cursor = start
        for phase in phases:
            if phase.start != cursor or phase.state == 'UNKNOWN':
                raise SessionConfigError('Verified trade phases have unknown coverage', 'SESSION_PHASE_UNKNOWN')
            cursor = phase.end
        if cursor != end:
            raise SessionConfigError('Verified phase coverage is incomplete', 'SESSION_PHASE_UNKNOWN')
    return SessionCalendarV2(config['symbol'], start, end, expiry, tuple(sorted(quotes)), tuple(phases),
                              tuple(holds), tuple(sorted(set(kinds))), verification['quote_schedule_verified'],
                              config['candle_finality']['verified'], verification['trade_schedule_verified'])
