"""Historical Evidence Manifest v1: integrity and reproduction never grant approval."""
from copy import deepcopy
from pathlib import Path
from datetime import timedelta
import csv,re
from iat.chart_benchmark import keys,require,hashed,check_hash
from iat.replay_dataset import read_bytes,strict_json,utc
from iat.pilot_preparation import file_fingerprint,_bounded_lines
from iat.historical_session_boundaries import inspect_csv_files,read_window
from iat.analysis import validate_candles
from iat.historical_replay import safety
from iat.intelligence.models import iso

VERSION=1
TOOL='historical-evidence-manifest-v1'
MAX_OBSERVATION_BYTES=64*1024
MAX_FILE_BYTES=64*1024*1024
REQUIRED_CODES=tuple(sorted(('BROKER_PHASE_RESTRICTED','CALENDAR_COVERAGE_UNVERIFIED','CALENDAR_SCHEDULE_CONFLICT',
    'CANDLE_FINALITY_UNCERTAIN','HOLIDAY_COVERAGE_UNKNOWN','MAINTENANCE_COVERAGE_UNKNOWN','PARTIAL_SESSION_CANDLE','SESSION_PHASE_UNKNOWN')))
GAPS=('historical_price_basis','provider_feed_provenance','historical_usage_rights','account_instrument_specification',
    'dated_sessions_timezone_dst','holidays_special_closures','maintenance_interruptions','candle_finality_corrections','independent_approval')
STATES=('OPERATOR_REPORTED','LOCAL_INTEGRITY_VERIFIED','LOCAL_MECHANICAL_REPRODUCED','INDEPENDENT_QUALIFICATION_REQUIRED','INVALID_OR_CONFLICTING_EVIDENCE')
MAPPING={'timestamp':'timestamp_utc',**{k:k for k in ('open','high','low','close')}}
HEADERS=['timestamp_utc','open','high','low','close','tick_volume','spread','real_volume']


class EvidenceError(ValueError):
    pass


def need(condition,code):
    if not condition:raise EvidenceError(code)


def sha(value):need(isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) is not None,'DIGEST_INVALID')


def label(value):
    need(isinstance(value,str) and re.fullmatch('[A-Za-z0-9 _.,()/+-]{1,160}',value) is not None,'SANITIZED_LABEL_REQUIRED')


def basename(value,suffix):
    need(isinstance(value,str) and re.fullmatch('[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}',value) is not None
        and '..' not in value and value.endswith(suffix),'LOCAL_FILE_IDENTITY_UNSAFE')


