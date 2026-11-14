"""Blinded offline chart-review benchmark v1; analyst agreement is not accuracy."""
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from html import escape
from itertools import combinations
from math import isfinite
from pathlib import Path
import json,os,re,tempfile
from iat.replay_dataset import load_dataset,utc,strict_json,read_bytes
from iat.journal_dataset_replay import run_journal_manifest,validate_journal_dataset_report
from iat.intelligence.strategy_replay import digest
from iat.intelligence.models import iso
from iat.historical_replay import safety

REGIMES=('TREND_UP','TREND_DOWN','RANGE','TRANSITION','UNKNOWN')
SCENARIOS=('BULLISH','BEARISH','NEUTRAL')
CATEGORIES=('STRUCTURE','TRANSITION','CANDLE','SUPPORT_RESISTANCE','SUPPLY_DEMAND','LIQUIDITY','MOMENTUM','VOLATILITY')
FLAGS=('DATA_LIMITATION','STRUCTURE_CONFLICT','SCENARIO_TIE','HIGH_VOLATILITY','NO_SUITABLE_STRATEGY','EXPERIMENTAL_METHOD')
INSTRUCTIONS='Review both frames independently. No IAT interpretation or later candles are included.'
POLICY={'version':1,'packet_window':5000,'evidence_comparison':'CATEGORY_TIMEFRAME_DIRECTION_SETS_PER_SUPPORT_OR_CONFLICT_ROLE',
        'uncertainty_comparison':'EXPLICIT_FLAGS_ONLY_NO_CONFIDENCE_LEVEL_MAPPING','reviewer_roster':'ALL_MEMBERS_BEFORE_REVEAL',
        'scope':'OFFLINE_CHART_READING_AGREEMENT_NOT_GROUND_TRUTH','flags':list(FLAGS)}


def require(condition,message='Invalid benchmark contract'):
    if not condition:raise ValueError(message)


def keys(obj,names):require(isinstance(obj,dict) and set(obj)==set(names.split()))


def text(value):require(isinstance(value,str) and 0<len(value.strip())<=1000 and not any(ord(c)<32 for c in value))


def texts(values):
    require(isinstance(values,list) and len(values)<=32)
    for value in values:text(value)


def identifier(value):require(isinstance(value,str) and re.fullmatch('[a-zA-Z0-9_-]{1,48}',value) is not None)


def hashed(value):return dict(value,sha256=digest(value))


def check_hash(value):require(isinstance(value,dict) and value.get('sha256')==digest({k:v for k,v in value.items() if k!='sha256'}),'Checksum mismatch')


def packet_at(dataset,at):
    """Public schema intentionally excludes manifest hashes and all IAT observations."""
    at=utc(at);frames={}
    for tf,minutes in (('M1',1),('M5',5)):
        visible=[r for r in dataset.rows[tf] if utc(r['timestamp'])+timedelta(minutes=minutes)<=at][-POLICY['packet_window']:]
        require(visible,'Closed history unavailable')
        frames[tf]=[dict(r,candle_id=digest([tf,r])) for r in visible]
    body={'packet_version':1,'kind':'BLINDED_CHART_REVIEW','symbol':'XAUUSD','timestamp_utc':iso(at),
          'dataset_kind':dataset.metadata['dataset_kind'],'timestamp_convention':'UTC_INTERVAL_OPEN',
          'window_policy':'ALL_AVAILABLE_CLOSED_PER_TIMEFRAME','frames':frames,
          'instructions':INSTRUCTIONS,
          'exness':'BLOCKED','signal':'WAIT','execution_allowed':False}
    body['packet_id']=digest(body)
    return hashed(body)


