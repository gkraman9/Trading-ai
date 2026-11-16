"""Stream private archives; qualify only a bounded, explicit UTC pilot selection."""
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import csv,json,sqlite3,tempfile
from iat.chart_benchmark import (hashed,check_hash,write_new,read_json,require,packet_html)
from iat.qualification_assistant import (_spec,_parse_record,ImportFailure,prepare_package,assess_candidate,_write_bytes,need)
from iat.replay_dataset import local_file,read_bytes,utc,DatasetError,load_dataset
from iat.intelligence.models import iso
from iat.intelligence.strategy_replay import digest
from iat.review_pilot import register_plan,generate_pilot,annotation_v2_template
from iat.historical_replay import safety

CHUNK_BYTES=1024*1024
MAX_ARCHIVE_ROWS=10_000_000
MAX_LINE_CHARACTERS=1024*1024


def file_fingerprint(path):
    """Bounded-memory SHA-256; never reads an archive into a byte array."""
    result=sha256();size=0
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(CHUNK_BYTES):result.update(chunk);size+=len(chunk)
    return {'sha256':result.hexdigest(),'byte_count':size}


def window_contract(start,end,evaluation_start):
    a,b,e=(utc(v) for v in (start,end,evaluation_start))
    require(a<e<b and all(t.timestamp()%300==0 for t in (a,b,e)),'Explicit five-minute UTC window boundaries required')
    return {'start':iso(a),'end':iso(b),'evaluation_start':iso(e),
            'eligibility':'OPEN_GE_START_AND_CLOSE_LE_END','max_selected_rows_per_frame':5000}


def _bounded_lines(handle):
    while line:=handle.readline(MAX_LINE_CHARACTERS+1):
        need(len(line)<=MAX_LINE_CHARACTERS,'CSV_LINE_LIMIT')
        yield line


