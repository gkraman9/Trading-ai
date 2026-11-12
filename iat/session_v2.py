"""Generic second-level phases and quote-boundary classification; no execution."""
from dataclasses import dataclass
from bisect import bisect_right
from datetime import timedelta

from iat.sessions import SessionValidationError, utc, duration_seconds
from iat.calendar_assurance import ASSURANCE_MESSAGES

STATES = ('FULL_TRADING', 'CLOSE_ONLY', 'QUOTE_ONLY', 'CLOSED', 'UNKNOWN')
CLASSES = ('FULL_SESSION_BAR', 'PARTIAL_SESSION_OPEN', 'PARTIAL_SESSION_CLOSE',
           'CROSSES_SESSION_BREAK', 'OUTSIDE_SESSION', 'UNKNOWN_SESSION')
V2_MESSAGES = {
    'PARTIAL_SESSION_CANDLE': 'Partial-session candles are excluded from ordinary full-bar inputs.',
    'SESSION_PHASE_UNKNOWN': 'The session phase or its dated verification is unknown.',
    'CALENDAR_COVERAGE_UNVERIFIED': 'Calendar coverage has not been verified for this request.',
    'UNEXPECTED_MISSING_BARS': 'Expected ordinary full-session bars are missing.',
    'PHASE_CONFLICT': 'Quote availability and trading phases conflict or overlap.',
    'TIMEZONE_AMBIGUOUS': 'A local phase boundary has two possible UTC instants.',
    'TIMEZONE_NONEXISTENT': 'A local phase boundary has no UTC instant.',
    'CALENDAR_EXPIRED': 'Calendar verification has expired.',
    'CANDLE_FINALITY_UNCERTAIN': 'Broker candle finality is not established by verified evidence.',
    'BROKER_PHASE_RESTRICTED': 'Broker phase permissions restrict ordinary analysis inputs.',
}
PERMISSIONS = {'FULL_TRADING': (True, True), 'CLOSE_ONLY': (False, True),
               'QUOTE_ONLY': (False, False), 'CLOSED': (False, False), 'UNKNOWN': (None, None)}


def merge(windows):
    result = []
    for a, b in sorted(windows):
        if result and a <= result[-1][1]:
            result[-1] = (result[-1][0], max(b, result[-1][1]))
        else:
            result.append((a, b))
    return tuple(result)


@dataclass(frozen=True)
class Phase:
    start: object
    end: object
    state: str
    origin: str = 'WEEKLY'

    def __post_init__(self):
        a, b = utc(self.start), utc(self.end)
        if a >= b or self.state not in STATES or self.origin not in ('WEEKLY', 'EXCEPTION', 'HOLIDAY', 'MAINTENANCE', 'CLOSURE'):
            raise SessionValidationError('Invalid phase', 'PHASE_CONFLICT')
        object.__setattr__(self, 'start', a)
        object.__setattr__(self, 'end', b)