def validate_packet(packet):
    keys(packet,'packet_version kind symbol timestamp_utc dataset_kind timestamp_convention window_policy frames instructions exness signal execution_allowed packet_id sha256')
    check_hash(packet)
    require(type(packet['packet_version']) is int and packet['packet_version']==1 and packet['kind']=='BLINDED_CHART_REVIEW')
    require(packet['instructions']==INSTRUCTIONS and packet['timestamp_convention']=='UTC_INTERVAL_OPEN' and packet['window_policy']=='ALL_AVAILABLE_CLOSED_PER_TIMEFRAME')
    require(packet['symbol']=='XAUUSD' and packet['dataset_kind'] in ('SYNTHETIC_FIXTURE','INDEPENDENT_HISTORICAL'))
    require(packet['execution_allowed'] is False and packet['signal']=='WAIT' and packet['exness']=='BLOCKED')
    require(packet['packet_id']==digest({k:v for k,v in packet.items() if k not in ('packet_id','sha256')}))
    at=utc(packet['timestamp_utc']);keys(packet['frames'],'M1 M5')
    for tf,minutes in (('M1',1),('M5',5)):
        rows=packet['frames'][tf];require(isinstance(rows,list) and 1<=len(rows)<=5000);previous=None
        for row in rows:
            keys(row,'timestamp open high low close candle_id');opened=utc(row['timestamp'])
            require(opened+timedelta(minutes=minutes)<=at and (previous is None or opened>previous))
            require(opened.timestamp()%(minutes*60)==0)
            values=[row[k] for k in ('open','high','low','close')]
            require(all(type(v) in (int,float) and isfinite(v) and v>0 for v in values))
            o,h,l,c=values;require(l<=min(o,c)<=max(o,c)<=h)
            require(row['candle_id']==digest([tf,{k:v for k,v in row.items() if k!='candle_id'}]))
            previous=opened
    return True


def prepare_benchmark(manifest_path,timestamps,reviewer_ids,*,config=None,intelligence_config=None):
    require(isinstance(timestamps,list) and 1<=len(timestamps)<=32)
    require(isinstance(reviewer_ids,list) and 1<=len(reviewer_ids)<=16 and len(set(reviewer_ids))==len(reviewer_ids))
    for name in reviewer_ids:identifier(name)
    requested=[iso(utc(t)) for t in timestamps];require(len(set(requested))==len(requested))
    # Reuse the complete journal dataset gate before forming any public packet.
    result=run_journal_manifest(manifest_path,config=config,intelligence_config=intelligence_config)
    require(result['reasoning_journal'] is not None and result['status'] in ('PASS','WARN'),'Dataset preflight blocked benchmark')
    dataset=load_dataset(manifest_path)
    require(dataset.metadata==result['dataset'],'Dataset changed after preflight')
    originals={a['timestamp_utc']:a for a in result['reasoning_journal']['assessments']}
    start,end=(utc(result['scope']['evaluation'][k]) for k in ('start','end'))
    packets=[];bindings={}
    for stamp in sorted(requested):
        require(stamp in originals and start<utc(stamp)<=end,'Timestamp outside evaluation assessments')
        original=originals[stamp];require(original['adaptive_report']['data_quality']['valid'] and original['adaptive_report']['status']!='BLOCKED','Snapshot blocked')
        packet=packet_at(dataset,stamp);validate_packet(packet);packets.append(packet)
        bindings[packet['packet_id']]={'assessment_id':original['assessment_id'],'assessment_sha256':original['adaptive_report']['sha256'],'packet_sha256':packet['sha256']}
    return hashed({'bundle_version':1,'kind':'PRIVATE_CHART_REVIEW_KEY','policy':deepcopy(POLICY),
                   'reviewer_ids':sorted(reviewer_ids),'packets':packets,'bindings':bindings,
                   'journal_dataset_result':result,'exness':'BLOCKED','signal':'WAIT','execution_allowed':False})


