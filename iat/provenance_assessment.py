"""Source-bound provenance gap analysis; evidence labels never replace qualification gates."""
from collections import Counter
from datetime import timedelta
from hashlib import sha256
from math import isfinite
from pathlib import Path

from iat.analysis import validate_candles
from iat.replay_dataset import load_dataset, local_file, strict_json, utc, DatasetError
from iat.historical_replay import dataset_preflight, alignment_check, safety
from iat.historical_evidence_manifest import local_path
from iat.pilot_qualification import qualify_historical
from iat.qualification_assistant import analyze_import
from iat.independent_source_evidence import read_registry, review_registry, validate_source_report
from iat.scenario_replay import validate_scenario_replay, MAX_AUDIT_BYTES
from iat.replay_diagnostics import generate_replay_diagnostics
from iat.intelligence.models import IntelligenceConfig, iso
from iat.intelligence.scenario_assessment import need, plain
from iat.intelligence.strategy_replay import digest

VERSION = 1
KIND = 'HISTORICAL_PROVENANCE_GAP_ANALYSIS_V1'
LABELS = ('VERIFIED', 'PARTIALLY_VERIFIED', 'UNVERIFIED', 'CONTRADICTED', 'NOT_APPLICABLE')
BROKER_COMMIT = '09cf0f13c649b522447e1f5a1796bf52e2ff2519'
BROKER_SHA = 'faeff4d9ce854a5d33e45dcd495c8678a104f0a175505d8f376bdbba1ea2356a'


def broker_reference():
    path = Path(__file__).resolve().parents[1] / 'config/reference/exness-2026-11-11-13.relayed.json'
    value = strict_json(path.read_bytes())
    need(value.get('sha256') == BROKER_SHA and digest({k:v for k,v in value.items() if k != 'sha256'}) == BROKER_SHA
         and value['source_commit'] == BROKER_COMMIT, 'PINNED_BROKER_REFERENCE_INVALID')
    return value


def _read(path, limit=4*1024*1024):
    p = local_path(path)
    need(p.is_file() and not p.is_symlink(), 'LOCAL_INPUT_UNAVAILABLE_OR_UNSAFE')
    with p.open('rb') as handle:
        raw = handle.read(limit+1)
    need(len(raw) <= limit, 'LOCAL_INPUT_SIZE_LIMIT')
    return raw


def _state(label, codes=()):
    return {'verification_status': label, 'reason_codes': sorted(set(codes))}