def validate_observations(o):
    keys(o,'observation_version kind data_kind symbol timeframes source_description collection_date_utc code_revision tool_version window files diagnostic calendar findings evidence_references')
    need(type(o['observation_version']) is int and o['observation_version']==VERSION,'OBSERVATION_VERSION_UNSUPPORTED')
    need(o['kind']=='OPERATOR_REPORTED_HISTORICAL_OBSERVATIONS' and o['data_kind'] in ('OPERATOR_REPORTED_REAL_EXPORT','SYNTHETIC_FIXTURE'),'OBSERVATION_KIND_INVALID')
    need(o['symbol']=='XAUUSD' and o['timeframes']==['M1','M5'],'SYMBOL_TIMEFRAMES_INVALID');label(o['source_description'])
    if o['collection_date_utc'] is not None:utc(o['collection_date_utc'])
    if o['code_revision'] is not None:need(isinstance(o['code_revision'],str) and re.fullmatch('[a-f0-9]{40}',o['code_revision']) is not None,'CODE_REVISION_INVALID')
    need(o['tool_version']=='historical-session-boundary-v1','DIAGNOSTIC_VERSION_UNSUPPORTED')
    keys(o['window'],'start end');a,b=(utc(o['window'][k]) for k in ('start','end'))
    need(a<b and (b-a).total_seconds()/60<=20000,'OBSERVATION_WINDOW_LIMIT')
    keys(o['files'],'M1 M5')
    for tf in ('M1','M5'):
        f=o['files'][tf];keys(f,'name sha256 byte_count row_count headers origin price_basis feed_identity first_open_utc last_open_utc')
        basename(f['name'],'.csv');sha(f['sha256'])
        need(f['byte_count'] is None or type(f['byte_count']) is int and 0<f['byte_count']<=MAX_FILE_BYTES,'SOURCE_SIZE_INVALID')
        need(type(f['row_count']) is int and 3<=f['row_count']<=5000,'SOURCE_ROW_LIMIT')
        need(f['headers']==HEADERS,'CSV_HEADER_DECLARATION_INVALID')
        need(f['origin'] in ('NATIVE_OPERATOR_REPORTED','UNKNOWN','DERIVED'),'SOURCE_ORIGIN_INVALID')
        need(f['price_basis'] in ('UNKNOWN','BID','ASK','MID','LAST'),'PRICE_BASIS_INVALID')
        if f['feed_identity'] is not None:label(f['feed_identity'])
        for k in ('first_open_utc','last_open_utc'):
            if f[k] is not None:need(a<=utc(f[k])<b,'COVERAGE_DECLARATION_INVALID')
    d=o['diagnostic'];keys(d,'name file_sha256 byte_count');basename(d['name'],'.json');sha(d['file_sha256'])
    need(d['byte_count'] is None or type(d['byte_count']) is int and 0<d['byte_count']<=4*1024*1024,'DIAGNOSTIC_SIZE_INVALID')
    c=o['calendar'];keys(c,'name file_sha256 quote_close_utc independently_verified');basename(c['name'],'.json');sha(c['file_sha256'])
    need(c['independently_verified'] is False and c['quote_close_utc']=='21:58:00','CANDIDATE_ASSUMPTION_CONFLICT')
    f=o['findings'];keys(f,'comparison_counts absent_m1_slot_counts partials reason_codes')
    for field in ('comparison_counts','absent_m1_slot_counts'):
        need(isinstance(f[field],dict) and 1<=len(f[field])<=16,'FINDING_COUNTS_INVALID')
        for k,v in f[field].items():need(isinstance(k,str) and re.fullmatch('[A-Z0-9_]{1,64}',k) and type(v) is int and 0<=v<=25000,'FINDING_COUNTS_INVALID')
    codes=f['reason_codes'];need(isinstance(codes,list) and len(codes)<=32 and codes==sorted(set(codes)) and set(REQUIRED_CODES)<=set(codes),'REQUIRED_BLOCKERS_MISSING')
    need(all(isinstance(code,str) and re.fullmatch('[A-Z0-9_]{1,64}',code) for code in codes),'REASON_CODE_INVALID')
    need(isinstance(f['partials'],list) and 1<=len(f['partials'])<=32,'PARTIALS_INVALID');seen=set()
    for p in f['partials']:
        keys(p,'open_utc classification market_open_seconds schedule_verified');at=utc(p['open_utc'])
        need(a<=at<b and at.timestamp()%300==0 and at not in seen,'PARTIAL_TIMESTAMP_INVALID');seen.add(at)
        need(p['classification']=='PARTIAL_SESSION_CLOSE' and type(p['market_open_seconds']) in (float,int) and 0<p['market_open_seconds']<300 and p['schedule_verified'] is False,'PARTIAL_DECLARATION_INVALID')
    keys(o['evidence_references'],' '.join(GAPS))
    for value in o['evidence_references'].values():
        if value is not None:
            keys(value,'document sha256');basename(value['document'],'.pdf');sha(value['sha256'])
    return True


def local_path(path):
    value=str(path)
    need(not value.startswith(('\\\\','//')) and '://' not in value,'LOCAL_PATH_REQUIRED')
    return Path(path)


def read_observations(path):
    path=local_path(path)
    need(path.is_file() and not path.is_symlink(),'OBSERVATION_FILE_UNAVAILABLE_OR_UNSAFE')
    need(0<path.stat().st_size<=MAX_OBSERVATION_BYTES,'OBSERVATION_SIZE_LIMIT')
    data=read_bytes(path);need(len(data)<=MAX_OBSERVATION_BYTES,'OBSERVATION_SIZE_LIMIT')
    value=strict_json(data);validate_observations(value);return value