def validate_bundle(bundle):
    keys(bundle,'bundle_version kind policy reviewer_ids packets bindings journal_dataset_result exness signal execution_allowed sha256')
    check_hash(bundle);require(type(bundle['bundle_version']) is int and bundle['bundle_version']==1 and bundle['kind']=='PRIVATE_CHART_REVIEW_KEY')
    require(bundle['policy']==POLICY and bundle['signal']=='WAIT' and bundle['execution_allowed'] is False and bundle['exness']=='BLOCKED')
    names=bundle['reviewer_ids'];require(isinstance(names,list) and 1<=len(names)<=16 and names==sorted(set(names)))
    for name in names:identifier(name)
    result=bundle['journal_dataset_result'];validate_journal_dataset_report(result)
    require(result['status'] in ('PASS','WARN') and result['reasoning_journal'] is not None)
    require(1<=len(bundle['packets'])<=32)
    require(set(bundle['bindings'])=={p['packet_id'] for p in bundle['packets']} and len(bundle['bindings'])==len(bundle['packets']))
    originals={a['assessment_id']:a for a in result['reasoning_journal']['assessments']}
    for p in bundle['packets']:
        validate_packet(p);b=bundle['bindings'][p['packet_id']];keys(b,'assessment_id assessment_sha256 packet_sha256')
        require(b['packet_sha256']==p['sha256'] and b['assessment_id'] in originals)
        a=originals[b['assessment_id']];r=a['adaptive_report']
        require(r['sha256']==b['assessment_sha256'] and r['timestamp_utc']==p['timestamp_utc'] and r['data_quality']['valid'] and r['status']!='BLOCKED')
        require(p['dataset_kind']==result['dataset']['dataset_kind'])
        # Bind visible candles to the frozen assessment's observations, not just hashes.
        observed={(v['timeframe'],v['observed_at']):v['ohlc'] for v in r['observed_facts']['candles'].values()}
        for tf,rows in p['frames'].items():
            for row in rows:
                key=(tf,row['timestamp'])
                if key in observed:require(all(row[k]==observed[key][k] for k in ('open','high','low','close')))
    return True


def annotation_template(packet,reviewer_id):
    validate_packet(packet);identifier(reviewer_id)
    return {'annotation_version':1,'packet_id':packet['packet_id'],'packet_sha256':packet['sha256'],
            'reviewer_id':reviewer_id,'annotation_kind':'SYNTHETIC_FIXTURE' if packet['dataset_kind']=='SYNTHETIC_FIXTURE' else 'INDEPENDENT_ANALYST',
            'blinded_attestation':False,'independence_attestation':False,'regime':'UNKNOWN','key_levels':[],
            'supporting_evidence':[],'conflicting_evidence':[],
            'scenarios':[{'scenario':s,'plausibility':'UNKNOWN','assumptions':[], 'invalidation_conditions':[]} for s in SCENARIOS],
            'uncertainty':{'level':'UNKNOWN','flags':[],'explanation':'Record uncertainty before submitting.'},
            'would_change_view':['Record what new closed-candle evidence would change this view.']}


def validate_annotation(annotation,packet):
    validate_packet(packet)
    keys(annotation,'annotation_version packet_id packet_sha256 reviewer_id annotation_kind blinded_attestation independence_attestation regime key_levels supporting_evidence conflicting_evidence scenarios uncertainty would_change_view')
    a=annotation;require(type(a['annotation_version']) is int and a['annotation_version']==1)
    require(a['packet_id']==packet['packet_id'] and a['packet_sha256']==packet['sha256']);identifier(a['reviewer_id'])
    require(a['annotation_kind'] in ('SYNTHETIC_FIXTURE','INDEPENDENT_ANALYST') and a['blinded_attestation'] is True)
    require(type(a['independence_attestation']) is bool)
    if a['annotation_kind']=='INDEPENDENT_ANALYST':require(a['independence_attestation'] and packet['dataset_kind']!='SYNTHETIC_FIXTURE','Synthetic inputs cannot establish independent analyst agreement')
    require(a['regime'] in REGIMES)
    refs={tf:{r['candle_id'] for r in rows} for tf,rows in packet['frames'].items()}
    def references(item):
        require(item['timeframe'] in refs and isinstance(item['candle_ids'],list) and 1<=len(item['candle_ids'])<=100)
        require(len(set(item['candle_ids']))==len(item['candle_ids']) and set(item['candle_ids'])<=refs[item['timeframe']])
    for name in ('supporting_evidence','conflicting_evidence'):
        require(isinstance(a[name],list) and len(a[name])<=32)
        for e in a[name]:
            keys(e,'category timeframe direction candle_ids description');references(e)
            require(e['category'] in CATEGORIES and e['direction'] in SCENARIOS);text(e['description'])
    require(isinstance(a['key_levels'],list) and len(a['key_levels'])<=32)
    for level in a['key_levels']:
        keys(level,'kind price timeframe candle_ids rationale');references(level)
        require(level['kind'] in ('SUPPORT','RESISTANCE','OTHER') and type(level['price']) in (int,float) and isfinite(level['price']) and level['price']>0);text(level['rationale'])
    require(isinstance(a['scenarios'],list) and len(a['scenarios'])==3 and {s['scenario'] for s in a['scenarios']}==set(SCENARIOS))
    for s in a['scenarios']:
        keys(s,'scenario plausibility assumptions invalidation_conditions');require(s['plausibility'] in ('LEADING','PLAUSIBLE','UNLIKELY','UNKNOWN'))
        texts(s['assumptions']);texts(s['invalidation_conditions'])
    u=a['uncertainty'];keys(u,'level flags explanation');require(u['level'] in ('LOW','MODERATE','HIGH','UNKNOWN'))
    require(isinstance(u['flags'],list) and len(set(u['flags']))==len(u['flags']) and set(u['flags'])<=set(FLAGS));text(u['explanation'])
    texts(a['would_change_view']);require(a['would_change_view'])
    return True