def stream_archive(path,*,timeframe=None,frame_spec=None,source=None,window=None,selected_path=None):
    """Global order/identity integrity, disk-indexed duplicates; gaps are not assumed missing sessions."""
    result={'inspection_version':1,'status':'BLOCKED','source_fingerprint':None,'headers':None,'row_count':0,
        'timestamp_range':None,'selected_row_count':0,'declarations':None,'errors':{},'examples':[],
        'raw_gap_count':0,'gap_examples':[],'session_claim':'SELECTED_WINDOW_ONLY_FULL_ARCHIVE_SESSIONS_NOT_ESTABLISHED',
        'scan_complete':False,'status_scope':'STRUCTURAL_SCAN_NOT_FULL_SESSION_COMPLETENESS_OR_QUALIFICATION',
        'metadata_status':'DECLARATIONS_REQUIRED' if frame_spec is None else 'EXPLICIT_OPERATOR_DECLARATIONS_NOT_VERIFIED'}
    errors=Counter();target=None;writer=None;conn=None
    def error(code,row=None):
        errors[code]+=1
        if len(result['examples'])<25:result['examples'].append({'code':code,'row':row})
    try:
        before=file_fingerprint(path);result['source_fingerprint']=before
        with tempfile.TemporaryDirectory(prefix='iat stream index ') as folder:
            conn=sqlite3.connect(str(Path(folder)/'timestamps.sqlite'))
            conn.execute('PRAGMA cache_size=-1024');conn.execute('PRAGMA temp_store=FILE');conn.execute('CREATE TABLE seen (stamp TEXT PRIMARY KEY)')
            try:
                with Path(path).open('r',encoding='utf-8-sig',newline='') as handle:
                    reader=csv.reader(_bounded_lines(handle),strict=True);headers=next(reader);result['headers']=headers
                    require(0<len(headers)<=128 and len(headers)==len(set(headers)))
                    if frame_spec is not None:
                        require(timeframe in ('M1','M5') and isinstance(source,dict),'Explicit timeframe/source required')
                        result['declarations']={'timeframe':timeframe,'provider_entity':source['provider_entity'],'instrument':source['instrument'],
                            'feed_id':frame_spec['feed_id'],'price_basis':frame_spec['price_basis'],'origin':frame_spec['origin'],
                            'provider_contract':frame_spec['finality']['provider_contract'],'corrections':deepcopy(frame_spec['corrections'])}
                        expected=[v for v in frame_spec['columns'].values() if v is not None]+frame_spec['ignored_columns']
                        require(set(headers)==set(expected),'CSV mapping invalid')
                        duration=timedelta(minutes=1 if timeframe=='M1' else 5)
                    if selected_path is not None:
                        target=Path(selected_path).open('x',encoding='utf-8',newline='');writer=csv.writer(target,lineterminator='\n');writer.writerow(headers)
                    previous=first=last=None;limit_hit=False
                    for index,values in enumerate(reader,1):
                        result['row_count']=index
                        if index>MAX_ARCHIVE_ROWS:limit_hit=True;error('ARCHIVE_SCAN_LIMIT');break
                        if len(values)!=len(headers):error('CSV_COLUMNS_INVALID',index);continue
                        if frame_spec is None:continue
                        record=dict(zip(headers,values))
                        try:
                            at=utc(record[frame_spec['columns']['timestamp']]);stamp=iso(at)
                            if at.timestamp()%duration.total_seconds():error('TIMEFRAME_MISALIGNED',index)
                            if conn.execute('INSERT OR IGNORE INTO seen VALUES (?)',(stamp,)).rowcount==0:error('TIMESTAMP_DUPLICATE',index)
                            if previous is not None:
                                if at<previous:error('TIMESTAMP_OUT_OF_ORDER',index)
                                elif at-previous>duration:
                                    result['raw_gap_count']+=1
                                    if len(result['gap_examples'])<25:result['gap_examples'].append({'after_utc':iso(previous),'next_open_utc':stamp})
                            previous=at;first=at if first is None else min(first,at);last=at if last is None else max(last,at)
                            if source is not None and at+duration>utc(source['retrieved_at_utc']):error('CLOSE_AFTER_DECLARED_EXPORT',index)
                            _bar,_volume,complete=_parse_record(record,frame_spec,source)
                            if complete is False:error('BAR_NOT_COMPLETE',index)
                            if window is not None and utc(window['start'])<=at and at+duration<=utc(window['end']):
                                result['selected_row_count']+=1
                                if result['selected_row_count']>5000:error('SELECTED_WINDOW_ROW_LIMIT',index)
                                elif writer is not None:writer.writerow(values)
                        except ImportFailure as exc:error(exc.code,index)
                        except (ValueError,KeyError,OverflowError):error('UTC_TIMESTAMP_OR_RECORD_INVALID',index)
                    result['scan_complete']=not limit_hit
                    if first is not None:result['timestamp_range']={'first_open_utc':iso(first),'last_open_utc':iso(last),'last_close_utc':iso(last+duration)}
            finally:
                if target is not None:target.close();target=None
                conn.close();conn=None
        if file_fingerprint(path)!=before:error('SOURCE_CHANGED_DURING_INSPECTION')
    except ImportFailure as exc:error(exc.code)
    except (OSError,ValueError,TypeError,KeyError,OverflowError,csv.Error,StopIteration,sqlite3.Error):error('SOURCE_OR_SCHEMA_UNAVAILABLE')
    finally:
        if target is not None:target.close()
        if conn is not None:conn.close()
    result['errors']=dict(sorted(errors.items()))
    result['status']='PASS' if not errors and frame_spec is not None and result['row_count'] else 'INSPECTED_METADATA_UNVERIFIED' if not errors else 'BLOCKED'
    return hashed(result)