def qualification_gate(manifest):
    """No state or caller-supplied approval field can make this artifact a replay input."""
    return {'status':'BLOCKED','reason_codes':['EVIDENCE_MANIFEST_NOT_REPLAY_ELIGIBLE','INDEPENDENT_QUALIFICATION_REQUIRED'],
        'qualification':'DATA_NOT_QUALIFIED','ordinary_strategy_inputs_allowed':False,'review_packets_allowed':False,
        'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','exness':'BLOCKED','safety':safety()}


def _provenance_conflicts(o):
    left,right=o['files']['M1'],o['files']['M5'];codes=[]
    if any(f['origin']=='DERIVED' for f in (left,right)):codes.append('NATIVE_TIMEFRAME_PROVENANCE_CONFLICT')
    if left['price_basis']!='UNKNOWN' and right['price_basis']!='UNKNOWN' and left['price_basis']!=right['price_basis']:codes.append('PRICE_BASIS_CONFLICT')
    if left['feed_identity'] and right['feed_identity'] and left['feed_identity']!=right['feed_identity']:codes.append('FEED_IDENTITY_CONFLICT')
    return codes


def create_manifest(observations):
    validate_observations(observations);o=deepcopy(observations);conflicts=_provenance_conflicts(o)
    state='INVALID_OR_CONFLICTING_EVIDENCE' if conflicts else 'OPERATOR_REPORTED'
    return hashed({'manifest_schema_version':VERSION,'kind':'HISTORICAL_EVIDENCE_MANIFEST','tool_version':TOOL,
        'evidence_mode':'OPERATOR_REPORTED_NOT_INDEPENDENTLY_REPRODUCED','evidence_state':state,'state_history':['OPERATOR_REPORTED']+([state] if conflicts else []),
        'operator_assertions':o,'column_mapping':dict(MAPPING,volume='tick_volume',volume_kind='TICK',complete=None,symbol=None,price_basis=None,feed_id=None,ignored_columns=['spread','real_volume']),'local_facts':None,'reproduction':{'status':'NOT_REPRODUCED'},'externally_verified_evidence':[],
        'evidence_gaps':{k:{'status':'MISSING' if v is None else 'OPERATOR_REFERENCE_NOT_VERIFIED','reference':v} for k,v in o['evidence_references'].items()},
        'reason_codes':sorted(set(o['findings']['reason_codes'])|set(conflicts)|{'INDEPENDENT_QUALIFICATION_REQUIRED'}),
        'hash_contract':{'algorithm':'SHA-256','file_digest':'EXACT_ORIGINAL_BYTES','payload_digest':'UTF8_JSON_SORTED_KEYS_COMPACT_ENSURE_ASCII_TRUE_NO_NAN_EXCLUDING_ROOT_SHA256',
            'excluded_metadata':['absolute_input_paths','output_path','runtime_clock','filesystem_mtime','runtime_python_platform_tzdata_versions'],
            'dependencies':['operator_assertions -> manifest','M1/M5/calendar bytes -> diagnostic','diagnostic bytes and payload -> local_facts -> manifest']},
        'qualification_gate':qualification_gate(None),'qualification':'DATA_NOT_QUALIFIED','historical_validation':'PENDING',
        'historical_comparisons':'NOT_RUN','exness':'BLOCKED','safety':safety()})


def _fingerprint(path,expected,suffix):
    p=local_path(path);need(p.suffix.lower()==suffix and p.is_file() and not p.is_symlink(),'LOCAL_FILE_UNAVAILABLE_OR_UNSAFE')
    need(0<p.stat().st_size<=MAX_FILE_BYTES,'LOCAL_FILE_SIZE_LIMIT');actual=file_fingerprint(p)
    need(actual['byte_count']<=MAX_FILE_BYTES,'LOCAL_FILE_SIZE_LIMIT')
    need(actual['sha256']==expected['sha256'],'FILE_SHA256_MISMATCH')
    if expected.get('byte_count') is not None:need(actual['byte_count']==expected['byte_count'],'FILE_BYTE_COUNT_MISMATCH')
    return actual


