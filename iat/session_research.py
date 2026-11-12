"""Research-only timestamp comparison. No ordinary strategy inputs are emitted."""
from datetime import datetime, timedelta, timezone
import math
from uuid import uuid4

from iat.evidence import diagnostic, outcome, MESSAGES, validate_session_summary
from iat.session_v2 import CLASSES, STATES
from iat.sessions import utc, SessionValidationError

ORIGINS = ('CONFIG_ONLY', 'FILE_UNVERIFIED', 'SYNTHETIC_TEST', 'LOCAL_DEMO_OBSERVATION')


def new_research_report(calendar, now, origin='CONFIG_ONLY'):
    if origin not in ORIGINS:
        raise ValueError('Unknown research origin')
    return {'report_version':1, 'kind':'SESSION_V2_RESEARCH', 'run_id':str(uuid4()), 'status':'FAIL',
            'as_of_utc':utc(now).isoformat(), 'session_v2':calendar.public_state(now),
            'provenance':{'origin':origin, 'source_kinds':list(calendar.provenance_kinds),
                          'terminal_capture_attempted':False, 'independent_broker_certification':False},
            'phase_counts':{state:sum(p.state == state for p in calendar.phases) for state in STATES},
            'frames':{tf:{'observed_count':0,'full_count':0,'partial_count':0,'outside_count':0,
                          'unknown_count':0,'restricted_count':0,'finality_uncertain_count':0,
                          'missing_full_count':None,'missing_partial_count':None,
                          'classifications':{label:0 for label in CLASSES}, 'boundary_samples':[], 'codes':[]}
                      for tf in ('M1','M5')},
            'broker_comparison':{'scope':'UNAVAILABLE','comparison':'UNAVAILABLE','mismatch_intervals':None,
                                 'codes':['BROKER_SESSIONS_UNAVAILABLE']},
            'requirements':list(calendar.public_state(now)['reason_codes']),
            'diagnostics':[diagnostic('RUN_INCOMPLETE')],
            'safety':{'signal':'WAIT','execution_allowed':False,'ordinary_strategy_inputs_emitted':False,
                      'orders_requested':0,'credentials_requested':False}}