def receipt_for(bundle,annotation):
    validate_bundle(bundle)
    packet=next((p for p in bundle['packets'] if p['packet_id']==annotation.get('packet_id')),None)
    require(packet is not None);validate_annotation(annotation,packet)
    require(annotation['reviewer_id'] in bundle['reviewer_ids'],'Reviewer outside frozen roster')
    return hashed({'receipt_version':1,'bundle_sha256':bundle['sha256'],'annotation':deepcopy(annotation),
                   'annotation_sha256':digest(annotation),'frozen_assessment_sha256':bundle['bindings'][packet['packet_id']]['assessment_sha256']})


def uncertainty_flags(report):
    flags={'EXPERIMENTAL_METHOD'}
    if report['status']!='READY' or any('INCOMPLETE' in c or 'INSUFFICIENT' in c for c in report['uncertainty']):flags.add('DATA_LIMITATION')
    if report['regime']['directional']=='TRANSITION' or report['conflicts']:flags.add('STRUCTURE_CONFLICT')
    if len(report['assessment']['top_scenarios'])>1:flags.add('SCENARIO_TIE')
    if report['volatility']['overall']=='HIGH':flags.add('HIGH_VOLATILITY')
    if 'NO_SUITABLE_STRATEGY_CANDIDATE' in report['reason_codes']:flags.add('NO_SUITABLE_STRATEGY')
    return sorted(flags)


def evidence_tokens(report,role):
    leaders=[s for s in report['assessment']['scenarios'] if s['scenario'] in report['assessment']['top_scenarios']]
    field='supporting_evidence' if role=='supporting_evidence' else 'opposing_evidence'
    ids={eid for s in leaders for eid in s[field]}
    return sorted({(e['category'],e['timeframe'],'NEUTRAL' if e['direction']=='RANGING' else e['direction']) for e in report['interpretations']['evidence'] if e['id'] in ids and e['category'] in CATEGORIES and e['direction'] in (*SCENARIOS,'RANGING')})


def _comparison(annotation,report):
    evidence={}
    for role in ('supporting_evidence','conflicting_evidence'):
        reviewer={(e['category'],e['timeframe'],e['direction']) for e in annotation[role]};iat=set(evidence_tokens(report,role))
        evidence[role]={'reviewer_tokens':sorted(reviewer),'iat_tokens':sorted(iat),'shared':sorted(reviewer&iat),
                        'reviewer_only':sorted(reviewer-iat),'iat_only':sorted(iat-reviewer),
                        'intersection_count':len(reviewer&iat),'union_denominator':len(reviewer|iat),
                        'iat_leader_basis':report['assessment']['top_scenarios']}
    actual=uncertainty_flags(report);reviewer=sorted(annotation['uncertainty']['flags'])
    leaders=sorted(s['scenario'] for s in annotation['scenarios'] if s['plausibility']=='LEADING')
    return {'reviewer_id':annotation['reviewer_id'],'packet_id':annotation['packet_id'],'annotation_kind':annotation['annotation_kind'],
            'regime':{'reviewer':annotation['regime'],'iat':report['regime']['directional'],'agrees':annotation['regime']==report['regime']['directional']},
            'evidence':evidence,'uncertainty':{'reviewer_flags':reviewer,'iat_flags':actual,'exact_flag_set_agreement':reviewer==actual,
                          'reviewer_level':annotation['uncertainty']['level'],'level_comparison':'NOT_COMPARABLE_NO_IAT_CONFIDENCE_SCALE'},
            'leaders':{'reviewer':leaders,'iat':sorted(report['assessment']['top_scenarios']),'exact_set_agreement':leaders==sorted(report['assessment']['top_scenarios'])}}


