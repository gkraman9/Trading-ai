"""Read-only native CSV import diagnostics; mechanical checks never grant approval."""
from copy import deepcopy
from hashlib import sha256
from io import StringIO
from math import isfinite
from pathlib import Path
import csv,json,tempfile
from iat.replay_dataset import read_bytes,strict_json,local_file,load_dataset,utc,DatasetError
from iat.chart_benchmark import keys,require,text,identifier,hashed,check_hash,write_new,read_json
from iat.historical_replay import alignment_check,safety
from iat.pilot_qualification import qualify_historical,ITEMS
from iat.review_pilot import pilot_warmup,_configs
from iat.quality import assess_candles
from iat.session_config import compile_session_config
from iat.intelligence.models import iso,IntelligenceConfig
from iat.intelligence.strategy_replay import digest

ACTIONS={
 'IMPORT_SPEC_INVALID':'Use the complete v1 import schema; declare every mapping and metadata field explicitly.',
 'LOCAL_USE_AUTHORIZATION_REQUIRED':'Obtain permission for this local export and record the operator declaration before importing.',
 'SOURCE_UNAVAILABLE':'Supply the declared local file inside the import-spec directory.',
 'EXPORT_PRECEDES_CANDLE_CLOSE':'Set an honest export/retrieval cutoff after every supplied candle closes; obtain a later closed export.',
 'SOURCE_CHANGED_DURING_IMPORT':'Freeze the export and rerun into a new package.',
 'CSV_MAPPING_INVALID':'Inspect headers and map each column explicitly, including intentionally ignored columns.',
 'CSV_INVALID':'Provide a UTF-8 CSV with consistent rows and unique headers; do not repair it silently.',
 'UTC_TIMESTAMP_REQUIRED':'Re-export verified UTC interval openings with Z or +00:00. Do not assume broker/server local time.',
 'LOCAL_TIME_UNSUPPORTED':'This version does not convert IANA/local timestamps or resolve DST folds. Supply documented UTC timestamps.',
 'UNEXPECTED_MISSING_BARS':'Obtain the missing in-session bars from the provider; do not fill or interpolate prices.',
 'OHLC_INVALID':'Obtain a corrected source export with finite positive and consistent OHLC.',
 'VOLUME_INVALID':'Declare finite nonnegative volume and its semantics, or explicitly map no volume.',
 'VOLUME_SEMANTICS_UNKNOWN':'Document whether the supplied volume is tick or real volume; OHLC checks do not establish that meaning.',
 'PRICE_BASIS_MISMATCH':'Supply matching, explicitly documented BID, ASK or MID data for both frames.',
 'SYMBOL_MISMATCH':'Supply a single-instrument XAUUSD export; mapped symbol values must match the explicit instrument declaration.',
 'FEED_MISMATCH':'Supply native M1 and M5 from the same declared feed.',
 'NATIVE_M1_M5_REQUIRED':'Supply native same-feed M1 and M5. Derived or unknown M5 is not accepted as native.',
 'FINALITY_UNKNOWN':'Supply explicit per-row completion flags or documented closed-export finality metadata.',
 'FINALITY_CONTRACT_UNSUPPORTED':'The current session gate supports MT5_POSITION_1_ELAPSED only. Supply its evidence or validate a provider-specific adapter; do not relabel another contract.',
 'BAR_NOT_COMPLETE':'Exclude unfinished bars only by obtaining a correctly scoped closed-bar export; this tool will not drop rows.',
 'CORRECTIONS_UNRESOLVED':'Document provider correction status/version and any prior export checksum; never deduplicate or patch rows here.',
 'CALENDAR_REQUIRED':'Supply the dated v2 calendar covering all warm-up/evaluation and its source documentation.',
 'CALENDAR_INVALID':'Fix the calendar schema/hash/symbol through the existing session v2 workflow.',
 'EVIDENCE_MISSING':'Supply the referenced provider document and exact checksum for independent review.',
 'EVIDENCE_CHECKSUM_MISMATCH':'Preserve the reviewed document bytes or create a new evidence package.',
 'PILOT_WARMUP_INSUFFICIENT':'Export more preceding history for both frames under the unchanged pilot lookbacks.',
 'M1_M5_ALIGNMENT_UNESTABLISHED':'Supply sufficient matching native M1/M5 coverage for the declared evaluation interval.',
 'INDEPENDENT_REVIEW_REQUIRED':'An independent person must review evidence and supply their own sign-off; preparation never approves a source.',
 'SELF_APPROVAL_FORBIDDEN':'The independent reviewer code must differ from the preparer code; actual independence also requires human oversight.',
 'PACKAGE_INVALID':'Verify package.lock.json and all original/normalized/evidence files; never edit a locked package.',
 'REVIEWED_MANIFEST_CHANGED_DATA':'A reviewed manifest may change only evidence-review attestations, not source, prices, dates or calendar.',
}