def verify_local(observations,*,m1_path,m5_path,diagnostic_path,calendar_path):
    report=create_manifest(observations);report.pop('sha256');report['evidence_mode']='LOCAL_REPRODUCIBILITY_VERIFICATION'
    paths={'M1':m1_path,'M5':m5_path,'diagnostic':diagnostic_path,'calendar':calendar_path};o=report['operator_assertions'];facts={};report['local_facts']=facts
    try:
        need(report['evidence_state']!='INVALID_OR_CONFLICTING_EVIDENCE','PROVENANCE_CONFLICT')
        resolved=[local_path(p).resolve() for p in paths.values()];need(len(set(resolved))==4,'INPUT_PATH_ALIAS')
        for tf in ('M1','M5'):facts[tf]={'file_fingerprint':_fingerprint(paths[tf],o['files'][tf],'.csv')}
        for key in ('diagnostic','calendar'):
            declared=o[key];facts[key]={'file_fingerprint':_fingerprint(paths[key],{'sha256':declared['file_sha256'],'byte_count':declared.get('byte_count')},'.json')}
        report['state_history'].append('LOCAL_INTEGRITY_VERIFIED')
        raw=read_bytes(diagnostic_path);diagnostic=strict_json(raw);check_hash(diagnostic)
        facts['diagnostic']['embedded_payload_sha256']=diagnostic['sha256']
        for tf,minutes in (('M1',1),('M5',5)):
            with Path(paths[tf]).open('r',encoding='utf-8-sig',newline='') as handle:headers=next(csv.reader(_bounded_lines(handle),strict=True))
            need(headers==o['files'][tf]['headers'],'CSV_HEADER_MISMATCH')
            rows,scan=read_window(paths[tf],MAPPING,o['window']['start'],o['window']['end'])
            need(not scan['parse_errors'],'CSV_PARSE_INVALID')
            need(scan['scanned_row_count']==o['files'][tf]['row_count']==len(rows),'CSV_ROW_COUNT_OR_SCOPE_MISMATCH')
            try:validate_candles(rows)
            except ValueError:raise EvidenceError('CSV_CHRONOLOGY_OR_OHLC_INVALID') from None
            need(all(utc(r['timestamp']).timestamp()%(minutes*60)==0 for r in rows),'TIMEFRAME_ALIGNMENT_INVALID')
            first,last=(iso(utc(rows[i]['timestamp'])) for i in (0,-1))
            for field,actual in (('first_open_utc',first),('last_open_utc',last)):
                if o['files'][tf][field] is not None:need(utc(o['files'][tf][field])==utc(actual),'CSV_TIMESTAMP_COVERAGE_MISMATCH')
            facts[tf].update(row_count=len(rows),headers=headers,first_open_utc=first,last_open_utc=last,
                scheduled_last_end_utc=iso(utc(last)+timedelta(minutes=minutes)),timestamp_convention='UTC_INTERVAL_OPEN',
                normalized_ohlc_payload_sha256=hashed({'rows':rows})['sha256'])
        reproduced=inspect_csv_files(m1_path,m5_path,calendar_path,o['window']['start'],o['window']['end'],MAPPING)
        need(reproduced==diagnostic,'DIAGNOSTIC_REPRODUCTION_MISMATCH')
        need(diagnostic['comparison_counts']==o['findings']['comparison_counts'],'COMPARISON_COUNTS_MISMATCH')
        need(diagnostic['m1_slot_absence_counts']==o['findings']['absent_m1_slot_counts'],'ABSENT_SLOT_COUNTS_MISMATCH')
        partials=[{'open_utc':b['geometry']['scheduled_open_utc'],'classification':b['geometry']['classification'],
            'market_open_seconds':b['geometry']['market_open_seconds'],'schedule_verified':b['geometry']['schedule_verified']}
            for b in diagnostic['m5_intervals'] if b['geometry']['classification']=='PARTIAL_SESSION_CLOSE']
        expected=deepcopy(o['findings']['partials'])
        for p in expected:p['open_utc']=iso(utc(p['open_utc']))
        need(sorted(partials,key=lambda p:p['open_utc'])==sorted(expected,key=lambda p:p['open_utc']),'PARTIAL_SESSION_FINDINGS_MISMATCH')
        need(diagnostic['reason_codes']==o['findings']['reason_codes'],'DIAGNOSTIC_BLOCKERS_MISMATCH')
        need(diagnostic['qualification']=='DATA_NOT_QUALIFIED' and diagnostic['historical_validation']=='PENDING'
            and diagnostic['historical_comparisons']=='NOT_RUN' and diagnostic['exness']=='BLOCKED'
            and diagnostic['safety']==safety() and diagnostic['ordinary_inputs_emitted'] is False,'DIAGNOSTIC_SAFETY_CONFLICT')
        for key,p in paths.items():need(file_fingerprint(p)==facts[key]['file_fingerprint'],'INPUT_CHANGED_DURING_VERIFICATION')
        facts['research_findings']={'comparison_counts':deepcopy(diagnostic['comparison_counts']),
            'absent_m1_slot_counts':deepcopy(diagnostic['m1_slot_absence_counts']),'partials':partials,
            'reason_codes':list(diagnostic['reason_codes']),'calendar_independently_verified':False}
        report['state_history']+=['LOCAL_MECHANICAL_REPRODUCED','INDEPENDENT_QUALIFICATION_REQUIRED']
        report['evidence_state']='INDEPENDENT_QUALIFICATION_REQUIRED'
        report['reproduction']={'status':'REPRODUCED','diagnostic_payload_sha256':reproduced['sha256'],
            'scope':'PR23_RESEARCH_DIAGNOSTIC_ONLY_NOT_STRATEGY_REPLAY','source_authenticity':'NOT_ESTABLISHED','historical_price_basis':'NOT_ESTABLISHED','full_or_partial_finality':'NOT_ESTABLISHED',
            'candidate_schedule_independently_verified':False}
    except (ValueError,OSError,TypeError,KeyError,OverflowError,csv.Error,StopIteration) as exc:
        code=str(exc) if isinstance(exc,EvidenceError) else 'LOCAL_EVIDENCE_INVALID_OR_UNAVAILABLE'
        report['evidence_state']='INVALID_OR_CONFLICTING_EVIDENCE'
        if report['state_history'][-1]!=report['evidence_state']:report['state_history'].append(report['evidence_state'])
        report['reason_codes']=sorted(set(report['reason_codes'])|{code})
    return hashed(report)