def inspect_dataset_integrity(dataset):
    """Mechanical facts only; missing UTC slots are not automatically missing session bars."""
    frames = {}
    for tf, seconds in (('M1',60),('M5',300)):
        rows = dataset.rows[tf]; times = [utc(r['timestamp']) for r in rows]
        duplicates = len(times)-len(set(times))
        reversed_pairs = sum(b<a for a,b in zip(times,times[1:]))
        grid = sum(t.timestamp()%seconds != 0 for t in times)
        invalid = sum(not all(isfinite(r[k]) and r[k]>0 for k in ('open','high','low','close')) or
            r['low']>min(r['open'],r['close']) or r['high']<max(r['open'],r['close']) or r['high']<r['low'] for r in rows)
        gaps = sum(max(0,int((b-a).total_seconds()/seconds)-1) for a,b in zip(times,times[1:])) if not (duplicates or reversed_pairs or grid) else None
        try:validate_candles(rows); validator = 'VERIFIED'
        except ValueError:validator = 'CONTRADICTED'
        labels = Counter(); restricted = unknown = 0
        calendar = dataset.calendar
        for row in rows:
            if calendar is not None and getattr(calendar,'version',1)==2:
                if utc(row['timestamp']).timestamp()%seconds:
                    labels['TIMEFRAME_MISALIGNED']+=1;unknown+=1;continue
                bar = calendar.classify_bar(utc(row['timestamp']),tf,research=True)
                labels[bar['classification']] += 1
                restricted += bar['phase_states'] != ['FULL_TRADING']
                unknown += not bar['schedule_verified']
        expected_missing = None
        if (calendar is not None and getattr(calendar,'version',1)==2 and not calendar.assurance_codes
                and calendar.coverage_start <= min(times) and max(times)+timedelta(seconds=seconds) <= calendar.coverage_end):
            expected = set(calendar.expected_opens(min(times),max(times)+timedelta(seconds=seconds),timedelta(seconds=seconds)))
            expected_missing = len(expected-set(times))
        frames[tf] = {'row_count':len(rows),'duplicate_timestamps':duplicates,'out_of_order_pairs':reversed_pairs,
            'misaligned_openings':grid,'invalid_ohlc_rows':invalid,'missing_utc_grid_intervals':gaps,
            'missing_declared_calendar_ordinary_intervals':expected_missing,
            'closed_after_declared_retrieval_count':sum(t+timedelta(seconds=seconds)>utc(dataset.metadata['source']['retrieved_at_utc']) for t in times),
            'existing_candle_validator':validator,'declared_calendar_classifications':dict(sorted(labels.items())),
            'restricted_phase_bars':restricted if calendar is not None else None,
            'unverified_calendar_bars':unknown if calendar is not None else None,
            'partial_session_bars':sum(v for k,v in labels.items() if k.startswith('PARTIAL_') or k=='CROSSES_SESSION_BREAK') if calendar is not None else None}
    suitable = all(not any(f[k] for k in ('duplicate_timestamps','out_of_order_pairs','misaligned_openings','invalid_ohlc_rows')) for f in frames.values())
    alignment = alignment_check(dataset,IntelligenceConfig().epsilon) if suitable else None
    return {'frames':frames,'alignment':alignment,
            'alignment_status':'UNVERIFIED' if alignment is None or not alignment['comparable_m5_bars'] else
                'CONTRADICTED' if alignment['mismatch_count'] else 'PARTIALLY_VERIFIED' if alignment['uncovered_m5_bars'] else 'VERIFIED',
            'alignment_assurance':'INTERNAL_AGGREGATION_ONLY' if dataset.metadata.get('lineage',{}).get('m5_origin')=='AGGREGATED_FROM_M1' else 'DECLARED_LINEAGE_NOT_INDEPENDENT_FEED_AUTHENTICATION'}


def compare_relayed_broker_boundaries(dataset, broker_binding):
    """Conditional comparison only; never installs a calendar or infers broker identity."""
    source = broker_reference()
    result = {'source_commit':BROKER_COMMIT,'reference_sha256':BROKER_SHA,
        'applicability':'UNVERIFIED','assurance':'CONDITIONAL_ON_OPERATOR_BINDING_AND_RELAYED_CLAIMS',
        'reason_codes':[],'evaluated_bars':None,'closed_quote_conflicts':None,'partial_bars':None,
        'close_only_bars':None,'friday_ambiguous_bars':None,'observations':[]}
    if broker_binding is None or broker_binding['broker']=='UNKNOWN':
        result['reason_codes']=['DATASET_BROKER_AFFILIATION_UNESTABLISHED'];return result
    if broker_binding['broker']=='NON_EXNESS':
        result.update(applicability='NOT_APPLICABLE',reason_codes=['NON_EXNESS_DATASET']);return result
    a,b = utc(source['interval_utc']['start']),utc(source['interval_utc']['end_exclusive'])
    if utc(dataset.metadata['utc_range']['end'])<=a or utc(dataset.metadata['utc_range']['start'])>=b:
        result.update(applicability='NOT_APPLICABLE',reason_codes=['OUTSIDE_RELAYED_EVIDENCE_DATES']);return result
    counts = Counter()
    for tf, minutes in (('M1',1),('M5',5)):
        for bar in dataset.rows[tf]:
            opened = utc(bar['timestamp']); end = opened+timedelta(minutes=minutes)
            if not a <= opened < b:continue
            counts['evaluated_bars']+=1
            midnight=opened.replace(hour=0,minute=0,second=0,microsecond=0)
            close=midnight+timedelta(hours=21,minutes=58); resume=midnight+timedelta(hours=23); normal=resume+timedelta(minutes=2)
            cut=max(0,(min(end,resume)-max(opened,close)).total_seconds())
            restricted=max(0,(min(end,normal)-max(opened,resume)).total_seconds())
            friday=opened.weekday()==4 and end>resume
            label='OUTSIDE_SPECIFIC_BOUNDARY_CLAIMS'; quote_seconds=None; permission=None
            if friday:label='FRIDAY_REOPEN_UNRESOLVED';counts['friday_ambiguous_bars']+=1
            elif cut:
                quote_seconds=minutes*60-cut;permission=False
                if cut==minutes*60:label='CONFLICTS_WITH_REPORTED_CLOSED_QUOTES';counts['closed_quote_conflicts']+=1
                else:label='PARTIAL_QUOTE_INTERVAL';counts['partial_bars']+=1
            elif restricted:
                label='QUOTED_WITH_CLOSE_ONLY_PORTION';quote_seconds=minutes*60;permission=False;counts['close_only_bars']+=1
            elif opened>=normal:
                label='POST_2302_OPENING_PERMISSION_UNCONFIRMED'
            if label!='OUTSIDE_SPECIFIC_BOUNDARY_CLAIMS':
                result['observations'].append({'timeframe':tf,'open_utc':iso(opened),'end_utc':iso(end),
                    'classification':label,'reported_quote_seconds':quote_seconds,'new_position_permission':permission,
                    'iat_execution_allowed':False})
    for key in ('evaluated_bars','closed_quote_conflicts','partial_bars','close_only_bars','friday_ambiguous_bars'):result[key]=counts[key]
    result.update(applicability='PARTIALLY_VERIFIED',reason_codes=['BROKER_REPLY_OPERATOR_RELAYED_NOT_AUTHENTICATED','POST_2302_AND_FRIDAY_PERMISSIONS_UNRESOLVED'])
    if counts['closed_quote_conflicts']:result['applicability']='CONTRADICTED'
    return result