class ImportFailure(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def need(value,code):
    if not value:raise ImportFailure(code)


def _json_bytes(value):return (json.dumps(value,indent=2,allow_nan=False)+'\n').encode('utf-8')


def inspect_csv(path):
    raw=read_bytes(path)
    try:
        reader=csv.reader(StringIO(raw.decode('utf-8-sig')),strict=True);headers=next(reader)
        need(headers and len(headers)==len(set(headers)),'CSV_MAPPING_INVALID')
        count=0
        for row in reader:
            need(len(row)==len(headers),'CSV_INVALID');count+=1;need(count<=5000,'CSV_INVALID')
    except (UnicodeError,csv.Error,StopIteration) as exc:raise ImportFailure('CSV_INVALID') from exc
    return {'inspection_version':1,'source_sha256':sha256(raw).hexdigest(),'byte_count':len(raw),'headers':headers,'row_count':count,
            'interpretation':'HEADER_INSPECTION_ONLY_NOT_DATA_QUALIFICATION','safety':safety(),'exness':'BLOCKED'}


def _spec(path):
    raw=read_bytes(path);s=strict_json(raw)
    keys(s,'import_version dataset_kind preparer_code authorized_local_use source timestamp utc_range evaluation warmup frames calendar evidence')
    need(type(s['import_version']) is int and s['import_version']==1,'IMPORT_SPEC_INVALID')
    need(s['authorized_local_use'] is True,'LOCAL_USE_AUTHORIZATION_REQUIRED');identifier(s['preparer_code'])
    require(s['dataset_kind'] in ('SYNTHETIC_FIXTURE','INDEPENDENT_HISTORICAL'))
    keys(s['source'],'provider_entity feed_id instrument price_basis reference retrieved_at_utc curation_id')
    source=s['source'];text(source['provider_entity']);text(source['feed_id']);identifier(source['curation_id'])
    require(source['instrument']=='XAUUSD');require(source['price_basis'] in ('BID','ASK','MID','UNKNOWN'));utc(source['retrieved_at_utc'])
    keys(s['timestamp'],'format timezone convention')
    need(s['timestamp']['timezone']=='UTC','LOCAL_TIME_UNSUPPORTED')
    need(s['timestamp']['format']=='ISO8601' and s['timestamp']['convention']=='INTERVAL_OPEN_UTC','UTC_TIMESTAMP_REQUIRED')
    for name in ('utc_range','evaluation'):
        keys(s[name],'start end');require(utc(s[name]['start'])<utc(s[name]['end']))
    keys(s['warmup'],'M1 M5');keys(s['frames'],'M1 M5');keys(s['evidence'],' '.join(ITEMS))
    for tf,f in s['frames'].items():
        keys(f,'file columns ignored_columns price_basis feed_id origin volume_kind finality corrections')
        keys(f['columns'],'timestamp open high low close volume complete symbol price_basis feed_id')
        required=[f['columns'][k] for k in ('timestamp','open','high','low','close')]
        require(all(isinstance(v,str) and v for v in required))
        require(all(v is None or isinstance(v,str) and v for v in f['columns'].values()))
        require(len([v for v in f['columns'].values() if v is not None])==len(set(v for v in f['columns'].values() if v is not None)))
        require(isinstance(f['ignored_columns'],list) and len(set(f['ignored_columns']))==len(f['ignored_columns']))
        require(not set(v for v in f['columns'].values() if v is not None)&set(f['ignored_columns']))
        require(f['price_basis'] in ('BID','ASK','MID','UNKNOWN'));text(f['feed_id'])
        require(f['origin'] in ('NATIVE_SAME_FEED','AGGREGATED_FROM_M1','UNKNOWN'))
        require(f['volume_kind'] in ('NONE','TICK','REAL','UNKNOWN'))
        require((f['columns']['volume'] is None)==(f['volume_kind']=='NONE'))
        keys(f['finality'],'policy provider_contract true_token false_token reference')
        text(f['finality']['provider_contract'])
        require(f['finality']['policy'] in ('PER_ROW_BOOLEAN','DOCUMENTED_CLOSED_EXPORT','UNKNOWN'))
        need(f['columns']['complete'] is None or f['finality']['policy']=='PER_ROW_BOOLEAN','FINALITY_UNKNOWN')
        if f['finality']['reference'] is not None:text(f['finality']['reference'])
        keys(f['corrections'],'status reference previous_source_sha256')
        require(f['corrections']['status'] in ('NO_KNOWN_CORRECTIONS_DECLARED','PROVIDER_CORRECTED','UNKNOWN'))
        if f['corrections']['reference'] is not None:text(f['corrections']['reference'])
    return raw,s


def _parse_frame(raw,f,source):
    try:
        reader=csv.DictReader(StringIO(raw.decode('utf-8-sig')),strict=True);columns=f['columns']
        expected=[v for v in columns.values() if v is not None]+f['ignored_columns']
        need(reader.fieldnames and len(reader.fieldnames)==len(set(reader.fieldnames)) and set(reader.fieldnames)==set(expected),'CSV_MAPPING_INVALID')
        rows=[];volumes=[];complete=[]
        for record in reader:
            need(set(record)==set(reader.fieldnames) and all(v is not None for v in record.values()),'CSV_INVALID')
            for key,expected_value,code in (('symbol',source['instrument'],'SYMBOL_MISMATCH'),('price_basis',f['price_basis'],'PRICE_BASIS_MISMATCH'),('feed_id',f['feed_id'],'FEED_MISMATCH')):
                if columns[key] is not None:need(record[columns[key]]==expected_value,code)
            try:at=utc(record[columns['timestamp']])
            except ValueError as exc:raise ImportFailure('UTC_TIMESTAMP_REQUIRED') from exc
            try:values={k:float(record[columns[k]]) for k in ('open','high','low','close')}
            except ValueError as exc:raise ImportFailure('OHLC_INVALID') from exc
            need(all(isfinite(v) and v>0 for v in values.values()),'OHLC_INVALID')
            need(values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high'],'OHLC_INVALID')
            rows.append(dict(timestamp=iso(at),**values));need(len(rows)<=5000,'CSV_INVALID')
            if columns['volume'] is not None:
                try:v=float(record[columns['volume']])
                except ValueError as exc:raise ImportFailure('VOLUME_INVALID') from exc
                need(isfinite(v) and v>=0,'VOLUME_INVALID');volumes.append({'timestamp':iso(at),'volume':v})
            if f['finality']['policy']=='PER_ROW_BOOLEAN':
                need(columns['complete'] is not None,'FINALITY_UNKNOWN')
                yes,no=f['finality']['true_token'],f['finality']['false_token']
                need(isinstance(yes,str) and isinstance(no,str) and yes!=no and yes and no,'FINALITY_UNKNOWN')
                need(record[columns['complete']] in (yes,no),'FINALITY_UNKNOWN');complete.append(record[columns['complete']]==yes)
        need(len(rows)>=3,'CSV_INVALID')
        return rows,volumes,complete
    except (UnicodeError,csv.Error) as exc:raise ImportFailure('CSV_INVALID') from exc


def _csv_bytes(rows):
    out=StringIO(newline='');writer=csv.DictWriter(out,fieldnames=['timestamp','open','high','low','close'],lineterminator='\n')
    writer.writeheader();writer.writerows(rows);return out.getvalue().encode('utf-8')


def analyze_import(spec_path):
    """No source mutations. Temporary canonical files only exercise unchanged contracts."""
    report={'assistant_version':1,'kind':'HISTORICAL_DATA_QUALIFICATION_ASSISTANT','status':'DATA_NOT_QUALIFIED',
        'classification':'UNRESOLVED','mechanical':{'status':'BLOCKED','frames':{},'alignment':None,'warmup':None,
          'finality_assurance':'DECLARED_FLAGS_OR_DOCUMENTED_EXPORT_NOT_INDEPENDENTLY_VERIFIED'},
        'source_files':{},'normalized_files':{},'spec_sha256':None,'canonical_spec_sha256':None,'dataset_id':None,
        'evidence':{},'issues':[],'gate':None,'candidate_available':False,'configuration_hashes':_configs()[2],
        'independent_signoff':{'decision':'PENDING','reviewer_code':None,'independent_review_attested':False},
        'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','safety':safety(),'exness':'BLOCKED'}
    payloads={};mechanical=[];pending=[];root=Path(spec_path).resolve().parent;s=None
    def issue(code,stage='MECHANICAL'):
        report['issues'].append({'code':code,'stage':stage,'severity':'ERROR' if stage=='MECHANICAL' else 'UNRESOLVED',
            'action':ACTIONS.get(code,'Review this existing validation reason using the quality/session documentation; correct the source or supply missing evidence.')})
        (mechanical if stage=='MECHANICAL' else pending).append(code)
    try:
        raw,s=_spec(spec_path);report.update(spec_sha256=sha256(raw).hexdigest(),canonical_spec_sha256=digest(s),
            classification='SYNTHETIC_ONLY' if s['dataset_kind']=='SYNTHETIC_FIXTURE' else 'DECLARED_HISTORICAL_UNQUALIFIED')
        payloads['import-spec.json']=raw;rows={};checksums={};calendar=None
        if utc(s['utc_range']['end'])>utc(s['source']['retrieved_at_utc']):issue('EXPORT_PRECEDES_CANDLE_CLOSE')
        for name,item in s['evidence'].items():
            keys(item,'file sha256 reference')
            report['evidence'][name]={'status':'PENDING','declared_reference':item['reference'],'document_sha256':None}
            if item['file'] is None:issue('EVIDENCE_MISSING','EVIDENCE');continue
            try:doc=read_bytes(local_file(root,item['file']))
            except DatasetError:issue('EVIDENCE_MISSING','EVIDENCE');continue
            if not doc or sha256(doc).hexdigest()!=item['sha256']:issue('EVIDENCE_CHECKSUM_MISMATCH','EVIDENCE');continue
            text(item['reference']);payloads['evidence/'+name+'.bin']=doc
            report['evidence'][name]['document_sha256']=sha256(doc).hexdigest()
        if s['calendar'] is None:issue('CALENDAR_REQUIRED')
        else:
            keys(s['calendar'],'file sha256');content=read_bytes(local_file(root,s['calendar']['file']))
            if sha256(content).hexdigest()!=s['calendar']['sha256']:issue('CALENDAR_INVALID')
            else:
                try:
                    calendar=compile_session_config(strict_json(content));need(calendar.version==2 and calendar.symbol=='XAUUSD','CALENDAR_INVALID')
                    payloads['calendar.json']=content
                except (ValueError,TypeError,KeyError):issue('CALENDAR_INVALID')
        for tf,f in s['frames'].items():
            content=read_bytes(local_file(root,f['file']));checksum=sha256(content).hexdigest();checksums[tf]=checksum
            report['source_files'][tf]={'file':f['file'],'sha256':checksum,'byte_count':len(content),
                'feed_id':f['feed_id'],'price_basis':f['price_basis'],'origin_declaration':f['origin'],
                'corrections_declaration':deepcopy(f['corrections']),'volume_kind':f['volume_kind']}
            payloads['source/'+tf.lower()+'.csv']=content
            if f['price_basis']!=s['source']['price_basis'] or f['price_basis']=='UNKNOWN':issue('PRICE_BASIS_MISMATCH')
            if f['feed_id']!=s['source']['feed_id']:issue('FEED_MISMATCH')
            if f['origin']!='NATIVE_SAME_FEED':issue('NATIVE_M1_M5_REQUIRED')
            correction=f['corrections'];previous=correction['previous_source_sha256']
            if previous is not None:
                import re
                need(isinstance(previous,str) and re.fullmatch('[a-f0-9]{64}',previous) is not None,'CORRECTIONS_UNRESOLVED')
            if correction['status']=='UNKNOWN' or correction['status']=='PROVIDER_CORRECTED' and (not correction['reference'] or previous is None or previous==checksum):issue('CORRECTIONS_UNRESOLVED')
            try:bars,volumes,complete=_parse_frame(content,f,s['source'])
            except ImportFailure as exc:issue(exc.code);continue
            rows[tf]=bars;canonical=_csv_bytes(bars);payloads[tf.lower()+'.csv']=canonical
            report['normalized_files'][tf]={'file_sha256':sha256(canonical).hexdigest(),'normalized_ohlc_sha256':digest(bars),'closed_or_declared_row_count':len(bars),
                'volume_sha256':digest(volumes) if volumes else None}
            if volumes:
                payloads[tf.lower()+'.volume.json']=_json_bytes({'volume_kind':f['volume_kind'],'rows':volumes})
                if f['volume_kind']=='UNKNOWN':issue('VOLUME_SEMANTICS_UNKNOWN','EVIDENCE')
            finality=f['finality']
            if finality['provider_contract']!='MT5_POSITION_1_ELAPSED':issue('FINALITY_CONTRACT_UNSUPPORTED')
            known=finality['policy']=='PER_ROW_BOOLEAN' and bool(complete) and all(complete)
            if finality['policy']=='DOCUMENTED_CLOSED_EXPORT':known=bool(finality['reference']) and report['evidence']['finality']['document_sha256'] is not None
            if complete and not all(complete):issue('BAR_NOT_COMPLETE')
            if not known:issue('FINALITY_UNKNOWN')
            quality=assess_candles(bars,tf,utc(s['utc_range']['end']),session_calendar=calendar,observed_finality=known).to_dict()
            report['mechanical']['frames'][tf]=quality
            for d in quality['diagnostics']:
                if d['severity']=='ERROR':issue(d['code'])
        if set(rows)=={'M1','M5'}:
            source=s['source'];manifest={'version':2,'symbol':'XAUUSD','dataset_kind':s['dataset_kind'],
                'source':{'name':source['provider_entity'],'reference':source['reference'],'retrieved_at_utc':source['retrieved_at_utc'],
                    'curation_id':source['curation_id'],'independent_review':'PENDING'},
                'utc_range':s['utc_range'],'frames':{tf:{'file':tf.lower()+'.csv','sha256':sha256(payloads[tf.lower()+'.csv']).hexdigest()} for tf in rows},
                'calendar':{'file':'calendar.json','sha256':sha256(payloads['calendar.json']).hexdigest()} if 'calendar.json' in payloads else None,
                'finality_attested':False,'evaluation':s['evaluation'],'warmup':s['warmup'],
                'lineage':{'feed_id':source['feed_id'],'price_basis':source['price_basis'],'timestamp_convention':'INTERVAL_OPEN_UTC',
                    'm5_origin':s['frames']['M5']['origin'],'raw_sha256':digest(checksums)},
                'evidence_review':{k:{'status':'PENDING','reference':None,'reason_code':'INDEPENDENT_EVIDENCE_REVIEW_REQUIRED'} for k in ('usage','instrument','timestamp','price_basis','calendar','finality')}}
            payloads['candidate-manifest.json']=_json_bytes(manifest)
            with tempfile.TemporaryDirectory(prefix='iat candidate ') as folder:
                target=Path(folder)
                for name in ('m1.csv','m5.csv','calendar.json','candidate-manifest.json'):
                    if name in payloads:(target/name).write_bytes(payloads[name])
                ds=load_dataset(target/'candidate-manifest.json');report['dataset_id']=digest(ds.metadata)
                report['mechanical']['warmup']=pilot_warmup(ds)
                if not report['mechanical']['warmup']['sufficient']:issue('PILOT_WARMUP_INSUFFICIENT')
                if all(v['valid'] for v in report['mechanical']['frames'].values()):
                    alignment=alignment_check(ds,IntelligenceConfig().epsilon);report['mechanical']['alignment']=alignment
                    if alignment['mismatch_count'] or not alignment['comparable_m5_bars'] or not alignment['evaluation']['coverage_sufficient']:issue('M1_M5_ALIGNMENT_UNESTABLISHED')
                report['gate']=qualify_historical(target/'candidate-manifest.json')
                report['candidate_available']=True
            template={'qualification_version':1,'dataset_id':report['dataset_id'],'interval':s['utc_range'],
                'provider_entity':source['provider_entity'],'feed_id':source['feed_id'],'instrument':'XAUUSD','price_basis':source['price_basis'],
                'reviewer_code':None,'independent_review_attested':False,'reviewed_at_utc':None,'decision':'PENDING',
                'evidence':{k:{'status':'PENDING','file':'evidence/'+k+'.bin' if 'evidence/'+k+'.bin' in payloads else None,
                    'sha256':report['evidence'][k]['document_sha256'],'reference':s['evidence'][k]['reference'],
                    'scope':s['utc_range'],'explanation':'Independent review required; no evidence approved by import.'} for k in ITEMS}}
            payloads['independent-review.template.json']=_json_bytes(hashed(template))
        for tf,f in s['frames'].items():
            if tf in checksums and sha256(read_bytes(local_file(root,f['file']))).hexdigest()!=checksums[tf]:issue('SOURCE_CHANGED_DURING_IMPORT')
    except ImportFailure as exc:issue(exc.code)
    except DatasetError as exc:issue(exc.code)
    except (ValueError,TypeError,KeyError,OverflowError):issue('IMPORT_SPEC_INVALID')
    except OSError:issue('SOURCE_UNAVAILABLE')
    issue('INDEPENDENT_REVIEW_REQUIRED','QUALIFICATION')
    report['mechanical']['status']='PASS' if not mechanical else 'BLOCKED'
    # No independent approval can originate from this assistant, even for a mechanically valid import.
    report['issues']=sorted({(i['code'],i['stage']):i for i in report['issues']}.values(),key=lambda i:(i['stage'],i['code']))
    return hashed(report),payloads


def validate_import(spec_path):return analyze_import(spec_path)[0]


def prepare_package(spec_path,destination):
    report,files=analyze_import(spec_path);root=Path(destination);root.mkdir(exist_ok=False)
    files['report.json']=_json_bytes(report)
    # A byte-preserving private package. Original files are never opened for writing.
    for name,data in sorted(files.items()):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        _write_bytes(path,data)
    lock=hashed({'package_version':1,'files':{name:sha256(data).hexdigest() for name,data in sorted(files.items())},
                 'report_sha256':report['sha256'],'qualification_status':'DATA_NOT_QUALIFIED'})
    write_new(root/'package.lock.json',lock);return report


def _write_bytes(path,data):
    import os
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.iat-import-',delete=False) as f:
            temporary=Path(f.name);f.write(data);f.flush();os.fsync(f.fileno())
        if os.name=='nt':os.rename(temporary,path)
        else:os.link(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def assess_candidate(package_directory,reviewed_manifest,independent_review):
    """Validate externally prepared attestations; this function cannot create them."""
    result={'assistant_version':1,'status':'DATA_NOT_QUALIFIED','reason_codes':[],
        'gate':None,'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','safety':safety(),'exness':'BLOCKED'}
    try:
        root=Path(package_directory).resolve();lock=read_json(root/'package.lock.json');check_hash(lock)
        require(lock['package_version']==1 and lock['qualification_status']=='DATA_NOT_QUALIFIED')
        for name,checksum in lock['files'].items():require(sha256(read_bytes(local_file(root,name))).hexdigest()==checksum)
        report=read_json(root/'report.json');check_hash(report);require(report['sha256']==lock['report_sha256'])
        require(report['mechanical']['status']=='PASS' and report['classification']=='DECLARED_HISTORICAL_UNQUALIFIED')
        require(report['configuration_hashes']==_configs()[2],'Package rules/configurations changed')
        original=read_json(root/'candidate-manifest.json');reviewed=read_json(reviewed_manifest)
        a,b=deepcopy(original),deepcopy(reviewed)
        for obj in (a,b):
            obj['source']['independent_review']=None;obj['finality_attested']=None;obj['evidence_review']=None
        if a!=b:raise ImportFailure('REVIEWED_MANIFEST_CHANGED_DATA')
        reviewer=read_json(independent_review);spec=read_json(root/'import-spec.json')
        if isinstance(reviewer.get('reviewer_code'),str) and reviewer['reviewer_code'].casefold()==spec['preparer_code'].casefold():raise ImportFailure('SELF_APPROVAL_FORBIDDEN')
        # The independent reviewed manifest must reference these locked canonical files.
        ds=load_dataset(reviewed_manifest)
        pending=load_dataset(root/'candidate-manifest.json')
        require(ds.metadata['checksums']==pending.metadata['checksums'] and ds.metadata['session_config_sha256']==pending.metadata['session_config_sha256'])
        require(pilot_warmup(ds)['sufficient'])
        result['gate']=qualify_historical(reviewed_manifest,independent_review)
        if result['gate']['status']=='HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED':result['status']='HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED'
        else:result['reason_codes']=result['gate']['reason_codes']
    except ImportFailure as exc:result['reason_codes']=[exc.code]
    except (OSError,ValueError,KeyError,TypeError):result['reason_codes']=['PACKAGE_INVALID']
    return hashed(result)