def validate_manifest(m):
    expected=set(create_manifest(m['operator_assertions']));need(set(m)==expected,'MANIFEST_SCHEMA_INVALID');check_hash(m)
    need(type(m['manifest_schema_version']) is int and m['manifest_schema_version']==VERSION,'MANIFEST_VERSION_UNSUPPORTED')
    need(m['kind']=='HISTORICAL_EVIDENCE_MANIFEST' and m['tool_version']==TOOL,'MANIFEST_KIND_INVALID')
    need(m['evidence_mode'] in ('OPERATOR_REPORTED_NOT_INDEPENDENTLY_REPRODUCED','LOCAL_REPRODUCIBILITY_VERIFICATION'),'EVIDENCE_MODE_INVALID')
    need(m['evidence_state'] in STATES and m['state_history'][-1]==m['evidence_state'],'EVIDENCE_STATE_INVALID')
    baseline=create_manifest(m['operator_assertions'])
    for field in ('column_mapping','qualification_gate','qualification','historical_validation','historical_comparisons','exness','safety','evidence_gaps','externally_verified_evidence','hash_contract'):
        need(m[field]==baseline[field],'MANIFEST_SAFETY_OR_APPROVAL_CONFLICT')
    need(set(baseline['reason_codes'])<=set(m['reason_codes']),'MANIFEST_BLOCKERS_REMOVED')
    need(m['reproduction']['status'] in ('NOT_REPRODUCED','REPRODUCED'),'REPRODUCTION_STATE_INVALID')
    need(m['state_history'] in (['OPERATOR_REPORTED'],['OPERATOR_REPORTED','INVALID_OR_CONFLICTING_EVIDENCE'],
        ['OPERATOR_REPORTED','LOCAL_INTEGRITY_VERIFIED','INVALID_OR_CONFLICTING_EVIDENCE'],
        ['OPERATOR_REPORTED','LOCAL_INTEGRITY_VERIFIED','LOCAL_MECHANICAL_REPRODUCED','INDEPENDENT_QUALIFICATION_REQUIRED']),'EVIDENCE_TRANSITION_INVALID')
    need((m['reproduction']['status']=='REPRODUCED')==(m['evidence_state']=='INDEPENDENT_QUALIFICATION_REQUIRED'),'REPRODUCTION_STATE_INVALID')
    return True