def _evidence_checklist(report):
    return {'checklist_version':1,'status':'DATA_NOT_QUALIFIED','required':{
        'provenance_and_usage':['AUTHORIZED_NATIVE_M1_AND_NATIVE_M5','PROVIDER_ENTITY_FEED_AND_BASIS','OFFLINE_USE_AND_UPSTREAM_RIGHTS','ARCHIVE_AND_SELECTION_HASHES'],
        'sessions':['DATED_SOURCE_SPECIFIC_CALENDAR_INCLUDING_WARMUP','HOLIDAY_EXCEPTION_MAINTENANCE_AND_DST_EVIDENCE'],
        'finality_and_corrections':['SUPPORTED_FINALITY_CONTRACT','COMPLETE_BARS_AND_PROVIDER_CORRECTION_HISTORY'],
        'independent_approval':['DISTINCT_INDEPENDENT_REVIEWER','EXPLICIT_APPROVAL_BOUND_TO_REVIEWED_DATASET','ALL_REQUIRED_DOCUMENTS_VERIFIED'],
        'blind_review':['PREDECLARED_EVALUATION_TIMES_AND_ROSTER','AT_LEAST_TWO_INDEPENDENT_REVIEWERS','SUBMIT_BEFORE_REVEAL']},
        'documents':report['evidence'] if report else None,
        'missing_document_names':[name for name,value in report['evidence'].items() if value['document_sha256'] is None] if report else None,
        'unverified_document_names':list(report['evidence']) if report else None,
        'independent_approval':'PENDING',
        'assistant_issues':report['issues'] if report else [],'automatically_approved':False,'safety':safety(),'exness':'BLOCKED'}


def _publish_manifest(root,record):
    """Lock all generated artifacts last. No input or prior output can be overwritten."""
    files={p.relative_to(root).as_posix():file_fingerprint(p)['sha256'] for p in sorted(root.rglob('*')) if p.is_file()}
    manifest=hashed({'preparation_version':1,**record,'files':files,'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','safety':safety(),'exness':'BLOCKED'})
    write_new(root/'preparation-manifest.json',manifest);return manifest