def assess_historical_provenance(manifest_path=None, *, broker_binding_path=None, import_spec_path=None,
                                 independent_review_path=None, source_registry_path=None, replay_report_path=None):
    """Inspect authorized local files only. Existing qualification decisions are never changed."""
    reference=broker_reference(); refs={}; errors=[]
    paths={'manifest':manifest_path,'broker_binding':broker_binding_path,'import_spec':import_spec_path,
           'independent_review':independent_review_path,'source_registry':source_registry_path,'replay_report':replay_report_path}
    def read_role(role):
        if paths[role] is None:return None
        raw=_read(paths[role],MAX_AUDIT_BYTES if role=='replay_report' else 4*1024*1024)
        refs[role]={'file_sha256':sha256(raw).hexdigest(),'payload_sha256':None,'binding':'UNVERIFIED'}
        return strict_json(raw)
    dataset=None; imported=None; registry=None; replay=None; binding=None; qualification=None
    source_summary=None; replay_summary=None; transform=_state('UNVERIFIED',['ORIGINAL_TO_NORMALIZED_CHAIN_UNAVAILABLE'])
    try:
        if manifest_path is not None:
            read_role('manifest');dataset=load_dataset(local_path(manifest_path))
            need(dataset.metadata['manifest_sha256']==refs['manifest']['file_sha256'],'MANIFEST_CHANGED_DURING_INSPECTION')
            refs['manifest'].update(payload_sha256=digest(dataset.metadata),binding='VERIFIED')
    except (ValueError,TypeError,KeyError,OSError,OverflowError) as exc:
        errors.append({'scope':'manifest','code':exc.code if isinstance(exc,DatasetError) else 'MANIFEST_INVALID_OR_UNAVAILABLE'})
    m=dataset.metadata if dataset else None;dataset_id=digest(m) if m else None
    if broker_binding_path is not None:
        try:
            binding=read_role('broker_binding')
            need(isinstance(binding,dict) and set(binding)=={'binding_version','dataset_id','manifest_sha256','broker'}
                 and type(binding['binding_version']) is int and binding['binding_version']==1
                 and binding['broker'] in ('EXNESS','NON_EXNESS','UNKNOWN'),'BROKER_BINDING_SCHEMA_INVALID')
            need(m is not None and binding['dataset_id']==dataset_id and binding['manifest_sha256']==m['manifest_sha256'],'BROKER_BINDING_DATASET_MISMATCH')
            refs['broker_binding'].update(payload_sha256=digest(binding),binding='VERIFIED')
        except (ValueError,TypeError,KeyError,OSError):
            binding=None;errors.append({'scope':'broker_binding','code':'BROKER_BINDING_INVALID_OR_CONFLICTING'})
    if import_spec_path is not None:
        try:
            read_role('import_spec');imported,_=analyze_import(local_path(import_spec_path))
            need(m is not None and set(imported['normalized_files'])=={'M1','M5'},'NORMALIZATION_UNAVAILABLE')
            need(all(imported['normalized_files'][tf]['normalized_ohlc_sha256']==m['checksums'][tf]['normalized_ohlc_sha256'] for tf in ('M1','M5')),'NORMALIZED_DATA_MISMATCH')
            need(all(imported['source_files'][tf]['feed_id']==m.get('lineage',{}).get('feed_id') and imported['source_files'][tf]['price_basis']==m.get('lineage',{}).get('price_basis') for tf in ('M1','M5')),'NORMALIZATION_FEED_OR_BASIS_MISMATCH')
            need(digest({tf:imported['source_files'][tf]['sha256'] for tf in ('M1','M5')})==m.get('lineage',{}).get('raw_sha256'),'ORIGINAL_SOURCE_SET_MISMATCH')
            transform=_state('VERIFIED',['EXISTING_IMPORT_NORMALIZATION_REPRODUCED_NOT_SOURCE_AUTHENTICATION'])
            refs['import_spec'].update(payload_sha256=imported['sha256'],binding='VERIFIED')
        except (ValueError,TypeError,KeyError,OSError):
            transform=_state('CONTRADICTED',['IMPORT_SPEC_CANNOT_BE_BOUND_TO_DATASET'])
            errors.append({'scope':'import_spec','code':'TRANSFORMATION_REFERENCE_INVALID_OR_MISMATCHED'})
    if dataset is not None:
        qualification=qualify_historical(local_path(manifest_path),local_path(independent_review_path) if independent_review_path else None)
    if independent_review_path is not None:
        try:
            review=read_role('independent_review')
            need(m is not None and qualification is not None and qualification['human_review_sha256']==refs['independent_review']['file_sha256'] and review['dataset_id']==dataset_id,'INDEPENDENT_REVIEW_NOT_BOUND')
            refs['independent_review'].update(payload_sha256=review['sha256'],binding='VERIFIED')
        except (ValueError,TypeError,KeyError,OSError):errors.append({'scope':'independent_review','code':'INDEPENDENT_REVIEW_INVALID_OR_UNBOUND'})
    if source_registry_path is not None:
        try:
            read_role('source_registry');registry,_=read_registry(local_path(source_registry_path))
            source_report=review_registry(registry,artifact_root=Path(source_registry_path).resolve().parent)
            validate_source_report(source_report)
            normalized={tf:m['checksums'][tf]['file_sha256'] for tf in ('M1','M5')} if m else None
            original={tf:imported['source_files'][tf]['sha256'] for tf in ('M1','M5')} if transform['verification_status']=='VERIFIED' else None
            declared={tf:registry['manifest_reference']['dataset_fingerprints'][tf] for tf in ('M1','M5')}
            need(m is not None and all(utc(registry['context']['interval'][k])==utc(m['utc_range'][k]) for k in ('start','end')) and declared in (normalized,original),'SOURCE_REGISTRY_SCOPE_MISMATCH')
            if binding and binding['broker']=='EXNESS':need(registry['context']['broker'].casefold()=='exness','REGISTRY_BROKER_SCOPE_MISMATCH')
            if binding and binding['broker']=='NON_EXNESS':need(registry['context']['broker'].casefold()!='exness','REGISTRY_BROKER_SCOPE_MISMATCH')
            if m['session_config_sha256'] is not None:
                need(registry['manifest_reference']['dataset_fingerprints']['calendar']==m['session_config_sha256'],'REGISTRY_CALENDAR_SCOPE_MISMATCH')
            refs['source_registry'].update(payload_sha256=source_report['sha256'],binding='VERIFIED')
            source_summary={'status':'CONTRADICTED' if any(c['classification']=='CONFLICTING_EVIDENCE' for c in source_report['claim_matrix']) else 'PARTIALLY_VERIFIED','claim_classifications':dict(sorted(Counter(c['classification'] for c in source_report['claim_matrix']).items())),
                            'reason_codes':source_report['reason_codes'],'assurance':'REVIEW_DECLARATIONS_NOT_EXTERNAL_AUTHENTICATION',
                            'dataset_binding_fields':['M1','M5','interval']+(['calendar'] if m['session_config_sha256'] is not None else []),
                            'unverified_references':['historical_evidence_manifest','diagnostic']+(['calendar'] if m['session_config_sha256'] is None else [])}
        except (ValueError,TypeError,KeyError,OSError):errors.append({'scope':'source_registry','code':'SOURCE_REGISTRY_INVALID_OR_UNBOUND'})
    if replay_report_path is not None:
        try:
            replay=read_role('replay_report');validate_scenario_replay(replay)
            need(m is not None and replay['replay_manifest'] is not None and replay['replay_manifest']['dataset']==m,'REPLAY_DATASET_MISMATCH')
            diagnostic=generate_replay_diagnostics(replay)
            refs['replay_report'].update(payload_sha256=replay['sha256'],binding='VERIFIED')
            replay_summary={'replay_sha256':replay['sha256'],'diagnostics_sha256':diagnostic['sha256'],
                'observation_count':diagnostic['observation_count'],'snapshot_status_counts':diagnostic['snapshot_status_counts'],
                'evidence_chain_coverage':diagnostic['coverage']['complete_required_chain']}
        except (ValueError,TypeError,KeyError,OSError):errors.append({'scope':'replay_report','code':'REPLAY_REPORT_INVALID_OR_UNBOUND'})
    mechanical=inspect_dataset_integrity(dataset) if dataset else None
    preflight=dataset_preflight(dataset) if dataset else None
    broker=compare_relayed_broker_boundaries(dataset,binding) if dataset else None
    inventory=None
    if m:
        original_known=transform['verification_status']=='VERIFIED'
        inventory={'dataset_id':dataset_id,'source_name':m['source']['name'],'acquisition_reference':m['source']['reference'],
            'instrument':m['symbol'],'dataset_kind':m['dataset_kind'],'coverage':m['utc_range'],
            'timestamp_basis':m.get('lineage',{}).get('timestamp_convention','UNKNOWN'),'normalized_timezone':'UTC',
            'original_timezone_declaration':'UTC' if original_known else 'UNKNOWN',
            'declared_price_basis':m.get('lineage',{}).get('price_basis','UNKNOWN'),'spread_availability':'UNKNOWN',
            'declared_feed_id':m.get('lineage',{}).get('feed_id'),
            'declared_raw_lineage_sha256':m.get('lineage',{}).get('raw_sha256'),
            'm5_origin':m.get('lineage',{}).get('m5_origin','UNKNOWN'),
            'source_authenticity':m['source_authenticity'],'declared_broker':binding['broker'] if binding else 'UNKNOWN',
            'frames':{tf:{'row_count':m['coverage'][tf]['candle_count'],'start_utc':m['coverage'][tf]['start_utc'],
                'end_utc':m['coverage'][tf]['end_utc'],'supplied_csv_sha256':m['checksums'][tf]['file_sha256'],
                'normalized_ohlc_sha256':m['checksums'][tf]['normalized_ohlc_sha256'],
                'original_import_sha256':imported['source_files'][tf]['sha256'] if original_known else None,
                'corrections_declaration':imported['source_files'][tf]['corrections_declaration']['status'] if original_known else 'UNKNOWN',
                'previous_source_sha256':imported['source_files'][tf]['corrections_declaration']['previous_source_sha256'] if original_known else None,
                'correction_reference_supplied':bool(imported['source_files'][tf]['corrections_declaration']['reference']) if original_known else None} for tf in ('M1','M5')},
            'normalization':transform,
            'usage_evidence_declaration':plain(m.get('evidence_review',{}).get('usage'))}
    # Detect mutations without ever modifying original data or silently refreshing a checksum.
    if m:
        try:
            manifest=strict_json(_read(manifest_path))
            for tf in ('M1','M5'):
                raw=_read(local_file(Path(manifest_path).resolve().parent,manifest['frames'][tf]['file']))
                need(sha256(raw).hexdigest()==m['checksums'][tf]['file_sha256'],'SOURCE_BYTES_CHANGED')
        except (ValueError,TypeError,KeyError,OSError):errors.append({'scope':'manifest','code':'SOURCE_CHANGED_DURING_ASSESSMENT'})
    for role,path in paths.items():
        if path is not None and role in refs:
            try:need(sha256(_read(path,MAX_AUDIT_BYTES if role=='replay_report' else 4*1024*1024)).hexdigest()==refs[role]['file_sha256'],'INPUT_CHANGED')
            except (ValueError,OSError):errors.append({'scope':role,'code':'INPUT_CHANGED_DURING_ASSESSMENT'})
    references=[{'reference_id':role.upper()+':'+v['file_sha256'],'role':role,**v} for role,v in sorted(refs.items())]
    broker_ref={'reference_id':'BROKER_NOTE:'+BROKER_SHA,'role':'broker_note','file_sha256':None,
                'payload_sha256':BROKER_SHA,'binding':'REFERENCE_ONLY'}
    references.append(broker_ref)
    codes={e['code'] for e in errors}
    gaps=[]
    def gap(code,layer,status,required,available,reason,action,roles=()):
        need(status in LABELS,'EVIDENCE_LABEL_INVALID')
        ids=sorted(r['reference_id'] for r in references if r['role'] in roles)
        scope={'dataset_id':dataset_id,'interval':m['utc_range'] if m else None,'timeframes':['M1','M5']}
        gaps.append({'gap_id':digest([VERSION,dataset_id,refs.get('manifest',{}).get('file_sha256'),code]),
            'code':code,'layer':layer,'scope':scope,'required_evidence':required,'available_evidence':available,
            'verification_status':status,'blocking_reason':reason,'next_verification_action':action,'source_references':ids})
    file_status='VERIFIED' if m and not any(c in codes for c in ('SOURCE_CHANGED_DURING_ASSESSMENT','INPUT_CHANGED_DURING_ASSESSMENT')) else 'CONTRADICTED' if any(c in codes for c in ('DATASET_CHECKSUM_MISMATCH','SOURCE_CHANGED_DURING_ASSESSMENT','INPUT_CHANGED_DURING_ASSESSMENT')) else 'UNVERIFIED'
    gap('FILE_INTEGRITY','MECHANICAL',file_status,'Checksummed manifest and exact supplied CSV bytes.',
        ['EXACT_SUPPLIED_BYTES_HASHED'] if m else [],None if file_status=='VERIFIED' else 'SOURCE_HASHES_UNESTABLISHED_OR_MISMATCHED',
        'Preserve the original export; supply missing hashes or obtain a corrected export.',['manifest'])
    clean=bool(mechanical and all(f['existing_candle_validator']=='VERIFIED' and not f['misaligned_openings'] and not f['closed_after_declared_retrieval_count'] for f in mechanical['frames'].values()))
    gap('CANDLE_INTEGRITY','MECHANICAL','VERIFIED' if clean else 'CONTRADICTED' if mechanical else 'UNVERIFIED',
        'Ordered unique UTC-aligned positive finite mathematically valid OHLC.', ['NORMALIZED_ROWS_INSPECTED'] if mechanical else [],
        None if clean else 'CANDLE_INTEGRITY_UNESTABLISHED','Obtain intact provider rows; never sort, deduplicate or interpolate prices.',['manifest'])
    align_status=mechanical['alignment_status'] if mechanical else 'UNVERIFIED'
    gap('CROSS_FRAME_CONSISTENCY','MECHANICAL',align_status,'Five eligible M1 bars per comparable M5, with declared lineage.',
        [mechanical['alignment_assurance']] if mechanical else [],None if align_status=='VERIFIED' else 'CROSS_FRAME_CHECK_INCOMPLETE_OR_MISMATCHED',
        'Resolve source coverage/mismatches. Derived M5 demonstrates internal aggregation only.',['manifest'])
    continuity='UNVERIFIED'
    if mechanical:
        f=list(mechanical['frames'].values())
        continuity='CONTRADICTED' if any(x['missing_declared_calendar_ordinary_intervals'] for x in f) else 'VERIFIED' if all(x['missing_declared_calendar_ordinary_intervals']==0 for x in f) else 'PARTIALLY_VERIFIED'
    gap('COVERAGE_CONTINUITY','MECHANICAL',continuity,'Dated calendar coverage plus expected and supplied intervals.',
        ['UTC_GRID_COUNTS'] if mechanical else [],None if continuity=='VERIFIED' else 'EXPECTED_SESSION_DENOMINATOR_UNESTABLISHED_OR_GAPS',
        'Establish dated sessions before treating UTC grid gaps as missing broker candles.',['manifest'])
    gap('NORMALIZATION_TRACE','MECHANICAL',transform['verification_status'],'Original files and reproducible mapping to normalized rows.',transform['reason_codes'],
        None if transform['verification_status']=='VERIFIED' else 'NORMALIZATION_CHAIN_NOT_ESTABLISHED','Provide the existing import specification and exact original source files.',['manifest','import_spec'])
    gap('SOURCE_ORIGIN','PROVENANCE','PARTIALLY_VERIFIED' if m else 'UNVERIFIED','Identifiable provider/feed and file-bound acquisition evidence.',
        ['OPERATOR_SOURCE_DECLARATION'] if m else [],'ACQUISITION_AUTHENTICATION_PENDING','Independently verify acquisition and feed identity; labels and URLs alone are insufficient.',['manifest','source_registry','independent_review'])
    gap('SOURCE_AUTHENTICITY','PROVENANCE','CONTRADICTED' if source_summary and source_summary['status']=='CONTRADICTED' else 'PARTIALLY_VERIFIED' if source_summary or refs.get('independent_review',{}).get('binding')=='VERIFIED' else 'UNVERIFIED',
        'Authenticated acquisition/source evidence and independent confirmation.', ['BOUND_REVIEW_DECLARATIONS'] if source_summary or refs.get('independent_review',{}).get('binding')=='VERIFIED' else [],
        'INDEPENDENT_AUTHENTICITY_NOT_ESTABLISHED','Authenticate original source/acquisition evidence; do not equate document hashes with authenticity.',['source_registry','independent_review'])
    for code,field in [('TIMESTAMP_BASIS','timestamp_convention'),('PRICE_BASIS','price_basis')]:
        declared=m.get('lineage',{}).get(field) if m else None
        known=declared not in (None,'UNKNOWN','PENDING')
        gap(code,'PROVENANCE','PARTIALLY_VERIFIED' if known else 'UNVERIFIED','Dataset-specific provider documentation, not inferred chart conventions.',
            [declared] if known else [],code+'_INDEPENDENT_EVIDENCE_PENDING','Verify the actual export convention and source mapping.',['manifest','source_registry','independent_review'])
    gap('SPREAD_INFORMATION','PROVENANCE','UNVERIFIED','Explicit spread/Bid-Ask information if required by later research.',[],None,
        'Keep spread unknown; do not fabricate zero spread or reconstruct Ask from Bid.',['manifest','import_spec'])
    usage=m.get('evidence_review',{}).get('usage',{}) if m else {}
    gap('USAGE_RIGHTS','PROVENANCE','PARTIALLY_VERIFIED' if usage.get('reference') else 'UNVERIFIED',
        'File-bound offline-use permission with provider applicability.', ['DECLARED_USAGE_REFERENCE'] if usage.get('reference') else [],
        'INDEPENDENT_USAGE_REVIEW_PENDING','Verify permitted offline use and redistribution separately; keep raw data private.',['manifest','independent_review','source_registry'])
    bs=broker['applicability'] if broker else 'UNVERIFIED'
    gap('BROKER_SESSION_COMPATIBILITY','PROVENANCE',bs,'Dataset-bound broker identity, dates and authenticated session evidence.',
        broker['reason_codes'] if broker else [],None if bs=='NOT_APPLICABLE' else 'RELAYED_SESSION_SCOPE_OR_COMPATIBILITY_UNRESOLVED',
        'Resolve Friday reopening and post-23:02 permissions; never apply Exness rules to a different feed.',['manifest','broker_binding','broker_note'])
    gap('CANDLE_FINALITY','PROVENANCE','CONTRADICTED' if imported and any(i['code']=='BAR_NOT_COMPLETE' for i in imported['issues']) else 'PARTIALLY_VERIFIED' if dataset and dataset.finality_attested else 'UNVERIFIED',
        'Provider finality and capture-completeness evidence for exact dated bars.', ['FINALITY_DECLARED'] if dataset and dataset.finality_attested else [],
        'FINALITY_AND_CAPTURE_COMPLETENESS_PENDING','Verify closed-bar completeness independently, not merely elapsed time.',['manifest','import_spec','independent_review'])
    corrections=inventory and all(f['corrections_declaration']!='UNKNOWN' for f in inventory['frames'].values())
    gap('CORRECTIONS','PROVENANCE','PARTIALLY_VERIFIED' if corrections else 'UNVERIFIED',
        'Provider correction policy, revision identity and prior-file traceability.', ['OPERATOR_CORRECTIONS_DECLARATION'] if corrections else [],
        'CORRECTION_EVIDENCE_PENDING','Obtain provider correction/version history and authenticate any replacement export.',['import_spec','source_registry','independent_review'])
    gate=qualification['status'] if qualification else 'DATA_NOT_QUALIFIED'
    gap('INDEPENDENT_QUALIFICATION','INDEPENDENT','PARTIALLY_VERIFIED' if gate=='HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED' else 'UNVERIFIED',
        'Existing independent review and all source/data checks, without self-approval.', [gate],
        'EXISTING_GATE_REMAINS_SEPARATE','Complete the existing qualification process; this report never approves historical data.',['independent_review','source_registry','manifest'])
    ref_bad=any(e['scope'] in refs for e in errors)
    ref_missing=any(path is not None and role not in refs for role,path in paths.items())
    gap('EVIDENCE_REFERENCES','MECHANICAL','CONTRADICTED' if ref_bad else 'UNVERIFIED' if ref_missing else 'PARTIALLY_VERIFIED' if source_summary and source_summary['unverified_references'] else 'VERIFIED' if m and refs else 'UNVERIFIED',
        'Unaltered input hashes and evidence references bound to this exact dataset.',
        [r['reference_id'] for r in references if r['binding']=='VERIFIED'],
        'EVIDENCE_REFERENCE_CONFLICT' if ref_bad else 'REFERENCE_INPUTS_UNAVAILABLE' if ref_missing or m is None else 'NESTED_REGISTRY_REFERENCES_PENDING' if source_summary and source_summary['unverified_references'] else None,'Resolve mismatched or missing evidence references; never reuse another dataset review. ',paths.keys())
    result={'assessment_version':VERSION,'kind':KIND,'dataset_id':dataset_id,'inventory':inventory,'references':references,
        'input_errors':sorted(errors,key=lambda e:(e['scope'],e['code'])),'mechanical':mechanical,
        'existing_preflight':{'status':preflight['status'],'reason_codes':preflight['reason_codes']} if preflight else None,
        'existing_qualification':{'status':gate,'reason_codes':qualification['reason_codes'] if qualification else ['DATASET_UNAVAILABLE']},
        'source_review':source_summary,'replay_evidence':replay_summary,'broker_reference':plain(reference),
        'broker_comparison':broker,'gaps':sorted(gaps,key=lambda g:g['code']),
        'evidence_coverage':{'gap_count':len(gaps),'label_counts':{k:sum(g['verification_status']==k for g in gaps) for k in LABELS},
            'independent_authenticity':{'numerator':None,'denominator':None,'status':'UNVERIFIED'}},
        'qualification':'DATA_NOT_QUALIFIED','historical_validation':'PENDING','historical_comparisons':'NOT_RUN',
        'exness':'BLOCKED','mode':'READ_ONLY_SHADOW','signal':'WAIT','execution_allowed':False,'safety':safety(),
        'interpretation':'EVIDENCE_ASSESSMENT_LABELS_NOT_PRODUCTION_QUALIFICATION_STATES'}
    return dict(result,sha256=digest(result))


def validate_provenance_assessment(report, manifest_path=None, **inputs):
    need(isinstance(report,dict) and type(report.get('assessment_version')) is int and report['assessment_version']==VERSION,'PROVENANCE_SCHEMA_UNSUPPORTED')
    need(report.get('sha256')==digest({k:v for k,v in report.items() if k!='sha256'}),'PROVENANCE_CHECKSUM_INVALID')
    expected=assess_historical_provenance(manifest_path,**inputs)
    need(set(report)==set(expected) and report==expected and report['sha256']==expected['sha256'],'PROVENANCE_SEMANTIC_OR_SOURCE_MISMATCH')
    return True


def provenance_text(report):
    lines=['IAT historical provenance gaps v1 - PRIVATE READ-ONLY RESEARCH',
           'Dataset: '+str(report['dataset_id']), 'Evidence labels (not approval): '+str(report['evidence_coverage']['label_counts'])]
    for gap in report['gaps']:
        lines.append(gap['code']+': '+gap['verification_status']+' | '+str(gap['blocking_reason'])+' | '+gap['next_verification_action'])
    lines.append('Exness BLOCKED; WAIT; execution_allowed=false; historical validation PENDING; comparisons NOT_RUN.')
    return '\n'.join(lines)+'\n'