def _summary(rows):
    return {'annotation_denominator':len(rows),'regime_agreement_count':sum(r['regime']['agrees'] for r in rows),
            'leader_set_agreement_count':sum(r['leaders']['exact_set_agreement'] for r in rows),
            'uncertainty_flag_set_agreement_count':sum(r['uncertainty']['exact_flag_set_agreement'] for r in rows),
            'unknown_regime_count':sum(r['regime']['reviewer']=='UNKNOWN' for r in rows),
            'known_regime_pair_denominator':sum('UNKNOWN' not in (r['regime']['reviewer'],r['regime']['iat']) for r in rows),
            'known_regime_agreement_count':sum(r['regime']['agrees'] and r['regime']['iat']!='UNKNOWN' for r in rows),
            'regime_confusion_counts':dict(sorted(Counter(r['regime']['reviewer']+' / '+r['regime']['iat'] for r in rows).items())),
            'uncertainty_flag_denominators':{f:{'denominator':len(rows),'presence_agreement_count':sum((f in r['uncertainty']['reviewer_flags'])==(f in r['uncertainty']['iat_flags']) for r in rows)} for f in FLAGS},
            'evidence':{role:{'comparison_denominator':len(rows),'nonempty_union_denominator':sum(bool(r['evidence'][role]['union_denominator']) for r in rows),
                      'shared_token_count':sum(r['evidence'][role]['intersection_count'] for r in rows),'union_token_denominator':sum(r['evidence'][role]['union_denominator'] for r in rows),
                      'empty_union_count':sum(not r['evidence'][role]['union_denominator'] for r in rows)} for role in ('supporting_evidence','conflicting_evidence')}}


def compare_benchmark(bundle,receipts):
    validate_bundle(bundle);require(isinstance(receipts,list))
    by_pair={}
    for receipt in receipts:
        check_hash(receipt);expected=receipt_for(bundle,receipt['annotation']);require(receipt==expected,'Receipt altered or from different bundle')
        a=receipt['annotation'];key=(a['packet_id'],a['reviewer_id']);require(key not in by_pair,'Duplicate reviewer/packet receipt');by_pair[key]=a
    expected={(p['packet_id'],r) for p in bundle['packets'] for r in bundle['reviewer_ids']}
    require(set(by_pair)==expected,'All frozen-roster annotations must be recorded before reveal')
    journal=bundle['journal_dataset_result']['reasoning_journal'];originals={a['assessment_id']:a for a in journal['assessments']}
    rows=[];revealed=[];pairwise=[]
    for packet in bundle['packets']:
        aid=bundle['bindings'][packet['packet_id']]['assessment_id'];original=originals[aid]
        rows.extend(_comparison(by_pair[packet['packet_id'],reviewer],original['adaptive_report']) for reviewer in bundle['reviewer_ids'])
        latest={}
        for r in journal['outcome_reviews']:
            if r['assessment_id']==aid:latest[r['horizon_minutes']]=r
        revealed.append({'packet_id':packet['packet_id'],'frozen_original':deepcopy(original),
                         'price_outcome_reviews_separate':list(latest.values())})
        for one,two in combinations(bundle['reviewer_ids'],2):
            a,b=(by_pair[packet['packet_id'],x] for x in (one,two))
            pairwise.append({'packet_id':packet['packet_id'],'reviewers':[one,two],'regimes':[a['regime'],b['regime']],
                             'regime_agrees':a['regime']==b['regime'],'annotation_sha256':[digest(a),digest(b)]})
    synthetic=[r for r in rows if r['annotation_kind']=='SYNTHETIC_FIXTURE'];independent=[r for r in rows if r['annotation_kind']=='INDEPENDENT_ANALYST']
    return hashed({'benchmark_version':1,'kind':'BLINDED_CHART_READING_COMPARISON','policy':deepcopy(POLICY),'bundle_sha256':bundle['sha256'],
                   'expected_annotation_denominator':len(expected),'packet_denominator':len(bundle['packets']),
                   'synthetic_workflow_metrics':_summary(synthetic) if synthetic else None,
                   'independent_analyst_agreement':'OPERATOR_ATTESTED_BLINDED_ANNOTATIONS' if independent else 'UNMEASURED',
                   'independent_analyst_metrics':_summary(independent) if independent else None,
                   'per_reviewer':{name:_summary([r for r in rows if r['reviewer_id']==name]) for name in bundle['reviewer_ids']},
                   'comparisons':rows,'annotations':[deepcopy(by_pair[key]) for key in sorted(by_pair)],
                   'representative_disagreements':[r for r in rows if not r['regime']['agrees'] or not r['uncertainty']['exact_flag_set_agreement'] or any(r['evidence'][role]['reviewer_only'] or r['evidence'][role]['iat_only'] for role in ('supporting_evidence','conflicting_evidence'))][:10],
                   'reviewer_pairwise':{'pair_denominator':len(pairwise),'regime_disagreement_count':sum(not r['regime_agrees'] for r in pairwise),'pairs':pairwise},
                   'reveal':revealed,'outcome_observation_cutoff_utc':bundle['journal_dataset_result']['scope']['outcome_observation_cutoff_utc'],
                   'historical_validation':bundle['journal_dataset_result']['historical_validation'],'historical_comparisons':'NOT_RUN','safety':safety(),'exness':'BLOCKED'})