def prepare_pilot(spec_path,m1_path,m5_path,destination,*,start,end,evaluation_start,dry_run=False):
    """A source selection bridge to PR #21, never a qualification shortcut."""
    window=window_contract(start,end,evaluation_start);root=Path(destination);root.mkdir(exist_ok=False)
    selection=root/'selection'
    if not dry_run:selection.mkdir()
    spec=None;reasons=[];reports={};candidate_report=None;inspection_allowed=True
    try:
        _raw,spec=_spec(spec_path) if spec_path else (None,None)
        if _raw is not None:_write_bytes(root/'original-import-spec.json',_raw)
    except ImportFailure as exc:
        reasons.append(exc.code);inspection_allowed=exc.code!='LOCAL_USE_AUTHORIZATION_REQUIRED'
    except (ValueError,OSError,KeyError,TypeError):reasons.append('IMPORT_METADATA_INVALID')
    if spec is None:reasons.append('IMPORT_METADATA_REQUIRED')
    sources={'M1':m1_path,'M5':m5_path};bindings={}
    for tf,path in sources.items():
        if not inspection_allowed:continue
        if path is None or not Path(path).is_file():reasons.append('MISSING_NATIVE_'+tf);continue
        output=selection/(tf.lower()+'.csv') if not dry_run and spec is not None else None
        reports[tf]=stream_archive(path,timeframe=tf,frame_spec=spec['frames'][tf] if spec else None,source=spec['source'] if spec else None,window=window,selected_path=output)
        bindings[tf]={'path':str(Path(path).resolve()),'fingerprint':reports[tf]['source_fingerprint']}
        if reports[tf]['status']!='PASS':reasons.append(tf+'_ARCHIVE_INTEGRITY_NOT_ESTABLISHED')
        if spec is not None and not reports[tf]['selected_row_count']:reasons.append(tf+'_SELECTED_HISTORY_UNAVAILABLE')
    if dry_run:reasons.append('DRY_RUN_NO_NORMALIZATION')
    # No bounded validator call unless both native sources and complete declarations are supplied.
    if not reasons and spec is not None:
        staged=deepcopy(spec);staged['utc_range']={k:window[k] for k in ('start','end')}
        staged['evaluation']={'start':window['evaluation_start'],'end':window['end']}
        staged['warmup']={tf:{'start':window['start'],'end':window['evaluation_start']} for tf in ('M1','M5')}
        original_root=Path(spec_path).resolve().parent
        for tf in ('M1','M5'):staged['frames'][tf]['file']=tf.lower()+'.csv'
        if staged['calendar'] is not None:
            try:
                data=read_bytes(local_file(original_root,spec['calendar']['file']));_write_bytes(selection/'calendar.json',data);staged['calendar']['file']='calendar.json'
            except (OSError,ValueError):reasons.append('CALENDAR_SOURCE_UNAVAILABLE')
        for name,item in staged['evidence'].items():
            if item['file'] is None:continue
            try:
                data=read_bytes(local_file(original_root,spec['evidence'][name]['file']));_write_bytes(selection/(name+'.bin'),data);item['file']=name+'.bin'
            except (OSError,ValueError):item.update(file=None,sha256=None,reference=None)
        if not reasons:
            write_new(selection/'import.json',staged);candidate_report=prepare_package(selection/'import.json',root/'candidate-package')
            if candidate_report['mechanical']['status']!='PASS':reasons.append('SELECTED_WINDOW_MECHANICAL_CHECKS_FAILED')
    for tf,binding in bindings.items():
        if file_fingerprint(binding['path'])!=binding['fingerprint']:reasons.append(tf+'_SOURCE_CHANGED_AFTER_INSPECTION')
    inspection={'inspection_version':1,'sources':reports,'scope':window,
        'external_metadata_claims':'NOT_ASSUMED_USE_ACTUAL_INSPECTED_VALUES','safety':safety(),'exness':'BLOCKED'}
    write_new(root/'source-inspection.json',inspection)
    alignment={'alignment_audit_version':1,'status':'NOT_RUN' if candidate_report is None else candidate_report['mechanical']['status'],
        'scope':window,'full_archive_sessions':'NOT_ESTABLISHED_OUTSIDE_SELECTION',
        'frames':candidate_report['mechanical']['frames'] if candidate_report else None,
        'warmup':candidate_report['mechanical']['warmup'] if candidate_report else None,
        'm1_to_native_m5_comparison':candidate_report['mechanical']['alignment'] if candidate_report else None,
        'aggregation_role':'DIAGNOSTIC_ONLY_NATIVE_M5_NEVER_REPLACED','safety':safety(),'exness':'BLOCKED'}
    write_new(root/'alignment-audit.json',alignment);write_new(root/'evidence-checklist.json',_evidence_checklist(candidate_report))
    from iat.historical_session_boundaries import package_boundary_research
    write_new(root/'session-boundary-research.json',package_boundary_research(root/'candidate-package',window['start'],window['end']))
    reasons.append('INDEPENDENT_QUALIFICATION_REQUIRED')
    readiness={'readiness_version':1,'status':'BLOCKED','qualification':'DATA_NOT_QUALIFIED','reason_codes':sorted(set(reasons)),
        'review_packets_created':False,'evaluation_timestamps':None,'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','safety':safety(),'exness':'BLOCKED'}
    write_new(root/'review-readiness.json',readiness)
    return _publish_manifest(root,{'mode':'DRY_RUN' if dry_run else 'PREPARE','classification':candidate_report['classification'] if candidate_report else 'UNQUALIFIED',
        'window':window,'archive_bindings':bindings,'archive_binding_id':digest({tf:b['fingerprint'] for tf,b in bindings.items()}),
        'selected_dataset_id':candidate_report['dataset_id'] if candidate_report else None,'readiness':readiness})


