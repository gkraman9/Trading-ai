"""Offline source review v1. Review classifications never qualify market data."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
import re
from iat.chart_benchmark import keys,require,hashed,check_hash
from iat.replay_dataset import read_bytes,strict_json,local_file,digest as byte_digest,utc
from iat.historical_evidence_manifest import (GAPS,REQUIRED_CODES,qualification_gate,local_path,sha,basename,validate_manifest,need)
from iat.session_config import local_utc,SessionConfigError

KIND='INDEPENDENT_SOURCE_EVIDENCE_V1'
REPORT_KIND='HISTORICAL_SOURCE_REVIEW'
MAX_REGISTRY_BYTES=256*1024
SESSION_FIELDS=('weekday_quote_hours','daily_interruptions','weekend_boundaries','holiday_exceptions',
    'maintenance_windows','exceptional_announcements','dated_schedule')
PRICE_FIELDS=('price_basis','bar_construction','symbol_settings','tick_aggregation','timestamp_convention',
    'spread_representation','completed_bars','correction_policy','demo_live_distinction')
CRITERIA=('authority','temporal','instrument','account','claim_support')
CLASSIFICATIONS=('SUPPORTED_WITH_APPLICABILITY','SOURCE_PRESENT_APPLICABILITY_UNKNOWN','INSUFFICIENT_EVIDENCE',
    'CONFLICTING_EVIDENCE','SOURCE_UNAVAILABLE','NOT_REVIEWED')


def text(value):
    need(isinstance(value,str) and 0<len(value)<=500 and not any(ord(c)<32 for c in value),'REVIEW_TEXT_INVALID')


def identifier(value):need(isinstance(value,str) and re.fullmatch('[A-Za-z0-9_-]{1,64}',value) is not None,'REVIEW_IDENTIFIER_INVALID')


def optional_text(value):
    if value is not None:text(value)


def interval(value):
    keys(value,'start end');need(utc(value['start'])<utc(value['end']),'REVIEW_INTERVAL_INVALID')


def reference(value,synthetic):
    if value is None:return
    text(value);p=urlsplit(value)
    need(not p.username and not p.password and not p.query and not p.fragment,'SOURCE_REFERENCE_UNSAFE')
    if p.scheme=='document':basename(p.path,('.pdf','.txt','.html','.json','.md'))
    elif p.scheme=='synthetic':need(synthetic and bool(p.path or p.netloc),'SOURCE_REFERENCE_UNSAFE')
    else:need(p.scheme=='https' and bool(p.hostname) and not p.port,'SOURCE_REFERENCE_UNSAFE')


def claim_value(claim,value):
    text(value)
    if value=='UNKNOWN':return
    if claim['predicate'].endswith('_utc'):need(re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d',value) is not None,'SESSION_CLOCK_VALUE_INVALID')
    if claim['predicate'] in ('price_basis','historical_price_basis'):need(value in ('BID','ASK','MID','LAST'),'PRICE_BASIS_CLAIM_INVALID')


def validate_registry(r):
    keys(r,'registry_version kind data_kind collector_id as_of_utc context manifest_reference claims evidence reviews')
    need(type(r['registry_version']) is int and r['registry_version']==1 and r['kind']==KIND,'SOURCE_REGISTRY_VERSION_UNSUPPORTED')
    need(r['data_kind'] in ('PUBLIC_REFERENCE_REVIEW','SYNTHETIC_FIXTURE'),'SOURCE_REGISTRY_KIND_INVALID');identifier(r['collector_id']);utc(r['as_of_utc'])
    c=r['context'];keys(c,'broker account_scope account_category instrument interval');text(c['broker']);identifier(c['account_scope']);need(c['account_category'] in ('DEMO','LIVE','CENT','TRIAL','UNKNOWN'),'ACCOUNT_CATEGORY_INVALID');need(c['instrument']=='XAUUSD','REVIEW_INSTRUMENT_INVALID');interval(c['interval']);need(utc(r['as_of_utc'])>=utc(c['interval']['end']),'REVIEW_CUTOFF_BEFORE_HISTORY')
    m=r['manifest_reference'];keys(m,'origin reported_evidence_state manifest_payload_sha256 manifest_file_sha256 diagnostic_payload_sha256 dataset_fingerprints')
    need(m['origin']=='OPERATOR_REPORTED_LOCAL_VERIFICATION' and m['reported_evidence_state']=='INDEPENDENT_QUALIFICATION_REQUIRED','MANIFEST_REFERENCE_INVALID')
    for k in ('manifest_payload_sha256','diagnostic_payload_sha256'):sha(m[k])
    if m['manifest_file_sha256'] is not None:sha(m['manifest_file_sha256'])
    keys(m['dataset_fingerprints'],'M1 M5 diagnostic calendar')
    for v in m['dataset_fingerprints'].values():sha(v)
    need(isinstance(r['claims'],list) and 1<=len(r['claims'])<=64,'CLAIM_LIMIT');claims={}
    for c in r['claims']:
        keys(c,'id category predicate candidate_value description');identifier(c['id']);identifier(c['predicate']);text(c['candidate_value']);text(c['description'])
        need(c['category'] in GAPS and c['id'] not in claims,'CLAIM_CATEGORY_OR_ID_INVALID');claim_value(c,c['candidate_value']);claims[c['id']]=c
    need(isinstance(r['evidence'],list) and len(r['evidence'])<=64,'SOURCE_RECORD_LIMIT');ids=set()
    for e in r['evidence']:
        keys(e,'id category claim_id value publisher title reference published_at_utc retrieved_at_utc effective_start_utc effective_end_utc broker account_scope account_category instrument summary artifact collection_method verification_status reviewer_notes conflicting_references limitations quotation_timezone trading_timezone dst_rule wall_time_anchors session_details price_details')
        identifier(e['id']);need(e['id'] not in ids,'DUPLICATE_EVIDENCE_ID');ids.add(e['id'])
        need(e['category'] in GAPS and e['claim_id'] in claims and claims[e['claim_id']]['category']==e['category'],'SOURCE_CATEGORY_OR_CLAIM_INVALID')
        for k in ('value','title','summary'):text(e[k])
        for k in ('publisher','broker','instrument','quotation_timezone','trading_timezone','dst_rule','reviewer_notes'):optional_text(e[k])
        if e['account_scope'] is not None:identifier(e['account_scope'])
        need(e['account_category'] is None or e['account_category'] in ('DEMO','LIVE','CENT','TRIAL','UNKNOWN'),'ACCOUNT_CATEGORY_INVALID')
        claim_value(claims[e['claim_id']],e['value'])
        reference(e['reference'],r['data_kind']=='SYNTHETIC_FIXTURE')
        for k in ('published_at_utc','retrieved_at_utc','effective_start_utc','effective_end_utc'):
            if e[k] is not None:utc(e[k])
        if e['effective_start_utc'] and e['effective_end_utc']:need(utc(e['effective_start_utc'])<utc(e['effective_end_utc']),'SOURCE_EFFECTIVE_INTERVAL_INVALID')
        need(e['collection_method'] in ('MANUAL_REFERENCE','MANUAL_PUBLIC_TEXT_REVIEW','MANUAL_LOCAL_DOCUMENT','SYNTHETIC_FIXTURE'),'COLLECTION_METHOD_INVALID')
        need(r['data_kind']=='SYNTHETIC_FIXTURE' or e['collection_method']!='SYNTHETIC_FIXTURE','SYNTHETIC_SOURCE_MISLABELED')
        need(e['verification_status'] in ('REFERENCE_ONLY','PUBLIC_TEXT_REVIEWED','ARTIFACT_PROVIDED','DECLARED_UNAVAILABLE'),'SOURCE_STATUS_NOT_AN_APPROVAL')
        if e['artifact'] is not None:
            keys(e['artifact'],'file sha256');basename(e['artifact']['file'],('.pdf','.txt','.html','.json','.md'));sha(e['artifact']['sha256'])
        for k in ('limitations','conflicting_references'):
            need(isinstance(e[k],list) and len(e[k])<=16,'SOURCE_LIST_LIMIT')
        for v in e['limitations']:text(v)
        for v in e['conflicting_references']:identifier(v)
        need(len(e['conflicting_references'])==len(set(e['conflicting_references'])) and e['id'] not in e['conflicting_references'],'SOURCE_CONFLICT_REFERENCE_INVALID')
        keys(e['session_details'],' '.join(SESSION_FIELDS));keys(e['price_details'],' '.join(PRICE_FIELDS))
        for v in list(e['session_details'].values())+list(e['price_details'].values()):optional_text(v)
        need(isinstance(e['wall_time_anchors'],list) and len(e['wall_time_anchors'])<=8,'WALL_TIME_ANCHOR_LIMIT')
        for v in e['wall_time_anchors']:
            keys(v,'local timezone expected_utc');text(v['local']);text(v['timezone'])
            need(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',v['local']) is not None and datetime.fromisoformat(v['local']).tzinfo is None,'EXPLICIT_NAIVE_WALL_TIME_REQUIRED')
            if v['expected_utc'] is not None:utc(v['expected_utc'])
    for e in r['evidence']:need(set(e['conflicting_references'])<=ids,'SOURCE_CONFLICT_REFERENCE_INVALID')
    need(isinstance(r['reviews'],list) and len(r['reviews'])<=64,'REVIEW_LIMIT');review_ids=set()
    for v in r['reviews']:
        keys(v,'id reviewer_id reviewed_at_utc evidence_ids claim_id scope conclusion criteria unresolved_conflicts explanation provenance')
        identifier(v['id']);identifier(v['reviewer_id']);need(v['id'] not in review_ids,'DUPLICATE_REVIEW_ID');review_ids.add(v['id'])
        need(v['reviewer_id']!=r['collector_id'],'INDEPENDENT_REVIEWER_REQUIRED');utc(v['reviewed_at_utc'])
        need(v['claim_id'] in claims and isinstance(v['evidence_ids'],list) and 1<=len(v['evidence_ids'])<=64 and len(set(v['evidence_ids']))==len(v['evidence_ids']) and set(v['evidence_ids'])<=ids,'REVIEW_REFERENCES_INVALID')
        need(all(e['claim_id']==v['claim_id'] for e in r['evidence'] if e['id'] in v['evidence_ids']),'REVIEW_CLAIM_MISMATCH')
        keys(v['scope'],'broker account_scope account_category instrument interval');text(v['scope']['broker']);identifier(v['scope']['account_scope']);text(v['scope']['instrument']);interval(v['scope']['interval'])
        need(v['conclusion'] in ('SUPPORTS','REJECTS','UNRESOLVED','ACKNOWLEDGED'),'REVIEW_CONCLUSION_NOT_QUALIFICATION')
        keys(v['criteria'],' '.join(CRITERIA));need(all(x in ('SUPPORTED','CONTRADICTED','UNRESOLVED') for x in v['criteria'].values()),'REVIEW_CRITERIA_INVALID')
        need(isinstance(v['unresolved_conflicts'],list) and len(v['unresolved_conflicts'])<=16,'REVIEW_CONFLICT_LIMIT')
        for x in v['unresolved_conflicts']:text(x)
        text(v['explanation']);keys(v['provenance'],'method document sha256')
        need(v['provenance']['method']=='MANUAL_REVIEW_DECLARATION_NOT_AUTHENTICATED','REVIEW_PROVENANCE_INVALID')
        basename(v['provenance']['document'],('.pdf','.txt','.json','.md'));sha(v['provenance']['sha256'])
    return True


def read_registry(path):
    p=local_path(path);need(p.is_file() and not p.is_symlink() and p.suffix.lower()=='.json','SOURCE_REGISTRY_UNAVAILABLE')
    need(0<p.stat().st_size<=MAX_REGISTRY_BYTES,'SOURCE_REGISTRY_SIZE_LIMIT')
    raw=read_bytes(p);need(len(raw)<=MAX_REGISTRY_BYTES,'SOURCE_REGISTRY_SIZE_LIMIT');r=strict_json(raw);validate_registry(r)
    return r,{'file_sha256':byte_digest(raw),'byte_count':len(raw)}


def _timezone_checks(e):
    reasons=[]
    for k in ('quotation_timezone','trading_timezone'):
        if e[k] is None:reasons.append(k.upper()+'_UNKNOWN')
        else:
            try:ZoneInfo(e[k])
            except (ValueError,ZoneInfoNotFoundError):reasons.append('TIMEZONE_UNSUPPORTED')
    for v in e['wall_time_anchors']:
        try:
            converted=local_utc(datetime.fromisoformat(v['local']),ZoneInfo(v['timezone']))
            if v['expected_utc'] is not None and converted!=utc(v['expected_utc']):reasons.append('WALL_TIME_UTC_CONFLICT')
        except SessionConfigError as exc:reasons.append(exc.code)
        except (ValueError,ZoneInfoNotFoundError):reasons.append('TIMEZONE_UNSUPPORTED')
    return sorted(set(reasons))


def _integrity(e,root):
    if e['artifact'] is None:return {'status':'NOT_SUPPLIED','actual_file_sha256':None}
    if root is None:return {'status':'ARTIFACT_NOT_INSPECTED','actual_file_sha256':None}
    try:
        root=local_path(root);need(root.is_dir() and not root.is_symlink(),'SOURCE_ROOT_UNSAFE')
        need(not (root/e['artifact']['file']).is_symlink(),'SOURCE_ARTIFACT_UNSAFE')
        p=local_file(root,e['artifact']['file']);need(p.is_file() and not p.is_symlink(),'SOURCE_ARTIFACT_UNAVAILABLE')
        raw=read_bytes(p);actual=byte_digest(raw)
        return {'status':'MATCH' if actual==e['artifact']['sha256'] else 'MISMATCH','actual_file_sha256':actual,'byte_count':len(raw)}
    except (ValueError,OSError):return {'status':'UNAVAILABLE','actual_file_sha256':None}


def _assess(e,r,root):
    c=r['context'];asof=utc(r['as_of_utc']);a,b=(utc(c['interval'][k]) for k in ('start','end'));reasons=_timezone_checks(e)
    if e['published_at_utc'] and e['retrieved_at_utc'] and utc(e['published_at_utc'])>utc(e['retrieved_at_utc']):reasons.append('SOURCE_DATE_CHRONOLOGY_CONFLICT')
    future=any(e[k] and utc(e[k])>asof for k in ('published_at_utc','retrieved_at_utc'))
    if future:temporal='FUTURE_DATED';reasons.append('SOURCE_FUTURE_DATED')
    elif e['effective_start_utc'] and utc(e['effective_start_utc'])>=b or e['effective_end_utc'] and utc(e['effective_end_utc'])<=a:temporal='OUTSIDE_HISTORY';reasons.append('SOURCE_DATE_MISMATCH')
    elif e['effective_start_utc'] and e['effective_end_utc'] and utc(e['effective_start_utc'])<=a and utc(e['effective_end_utc'])>=b:temporal='DECLARED_MATCH'
    else:temporal='UNKNOWN';reasons.append('SOURCE_TEMPORAL_APPLICABILITY_UNKNOWN')
    scope={k:'UNKNOWN' if e[k] is None or e[k]=='UNKNOWN' or c[k]=='UNKNOWN' else 'DECLARED_MATCH' if e[k]==c[k] else 'MISMATCH' for k in ('broker','instrument','account_scope','account_category')}
    for k,v in scope.items():
        if v!='DECLARED_MATCH':reasons.append('SOURCE_'+k.upper()+'_'+v)
    integrity=_integrity(e,root)
    if integrity['status'] in ('MISMATCH','UNAVAILABLE'):reasons.append('SOURCE_ARTIFACT_'+integrity['status'])
    reviews=[];invalid_reviews=[]
    for v in r['reviews']:
        if e['id'] not in v['evidence_ids']:continue
        if utc(v['reviewed_at_utc'])>asof or any(e[k] and utc(v['reviewed_at_utc'])<utc(e[k]) for k in ('published_at_utc','retrieved_at_utc')) or v['scope']!=c:
            invalid_reviews.append(v['id']);reasons.append('REVIEW_DATE_OR_SCOPE_UNSUPPORTED')
        else:reviews.append(v)
    conclusions={v['conclusion'] for v in reviews};criteria_ok=bool(reviews) and all(v['conclusion']=='SUPPORTS' and all(x=='SUPPORTED' for x in v['criteria'].values()) and not v['unresolved_conflicts'] for v in reviews)
    disagreement=bool('SUPPORTS' in conclusions and ('REJECTS' in conclusions or any('CONTRADICTED' in v['criteria'].values() for v in reviews)))
    all_scope=temporal=='DECLARED_MATCH' and all(v=='DECLARED_MATCH' for v in scope.values()) and not reasons
    reviewed_support=bool(criteria_ok and not disagreement and conclusions=={'SUPPORTS'})
    return {'evidence_id':e['id'],'source_existence':'DECLARED_UNAVAILABLE' if e['verification_status']=='DECLARED_UNAVAILABLE' else 'REFERENCE_PROVIDED' if e['reference'] else 'REFERENCE_MISSING',
        'source_integrity':integrity,'source_authority':'DECLARED_PUBLISHER_IDENTIFIABLE_NOT_AUTHENTICATED' if e['publisher'] else 'UNESTABLISHED',
        'temporal_applicability':temporal,'scope_applicability':scope,'timezone_reason_codes':_timezone_checks(e),
        'independent_review':{'status':'REVIEWER_DISAGREEMENT' if disagreement else 'REVIEW_DECLARATIONS_RECORDED' if reviews else 'NOT_REVIEWED',
            'review_ids':sorted(v['id'] for v in reviews),'unsupported_review_ids':sorted(invalid_reviews),'authenticity':'NOT_EXTERNALLY_AUTHENTICATED'},
        'claim_support':'DISPUTED' if disagreement else 'SUPPORTED_REVIEW_DECLARATION' if reviewed_support else 'ACKNOWLEDGED_ONLY' if conclusions=={'ACKNOWLEDGED'} else 'NOT_ESTABLISHED',
        'supported_with_applicability':bool(all_scope and reviewed_support and integrity['status']=='MATCH' and e['reference'] and e['publisher'] and e['verification_status']!='DECLARED_UNAVAILABLE'),
        'reviewer_disagreement':disagreement,'reason_codes':sorted(set(reasons))}


def _manifest_reference(r,path):
    if path is None:return {'status':'NOT_SUPPLIED','raw_csv_reproduction':'NOT_RUN'}
    try:
        p=local_path(path);need(p.is_file() and not p.is_symlink() and p.suffix.lower()=='.json','MANIFEST_FILE_UNSAFE')
        raw=read_bytes(p);m=strict_json(raw);validate_manifest(m);ref=r['manifest_reference']
        need(m['sha256']==ref['manifest_payload_sha256'],'PR24_MANIFEST_PAYLOAD_MISMATCH')
        if ref['manifest_file_sha256'] is not None:need(byte_digest(raw)==ref['manifest_file_sha256'],'PR24_MANIFEST_FILE_MISMATCH')
        need(m['evidence_state']=='INDEPENDENT_QUALIFICATION_REQUIRED' and m['reproduction']['status']=='REPRODUCED','PR24_LOCAL_REPRODUCTION_NOT_RECORDED')
        need(m['operator_assertions']['symbol']==r['context']['instrument'] and all(utc(m['operator_assertions']['window'][k])==utc(r['context']['interval'][k]) for k in ('start','end')),'PR24_CONTEXT_MISMATCH')
        actual={tf:m['local_facts'][tf]['file_fingerprint']['sha256'] for tf in ('M1','M5','diagnostic','calendar')}
        need(actual==ref['dataset_fingerprints'] and m['reproduction']['diagnostic_payload_sha256']==ref['diagnostic_payload_sha256'],'PR24_DATASET_BINDING_MISMATCH')
        return {'status':'LOCAL_MANIFEST_BYTES_INSPECTED','file_sha256':byte_digest(raw),'byte_count':len(raw),'payload_sha256':m['sha256'],
            'computation_provenance':'PROVIDED_MANIFEST_RECORD_NOT_REEXECUTED','raw_csv_reproduction':'NOT_RUN'}
    except (ValueError,OSError,KeyError,TypeError,IndexError,RecursionError):return {'status':'INVALID_OR_CONFLICTING_MANIFEST','raw_csv_reproduction':'NOT_RUN'}


def review_registry(registry,*,artifact_root=None,manifest_path=None):
    validate_registry(registry);r=deepcopy(registry)
    for field in ('claims','evidence','reviews'):r[field].sort(key=lambda item:item['id'])
    for e in r['evidence']:e['conflicting_references'].sort()
    for v in r['reviews']:v['evidence_ids'].sort()
    if artifact_root is not None:local_path(artifact_root) # Reject network paths before any filesystem operation.
    assessed={e['id']:_assess(e,r,artifact_root) for e in sorted(r['evidence'],key=lambda e:e['id'])};matrix=[]
    for claim in sorted(r['claims'],key=lambda c:c['id']):
        es=sorted((e for e in r['evidence'] if e['claim_id']==claim['id']),key=lambda e:e['id'])
        eligible=[e for e in es if assessed[e['id']]['temporal_applicability'] not in ('OUTSIDE_HISTORY','FUTURE_DATED') and 'MISMATCH' not in assessed[e['id']]['scope_applicability'].values()]
        known_values={e['value'] for e in eligible if e['value']!='UNKNOWN'}
        explicit=sorted({(e['id'],other) for e in es for other in e['conflicting_references']})
        contradictory=[e['id'] for e in eligible if claim['candidate_value']!='UNKNOWN' and e['value'] not in (claim['candidate_value'],'UNKNOWN')]
        conflicts=bool(explicit or len(known_values)>1 or contradictory or any(assessed[e['id']]['reviewer_disagreement'] for e in es))
        if conflicts:classification='CONFLICTING_EVIDENCE'
        elif not es:classification='INSUFFICIENT_EVIDENCE'
        elif all(assessed[e['id']]['source_existence']!='REFERENCE_PROVIDED' or assessed[e['id']]['source_integrity']['status'] in ('MISMATCH','UNAVAILABLE') for e in es):classification='SOURCE_UNAVAILABLE'
        elif any(assessed[e['id']]['supported_with_applicability'] for e in es):classification='SUPPORTED_WITH_APPLICABILITY'
        elif any(assessed[e['id']]['temporal_applicability']=='UNKNOWN' or 'UNKNOWN' in assessed[e['id']]['scope_applicability'].values() for e in es):classification='SOURCE_PRESENT_APPLICABILITY_UNKNOWN'
        elif any(assessed[e['id']]['temporal_applicability'] in ('OUTSIDE_HISTORY','FUTURE_DATED') or 'MISMATCH' in assessed[e['id']]['scope_applicability'].values() or assessed[e['id']]['timezone_reason_codes'] for e in es):classification='INSUFFICIENT_EVIDENCE'
        elif all(assessed[e['id']]['independent_review']['status']=='NOT_REVIEWED' for e in es):classification='NOT_REVIEWED'
        else:classification='INSUFFICIENT_EVIDENCE'
        matrix.append({'claim':claim,'classification':classification,'supporting_reference_ids':[e['id'] for e in es if e['value']==claim['candidate_value'] and e['value']!='UNKNOWN'],
            'contradicting_candidate_reference_ids':contradictory,'source_values':[{'evidence_id':e['id'],'value':e['value'],'effective_start_utc':e['effective_start_utc'],'effective_end_utc':e['effective_end_utc']} for e in es],
            'explicit_conflicts':[{'evidence_id':a,'conflicting_reference':b} for a,b in explicit],
            'reason_codes':sorted({code for e in es for code in assessed[e['id']]['reason_codes']}),
            'required_review_steps':['INSPECT_ORIGINAL_SOURCE','ESTABLISH_DATED_ACCOUNT_INSTRUMENT_APPLICABILITY','RESOLVE_ALL_CONFLICTS','INDEPENDENT_QUALIFICATION_STILL_REQUIRED']})
    coverage={gap:{'claim_ids':[m['claim']['id'] for m in matrix if m['claim']['category']==gap],
        'reference_ids':sorted(e['id'] for e in r['evidence'] if e['category']==gap),
        'status':'REVIEW_ASSERTIONS_ONLY_NOT_QUALIFICATION' if any(m['classification']=='SUPPORTED_WITH_APPLICABILITY' and m['claim']['category']==gap for m in matrix) else 'UNRESOLVED'} for gap in GAPS}
    manifest=_manifest_reference(r,manifest_path);reasons=set(REQUIRED_CODES)|{'INDEPENDENT_QUALIFICATION_REQUIRED'}
    reasons.update(code for item in assessed.values() for code in item['reason_codes'])
    if manifest['status']=='INVALID_OR_CONFLICTING_MANIFEST':reasons.add('PR24_MANIFEST_INVALID_OR_CONFLICTING')
    if any(m['classification']=='CONFLICTING_EVIDENCE' for m in matrix):reasons.add('SOURCE_CLAIMS_CONFLICT')
    return hashed({**qualification_gate(None),'source_review_version':1,'kind':REPORT_KIND,'review_mode':'REVIEW_ONLY','data_kind':r['data_kind'],
        'registry_file_fingerprint':None,'registry_payload_sha256':hashed(r)['sha256'],'context':r['context'],'manifest_reference':r['manifest_reference'],'local_manifest_inspection':manifest,
        'evidence_inventory':sorted(r['evidence'],key=lambda e:e['id']),'source_assessments':list(assessed.values()),'claim_matrix':matrix,
        'review_declarations':sorted(r['reviews'],key=lambda v:v['id']),'review_authenticity':'NOT_EXTERNALLY_AUTHENTICATED_NO_APPROVAL_GRANTED',
        'coverage':coverage,'missing_evidence':list(GAPS),'reason_codes':sorted(reasons),'calendar_modifications':False,
        'interpretation':'DECLARED_CLAIMS_AND_REVIEW_SCOPE_NOT_BROKER_AUTHENTICATION_OR_QUALIFICATION'})


def validate_source_report(report):
    keys(report,'status reason_codes qualification ordinary_strategy_inputs_allowed review_packets_allowed historical_validation historical_comparisons exness safety source_review_version kind review_mode data_kind registry_file_fingerprint registry_payload_sha256 context manifest_reference local_manifest_inspection evidence_inventory source_assessments claim_matrix review_declarations review_authenticity coverage missing_evidence calendar_modifications interpretation sha256')
    check_hash(report);need(report['kind']==REPORT_KIND and type(report['source_review_version']) is int and report['source_review_version']==1,'SOURCE_REPORT_SCHEMA_INVALID')
    gate=qualification_gate(None)
    for k,v in gate.items():need(report[k]==v,'SOURCE_REVIEW_SAFETY_DOWNGRADE') if k!='reason_codes' else None
    need(set(REQUIRED_CODES)|{'INDEPENDENT_QUALIFICATION_REQUIRED'}<=set(report['reason_codes']),'SOURCE_BLOCKERS_REMOVED')
    return True