def packet_html(packet):
    """Static dual-frame SVG; carries exactly the public packet, with no answer key."""
    validate_packet(packet);parts=['<!doctype html><meta charset="utf-8"><title>Blinded chart review</title>',
        '<h1>XAUUSD closed-candle review</h1><p>'+escape(packet['timestamp_utc'])+' UTC; '+escape(packet['dataset_kind'])+'</p>',
        '<p>Record your view before receiving IAT or later observations. Prices are OHLC; UTC labels are interval openings.</p>']
    for tf,rows in packet['frames'].items():
        low=min(r['low'] for r in rows);high=max(r['high'] for r in rows);span=high-low or 1
        y=lambda v:30+(high-v)/span*230
        parts.append('<h2>'+tf+'</h2><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 310" role="img" aria-label="'+tf+' closed candles">')
        for i,row in enumerate(rows):
            x=80+i*880/len(rows);color='#007060' if row['close']>=row['open'] else '#ad3333'
            label=escape(row['timestamp']+' '+str({k:row[k] for k in ('open','high','low','close')})+' candle_id='+row['candle_id'])
            parts.append(f'<g><title>{label}</title><line x1="{x}" x2="{x}" y1="{y(row["high"])}" y2="{y(row["low"])}" stroke="{color}"/><rect x="{x-2}" y="{min(y(row["open"]),y(row["close"]))}" width="4" height="{max(1,abs(y(row["open"])-y(row["close"])))}" fill="{color}"/></g>')
        for v in (low,(low+high)/2,high):parts.append(f'<text x="1" y="{y(v)}" font-size="12">{v:.5f}</text>')
        parts.append('<text x="80" y="290" font-size="12">'+escape(rows[0]['timestamp'])+'</text><text x="650" y="290" font-size="12">'+escape(rows[-1]['timestamp'])+'</text></svg>')
    parts.append('<p>WAIT; execution_allowed=false; Exness BLOCKED. See companion JSON for exact candle IDs.</p>')
    return '\n'.join(parts)


def write_new(path,value):
    """Publish completely or not at all; never overwrite any existing destination."""
    path=Path(path);data=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode() if not isinstance(value,str) else value.encode()
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.iat-blind-',delete=False) as f:
            temporary=Path(f.name);f.write(data);f.flush();os.fsync(f.fileno())
        if os.name=='nt':os.rename(temporary,path)
        else:os.link(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def read_json(path):
    with Path(path).open('rb') as handle:data=handle.read(64*1024*1024+1)
    require(len(data)<=64*1024*1024,'Benchmark artifact size limit')
    return strict_json(data)