def handoff_review(preparation_directory,reviewed_manifest,independent_review,pilot_spec,destination):
    """Recheck frozen sources and approvals, lock the plan, then reuse closed-only packets."""
    root=Path(preparation_directory).resolve();result={'readiness_version':1,'status':'BLOCKED','qualification':'DATA_NOT_QUALIFIED',
        'reason_codes':[],'review_packets_created':False,'evaluation_timestamps':None,'historical_validation':'PENDING',
        'historical_comparisons':'NOT_RUN','safety':safety(),'exness':'BLOCKED'}
    output=Path(destination);output.mkdir(exist_ok=False)
    try:
        manifest=read_json(root/'preparation-manifest.json');check_hash(manifest)
        require(manifest['preparation_version']==1)
        need(manifest['mode']=='PREPARE','DRY_RUN_NO_NORMALIZATION')
        need(manifest['classification']!='SYNTHETIC_ONLY','SYNTHETIC_ONLY_NOT_REAL_QUALIFICATION')
        for name,checksum in manifest['files'].items():require(file_fingerprint(local_file(root,name))['sha256']==checksum,'Preparation artifacts changed')
        need('M1' in manifest['archive_bindings'],'MISSING_NATIVE_M1')
        need('M5' in manifest['archive_bindings'],'MISSING_NATIVE_M5')
        for binding in manifest['archive_bindings'].values():need(file_fingerprint(binding['path'])==binding['fingerprint'],'FROZEN_SOURCE_CHANGED')
        inspections=read_json(root/'source-inspection.json')['sources'];require(all(r['status']=='PASS' for r in inspections.values()))
        need(reviewed_manifest is not None and independent_review is not None and Path(reviewed_manifest).is_file() and Path(independent_review).is_file(),'INDEPENDENT_APPROVAL_REQUIRED')
        qualification=assess_candidate(root/'candidate-package',reviewed_manifest,independent_review)
        write_new(output/'qualification.json',qualification)
        if qualification['status']!='HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED':
            result['reason_codes']=qualification['reason_codes'];result['reason_codes']=result['reason_codes'] or ['INDEPENDENT_QUALIFICATION_REQUIRED']
        else:
            need(pilot_spec is not None and Path(pilot_spec).is_file(),'PREDECLARED_PILOT_SPEC_REQUIRED')
            plan,q=register_plan(reviewed_manifest,read_json(pilot_spec),independent_review)
            if plan is None:result['reason_codes']=q['reason_codes']
            else:
                require(plan['qualified_interval']=={'start':manifest['window']['start'],'end':manifest['window']['end']})
                # Persist registration before accessing IAT assessments or later observations.
                private=output/'private';private.mkdir();write_new(private/'plan.json',plan);(private/'receipts').mkdir()
                bundle=generate_pilot(plan,reviewed_manifest,independent_review);write_new(private/'bundle.json',bundle)
                packets=output/'reviewer-packets';packets.mkdir()
                for packet in bundle['benchmark']['packets']:
                    name=packet['packet_id'];write_new(packets/(name+'.json'),packet);write_new(packets/(name+'.html'),packet_html(packet))
                    for reviewer in plan['reviewer_codes']:write_new(private/(name+'.'+reviewer+'.template.json'),annotation_v2_template(packet,reviewer))
                write_new(output/'PACKETS_COMPLETE.json',{'pilot_version':1,'plan_sha256':plan['sha256'],'mode':'REAL','signal':'WAIT','execution_allowed':False,'exness':'BLOCKED'})
                result.update(status='READY_OPERATOR_ATTESTED',qualification=qualification['status'],review_packets_created=True,evaluation_timestamps=plan['timestamps'])
    except ImportFailure as exc:result['reason_codes']=[exc.code]
    except (ValueError,OSError,TypeError,KeyError,OverflowError):result['reason_codes']=['PREPARATION_OR_APPROVAL_INVALID']
    write_new(output/'review-readiness.json',result);return result