@dataclass(frozen=True)
class SessionCalendarV2:
    symbol: str
    coverage_start: object
    coverage_end: object
    expires_at: object
    windows: tuple
    phases: tuple[Phase, ...]
    assurance_codes: tuple[str, ...]
    provenance_kinds: tuple[str, ...]
    quote_schedule_verified: bool
    finality_verified: bool
    trade_schedule_verified: bool
    configuration_sha256: str
    provenance_count: int
    evidence_latest_at: object
    version: int = 2

    def __post_init__(self):
        start, end, expiry = utc(self.coverage_start), utc(self.coverage_end), utc(self.expires_at)
        if not isinstance(self.symbol, str) or not self.symbol or not start < end or expiry <= start:
            raise SessionValidationError('Invalid v2 coverage', 'CALENDAR_COVERAGE_UNVERIFIED')
        import re
        if not isinstance(self.configuration_sha256,str) or not re.fullmatch('[a-f0-9]{64}',self.configuration_sha256) or type(self.provenance_count) is not int or not 1<=self.provenance_count<=32:
            raise SessionValidationError('Invalid v2 provenance fingerprint','CALENDAR_COVERAGE_UNVERIFIED')
        if self.version != 2 or any(type(value) is not bool for value in (self.quote_schedule_verified,self.trade_schedule_verified,self.finality_verified)):
            raise SessionValidationError('Invalid v2 verification types','CALENDAR_COVERAGE_UNVERIFIED')
        if any(code not in set(V2_MESSAGES)|set(ASSURANCE_MESSAGES) for code in self.assurance_codes) or any(kind not in ('PUBLISHED','LOCAL_OBSERVATION','SYNTHETIC_TEST') for kind in self.provenance_kinds):
            raise SessionValidationError('Invalid v2 assurance metadata','CALENDAR_COVERAGE_UNVERIFIED')
        windows = tuple((utc(a), utc(b)) for a, b in self.windows)
        if any(a >= b or a < start or b > end for a, b in windows) or any(a[1] > b[0] for a, b in zip(windows, windows[1:])):
            raise SessionValidationError('Overlapping quote intervals', 'PHASE_CONFLICT')
        phases = tuple(self.phases)
        if any(p.start < start or p.end > end for p in phases) or any(a.end > b.start for a, b in zip(phases, phases[1:])):
            raise SessionValidationError('Overlapping trading phases', 'PHASE_CONFLICT')
        for phase in phases:
            overlap = sum((min(b, phase.end) - max(a, phase.start)).total_seconds()
                          for a, b in windows if a < phase.end and b > phase.start)
            if phase.state in ('FULL_TRADING', 'CLOSE_ONLY', 'QUOTE_ONLY') and overlap != (phase.end - phase.start).total_seconds():
                raise SessionValidationError('Quoted phase has no complete quote availability', 'PHASE_CONFLICT')
            if phase.state == 'CLOSED' and overlap:
                raise SessionValidationError('Closed phase contradicts quote availability', 'PHASE_CONFLICT')
        for key, value in (('coverage_start', start), ('coverage_end', end), ('expires_at', expiry), ('evidence_latest_at',utc(self.evidence_latest_at)),
                           ('windows', merge(windows)), ('phases', phases),
                           ('assurance_codes', tuple(self.assurance_codes)), ('provenance_kinds', tuple(self.provenance_kinds))):
            object.__setattr__(self, key, value)
        object.__setattr__(self, '_phase_starts', tuple(p.start for p in self.phases))
        object.__setattr__(self, '_quote_starts', tuple(a for a,b in self.windows))

    def phase_at(self, moment):
        moment = utc(moment)
        if not self.coverage_start <= moment < self.coverage_end:
            return 'UNKNOWN'
        index=bisect_right(self._phase_starts,moment)-1
        return self.phases[index].state if index>=0 and moment<self.phases[index].end else 'UNKNOWN'

    def permissions_at(self, moment):
        state = self.phase_at(moment)
        opened, closed = PERMISSIONS[state]
        trade_known = self.trade_schedule_verified and all(code == 'CANDLE_FINALITY_UNCERTAIN' for code in self.assurance_codes)
        quote_known = self.quote_schedule_verified and all(code in ('CANDLE_FINALITY_UNCERTAIN', 'SESSION_PHASE_UNKNOWN') for code in self.assurance_codes)
        if not trade_known:
            opened, closed = None, None
        quotes = any(a <= utc(moment) < b for a, b in self.windows) if quote_known and self.coverage_start <= utc(moment) < self.coverage_end else None
        return {'phase': state, 'market_data_expected': quotes, 'broker_open_positions': opened,
                'broker_close_positions': closed, 'broker_permissions_verified': trade_known and state != 'UNKNOWN',
                'iat_execution_allowed': False}

    def public_state(self, now):
        now = utc(now)
        codes = list(self.assurance_codes)
        if not self.coverage_start <= now < self.coverage_end or now < self.evidence_latest_at:
            codes.append('CALENDAR_COVERAGE_UNVERIFIED')
        if now >= self.expires_at:
            codes.append('CALENDAR_EXPIRED')
        permissions = self.permissions_at(now)
        if now >= self.expires_at or not self.coverage_start <= now < self.coverage_end or now < self.evidence_latest_at:
            permissions.update(phase='UNKNOWN', market_data_expected=None,
                               broker_open_positions=None, broker_close_positions=None,
                               broker_permissions_verified=False)
        return {'version': 2, 'configuration_sha256':self.configuration_sha256,'provenance_count':self.provenance_count, 'evaluated_at_utc': now.isoformat(), 'evidence_latest_at_utc':self.evidence_latest_at.isoformat(), 'coverage_start_utc': self.coverage_start.isoformat(),
                'coverage_end_utc': self.coverage_end.isoformat(), 'expires_at_utc': self.expires_at.isoformat(),
                'verification': 'BLOCKED' if codes else 'VERIFIED_DECLARATIONS',
                'reason_codes': list(dict.fromkeys(codes)), 'provenance_kinds': list(self.provenance_kinds),
                'permissions': permissions}

    def validate_request(self, symbol, now, duration):
        now = utc(now)
        if duration_seconds(duration) not in (60,300):
            raise SessionValidationError('Only M1/M5 intervals supported','TIMEFRAME_UNSUPPORTED')
        if now >= self.expires_at:
            raise SessionValidationError('Calendar verification expired', 'CALENDAR_EXPIRED')
        if symbol != self.symbol or not self.coverage_start <= now < self.coverage_end or now < self.evidence_latest_at:
            raise SessionValidationError('Unverified calendar coverage', 'CALENDAR_COVERAGE_UNVERIFIED')
        if self.assurance_codes:
            raise SessionValidationError('Mandatory calendar evidence is missing', self.assurance_codes[0])
        state = self.phase_at(now)
        if state == 'UNKNOWN':
            raise SessionValidationError('Current trading phase is unknown', 'SESSION_PHASE_UNKNOWN')
        if not any(a <= now < b for a, b in self.windows):
            raise SessionValidationError('Market session is closed', 'SESSION_CLOSED')
        # Informational broker permission never changes IAT execution permission.
        if state != 'FULL_TRADING':
            raise SessionValidationError('Current phase is restricted for ordinary analysis', 'BROKER_PHASE_RESTRICTED')

    def classify_bar(self, opened, timeframe, *, observed_finalized=None, research=False, as_of=None):
        opened = utc(opened)
        if timeframe not in ('M1', 'M5'):
            raise SessionValidationError('Unsupported candle timeframe', 'TIMEFRAME_UNSUPPORTED')
        duration = timedelta(minutes=1 if timeframe == 'M1' else 5)
        if opened.timestamp() % duration.total_seconds():
            raise SessionValidationError('Scheduled candle is misaligned', 'TIMEFRAME_MISALIGNED')
        end = opened + duration
        covered = self.coverage_start <= opened and end <= self.coverage_end
        quote_index=max(0,bisect_right(self._quote_starts,opened)-1)
        portions=[]
        for index in range(quote_index,len(self.windows)):
            a,b=self.windows[index]
            if a>=end:break
            if b>opened:portions.append((max(a,opened),min(b,end)))
        portions=merge(portions) if covered else ()
        phase_index=max(0,bisect_right(self._phase_starts,opened)-1)
        phases=[]
        for index in range(phase_index,len(self.phases)):
            phase=self.phases[index]
            if phase.start>=end:break
            if phase.end>opened:phases.append(phase)
        phase_seconds = sum((min(p.end, end) - max(p.start, opened)).total_seconds() for p in phases)
        phase_known = phase_seconds == duration.total_seconds() and all(p.state != 'UNKNOWN' for p in phases)
        verified = covered and all(code == 'CANDLE_FINALITY_UNCERTAIN' for code in self.assurance_codes) and self.quote_schedule_verified and phase_known
        if not covered or (not research and not verified):
            label = 'UNKNOWN_SESSION'
        elif not portions:
            label = 'OUTSIDE_SESSION'
        elif len(portions) == 1 and portions[0] == (opened, end):
            label = 'FULL_SESSION_BAR'
        elif len(portions) == 1 and portions[0][1] == end:
            label = 'PARTIAL_SESSION_OPEN'
        elif len(portions) == 1 and portions[0][0] == opened:
            label = 'PARTIAL_SESSION_CLOSE'
        else:
            label = 'CROSSES_SESSION_BREAK'
        def permission(index):
            values = [PERMISSIONS[p.state][index] for p in phases]
            return all(values) if phase_known and verified else None
        live_context = as_of is not None and self.evidence_latest_at <= utc(as_of) and self.coverage_start <= utc(as_of) < min(self.coverage_end,self.expires_at) and end <= utc(as_of) and self.phase_at(as_of) == 'FULL_TRADING'
        eligible = live_context and verified and label == 'FULL_SESSION_BAR' and all(p.state == 'FULL_TRADING' for p in phases) and observed_finalized is True and self.finality_verified
        return {'classification': label, 'scheduled_open_utc': opened.isoformat(), 'scheduled_end_utc': end.isoformat(),
                'market_open_portions': [{'start': a.isoformat(), 'end': b.isoformat()} for a, b in portions],
                'market_open_seconds': sum((b - a).total_seconds() for a, b in portions) if covered and (research or verified) else None,
                'schedule_verified': verified, 'phase_states': sorted(set(p.state for p in phases)) or ['UNKNOWN'],
                'broker_open_positions': permission(0), 'broker_close_positions': permission(1),
                'broker_finality': 'CONFIRMED_BY_DECLARED_PROVIDER_CONTRACT' if observed_finalized is True and self.finality_verified and label == 'FULL_SESSION_BAR' else 'UNESTABLISHED',
                'eligible_for_strategy': eligible, 'iat_execution_allowed': False}

    def expected_intervals(self, start, end, duration, *, full_only=False):
        """Yield scheduled grid intervals with quotes; never synthesize OHLC."""
        seconds = duration_seconds(duration)
        if seconds not in (60, 300):
            raise SessionValidationError('Only M1/M5 intervals supported', 'TIMEFRAME_UNSUPPORTED')
        start, end = max(utc(start), self.coverage_start), min(utc(end), self.coverage_end)
        seen = set()
        for a, b in self.windows:
            cursor = max(start, a - timedelta(seconds=a.timestamp() % seconds))
            remainder = cursor.timestamp() % seconds
            if remainder:
                cursor += timedelta(seconds=seconds - remainder)
            while cursor < end and cursor < b:
                if cursor not in seen and cursor + duration <= self.coverage_end:
                    seen.add(cursor)
                    if not full_only or self._ordinary_slot(cursor, duration):
                        yield cursor
                cursor += duration

    def _ordinary_slot(self, opened, duration):
        result = self.classify_bar(opened, 'M1' if duration.total_seconds() == 60 else 'M5', research=True)
        return result['classification'] == 'FULL_SESSION_BAR' and result['phase_states'] == ['FULL_TRADING']

    def expected_opens(self, start, end, duration):
        yield from self.expected_intervals(start, end, duration, full_only=True)

    def validate_history(self, openings, now, duration, max_delay_bars, *, observed_finality=None):
        self.validate_request(self.symbol, now, duration)
        if type(max_delay_bars) is not int or max_delay_bars < 0:
            raise SessionValidationError('Invalid freshness policy', 'QUALITY_POLICY_INVALID')
        openings = tuple(utc(value) for value in openings)
        if not openings or any(b <= a for a, b in zip(openings, openings[1:])):
            raise SessionValidationError('Invalid chronology', 'TIMESTAMP_OUT_OF_ORDER')
        timeframe = 'M1' if duration.total_seconds() == 60 else 'M5'
        for opened in openings:
            result = self.classify_bar(opened, timeframe, observed_finalized=observed_finality, as_of=now)
            if opened + duration > utc(now):
                raise SessionValidationError('An unclosed bar was returned', 'BAR_UNCLOSED')
            label = result['classification']
            if label == 'UNKNOWN_SESSION':
                raise SessionValidationError('Candle session phase is unknown', 'SESSION_PHASE_UNKNOWN')
            if label == 'OUTSIDE_SESSION':
                raise SessionValidationError('Candle lies outside a session', 'BAR_OUTSIDE_SESSION')
            if label != 'FULL_SESSION_BAR':
                raise SessionValidationError('Partial session candle rejected for ordinary input', 'PARTIAL_SESSION_CANDLE')
            if result['phase_states'] != ['FULL_TRADING']:
                raise SessionValidationError('Broker phase restricts ordinary input', 'BROKER_PHASE_RESTRICTED')
            if not result['eligible_for_strategy']:
                raise SessionValidationError('Broker candle finality cannot be established', 'CANDLE_FINALITY_UNCERTAIN')
        expected = iter(self.expected_opens(openings[0], openings[-1] + duration, duration))
        if any(next(expected, None) != opened for opened in openings) or next(expected, None) is not None:
            raise SessionValidationError('Unexpected missing full-session bars', 'UNEXPECTED_MISSING_BARS')
        missing = self.expected_opens(openings[-1] + duration, utc(now) - duration + timedelta(microseconds=1), duration)
        for count, _ in enumerate(missing, 1):
            if count > max_delay_bars:
                raise SessionValidationError('Candle data is stale', 'DATA_STALE')