def research_report(calendar, now, observations=None, *, origin='CONFIG_ONLY', broker_comparison=None,
                    demo_codes=(), terminal_capture_attempted=False):
    report = new_research_report(calendar, now, origin)
    now = utc(now)
    report['provenance']['terminal_capture_attempted'] = terminal_capture_attempted
    codes = list(report['requirements'])
    if origin == 'FILE_UNVERIFIED': codes.append('FILE_OBSERVATIONS_UNVERIFIED')
    if origin == 'SYNTHETIC_TEST' or 'SYNTHETIC_TEST' in calendar.provenance_kinds: codes.append('SYNTHETIC_EVIDENCE')
    if broker_comparison is not None:
        report['broker_comparison'] = {key:broker_comparison[key] for key in report['broker_comparison']}
    codes.extend(report['broker_comparison']['codes'])
    codes.extend(diagnostic(code)['code'] for code in demo_codes)
    observations = {} if observations is None else observations
    if not isinstance(observations, dict) or set(observations) - {'M1','M5'}:
        codes.append('OBSERVATIONS_MALFORMED')
        observations = {}
    for timeframe in ('M1','M5'):
        entry = report['frames'][timeframe]
        rows = observations.get(timeframe, [])
        if not isinstance(rows, list) or len(rows) > 5000:
            entry['codes'].append('OBSERVATIONS_MALFORMED');codes.append('OBSERVATIONS_MALFORMED');continue
        opened = []
        duration = timedelta(minutes=1 if timeframe == 'M1' else 5)
        for row in rows:
            try:
                if not isinstance(row,dict) or set(row) != {'timestamp','finalized'} or type(row['finalized']) not in (bool,type(None)) or not isinstance(row['timestamp'],str):
                    raise ValueError('Invalid observation')
                stamp = utc(datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')))
                if opened and stamp == opened[-1] or stamp in opened:
                    entry['codes'].append('TIMESTAMP_DUPLICATE')
                if opened and stamp < opened[-1]:
                    entry['codes'].append('TIMESTAMP_OUT_OF_ORDER')
                opened.append(stamp)
                if stamp + duration > now:
                    entry['codes'].append('BAR_UNCLOSED')
                item = calendar.classify_bar(stamp,timeframe,observed_finalized=row['finalized'],research=True)
                label = item['classification']
                entry['observed_count'] += 1
                entry['classifications'][label] += 1
                entry['full_count'] += label == 'FULL_SESSION_BAR'
                entry['partial_count'] += label.startswith('PARTIAL_') or label == 'CROSSES_SESSION_BREAK'
                entry['outside_count'] += label == 'OUTSIDE_SESSION'
                entry['unknown_count'] += not item['schedule_verified'] or label == 'UNKNOWN_SESSION'
                entry['restricted_count'] += item['phase_states'] != ['FULL_TRADING']
                entry['finality_uncertain_count'] += item['broker_finality'] == 'UNESTABLISHED'
                if len(entry['boundary_samples']) < 16:
                    entry['boundary_samples'].append({key:item[key] for key in
                         ('classification','scheduled_open_utc','scheduled_end_utc','market_open_seconds',
                          'schedule_verified','phase_states','broker_finality','iat_execution_allowed')})
            except SessionValidationError as exc:
                entry['codes'].append(diagnostic(exc.code)['code'])
            except Exception:
                entry['codes'].append('OBSERVATIONS_MALFORMED')
        if not rows:
            entry['codes'].append('OBSERVATIONS_UNAVAILABLE')
        if entry['partial_count']: entry['codes'].append('PARTIAL_SESSION_CANDLE')
        if entry['unknown_count']: entry['codes'].append('SESSION_PHASE_UNKNOWN')
        if entry['outside_count']: entry['codes'].append('BAR_OUTSIDE_SESSION')
        if entry['finality_uncertain_count']: entry['codes'].append('CANDLE_FINALITY_UNCERTAIN')
        if entry['restricted_count']: entry['codes'].append('BROKER_PHASE_RESTRICTED')
        if opened and not any(code in entry['codes'] for code in ('OBSERVATIONS_MALFORMED','TIMESTAMP_DUPLICATE','TIMESTAMP_OUT_OF_ORDER','TIMEFRAME_MISALIGNED')):
            full, partial = 0,0
            actual = set(opened)
            exhausted=False
            for index,expected in enumerate(calendar.expected_intervals(opened[0],opened[-1]+duration,duration)):
                if index>=20000:
                    exhausted=True;entry['codes'].append('RESEARCH_LIMIT_EXCEEDED');break
                if expected not in actual:
                    label = calendar.classify_bar(expected,timeframe,research=True)['classification']
                    if label == 'FULL_SESSION_BAR': full += 1
                    else: partial += 1
            if not exhausted:entry.update(missing_full_count=full, missing_partial_count=partial)
            if full: entry['codes'].append('UNEXPECTED_MISSING_BARS')
            if partial: entry['codes'].append('MISSING_PARTIAL_SESSION_BAR')
        if opened and opened[-1]+duration <= now:
            missing_recent=calendar.expected_opens(opened[-1]+duration,now-duration+timedelta(microseconds=1),duration)
            if sum(1 for _,slot in zip(range(3),missing_recent))>2:
                entry['codes'].append('DATA_STALE')
        entry['codes'] = list(dict.fromkeys(entry['codes']))
        codes.extend(entry['codes'])
    codes = list(dict.fromkeys(diagnostic(code)['code'] for code in codes))
    critical = {'OBSERVATIONS_MALFORMED','TIMESTAMP_DUPLICATE','TIMESTAMP_OUT_OF_ORDER','BAR_UNCLOSED',
                'TIMEFRAME_MISALIGNED','BROKER_SESSION_MISMATCH','BROKER_METADATA_INVALID','CLOCK_MOVED_BACKWARD'}
    report['status'] = 'FAIL' if critical.intersection(codes) else 'BLOCKED' if report['requirements'] else outcome(codes)
    report['diagnostics'] = [diagnostic(code) for code in codes] or [diagnostic('CHECKS_PASSED')]
    validate_research_report(report)
    return report


def validate_research_report(report):
    """Strict fixed-vocabulary research output; no raw source refs or account data."""
    expected = {'report_version','kind','run_id','status','as_of_utc','session_v2','provenance','phase_counts',
                'frames','broker_comparison','requirements','diagnostics','safety'}
    if not isinstance(report,dict) or set(report) != expected or report['kind'] != 'SESSION_V2_RESEARCH' or report['report_version'] != 1:
        raise ValueError('Invalid research report schema')
    from uuid import UUID
    UUID(report['run_id']);utc(datetime.fromisoformat(report['as_of_utc']))
    validate_session_summary(report['session_v2'])
    provenance=report['provenance']
    if set(provenance) != {'origin','source_kinds','terminal_capture_attempted','independent_broker_certification'} or provenance['origin'] not in ORIGINS or provenance['independent_broker_certification'] is not False or type(provenance['terminal_capture_attempted']) is not bool:
        raise ValueError('Unredacted research provenance')
    if any(kind not in ('PUBLISHED','LOCAL_OBSERVATION','SYNTHETIC_TEST') for kind in provenance['source_kinds']): raise ValueError('Unredacted source')
    if set(report['phase_counts']) != set(STATES) or any(type(value) is not int or value < 0 for value in report['phase_counts'].values()): raise ValueError('Invalid phase counts')
    if set(report['frames']) != {'M1','M5'}:raise ValueError('Invalid research frames')
    for frame in report['frames'].values():
        fields={'observed_count','full_count','partial_count','outside_count','unknown_count','restricted_count','finality_uncertain_count',
                'missing_full_count','missing_partial_count','classifications','boundary_samples','codes'}
        if set(frame) != fields:raise ValueError('Unredacted frame')
        for key in fields - {'classifications','boundary_samples','codes'}:
            if frame[key] is not None and (type(frame[key]) is not int or frame[key] < 0):raise ValueError('Invalid count')
        if set(frame['classifications']) != set(CLASSES) or any(type(n) is not int or n<0 for n in frame['classifications'].values()):raise ValueError('Invalid classes')
        if any(code not in MESSAGES for code in frame['codes']) or len(frame['boundary_samples'])>16:raise ValueError('Unredacted diagnostics')
        for sample in frame['boundary_samples']:
            if set(sample) != {'classification','scheduled_open_utc','scheduled_end_utc','market_open_seconds','schedule_verified','phase_states','broker_finality','iat_execution_allowed'}:raise ValueError('Unredacted sample')
            if sample['classification'] not in CLASSES or sample['broker_finality'] not in ('UNESTABLISHED','CONFIRMED_BY_DECLARED_PROVIDER_CONTRACT') or sample['iat_execution_allowed'] is not False or type(sample['schedule_verified']) is not bool:raise ValueError('Unsafe classification')
            for key in ('scheduled_open_utc','scheduled_end_utc'):utc(datetime.fromisoformat(sample[key]))
            if (sample['market_open_seconds'] is None and sample['classification']!='UNKNOWN_SESSION') or (sample['market_open_seconds'] is not None and (type(sample['market_open_seconds']) not in (int,float) or not math.isfinite(sample['market_open_seconds']) or sample['market_open_seconds']<0)) or any(state not in STATES for state in sample['phase_states']):raise ValueError('Invalid research geometry')
    comparison=report['broker_comparison']
    if set(comparison) != {'scope','comparison','mismatch_intervals','codes'} or comparison['scope'] not in ('UNAVAILABLE','DATED','WEEKLY','PHASES_V2') or comparison['comparison'] not in ('NOT_RUN','UNAVAILABLE','INVALID','MISMATCH','MATCH','UNCERTAIN'):raise ValueError('Invalid broker comparison')
    if comparison['mismatch_intervals'] is not None and (type(comparison['mismatch_intervals']) is not int or comparison['mismatch_intervals']<0):raise ValueError('Invalid mismatch count')
    if any(code not in MESSAGES for code in comparison['codes']+report['requirements']):raise ValueError('Unredacted codes')
    for item in report['diagnostics']:
        if not isinstance(item,dict) or item != diagnostic(item.get('code')):raise ValueError('Unredacted message')
    if report['safety'] != {'signal':'WAIT','execution_allowed':False,'ordinary_strategy_inputs_emitted':False,'orders_requested':0,'credentials_requested':False}:raise ValueError('Unsafe research')
    if report['status'] not in ('PASS','WARN','FAIL','BLOCKED'):raise ValueError('Invalid research status')
    if report['status']=='PASS' and ('SYNTHETIC_TEST' in provenance['source_kinds'] or report['requirements'] or outcome([d['code'] for d in report['diagnostics']])!='PASS' or not provenance['terminal_capture_attempted'] or provenance['origin']!='LOCAL_DEMO_OBSERVATION' or comparison['comparison']!='MATCH' or any(f['observed_count']==0 or any(f[k] for k in ('partial_count','unknown_count','outside_count','restricted_count','finality_uncertain_count','missing_full_count','missing_partial_count')) for f in report['frames'].values())):raise ValueError('Uncertain research cannot PASS')
