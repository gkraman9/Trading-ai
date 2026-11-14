"""Predeclared blinded review pilot v1 with annotation v2 and anonymous exports."""
from copy import deepcopy
from datetime import timedelta
import re
from iat.chart_benchmark import (require,keys,text,texts,identifier,hashed,check_hash,REGIMES,SCENARIOS,
    annotation_template,validate_annotation,prepare_benchmark,validate_bundle,receipt_for,compare_benchmark)
from iat.pilot_qualification import qualify_historical
from iat.replay_dataset import load_dataset,utc
from iat.journal_dataset_replay import empty_journal_dataset_report
from iat.intelligence.models import IntelligenceConfig,iso
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.strategy_replay import digest
from iat.historical_replay import dataset_preflight,safety

EVENTS=('HH_HL','LH_LL','BOS_UP','BOS_DOWN','CHOCH_UP','CHOCH_DOWN','LIQUIDITY_SWEEP_UP','LIQUIDITY_SWEEP_DOWN')
METRICS={'version':1,'regime':'EXACT_OR_UNCERTAIN_PARTIAL_OTHERWISE_DISAGREEMENT',
         'bias':'EXACT_OR_UNCERTAIN_PARTIAL_OTHERWISE_DISAGREEMENT',
         'structure':'TIMEFRAME_EVENT_SET_JACCARD_COUNTS','evidence':'BENCHMARK_V1_CODED_OVERLAP',
         'reasoning':'PRIVATE_PROSE_RETAINED_NO_AUTOMATED_SEMANTIC_GRADE',
         'uncertainty':'FLAGS_SEPARATE_FROM_CONFIDENCE_NO_IAT_CONFIDENCE_MAPPING',
         'decision':'RESEARCH_OPINION_ONLY_NEVER_AN_EXECUTION_SIGNAL'}


def _configs(config=None,intelligence_config=None):
    config=ContextConfig() if config is None else config;phase7=IntelligenceConfig() if intelligence_config is None else intelligence_config
    require(isinstance(config,ContextConfig) and isinstance(phase7,IntelligenceConfig))
    h=empty_journal_dataset_report()['configuration_hashes'];h.update(context=config.digest,intelligence=phase7.digest)
    return config,phase7,h


def _validate_plan(plan):
    check_hash(plan)
    keys(plan,'pilot_version pilot_id revision parent_plan_sha256 mode dataset_id dataset_manifest_sha256 qualified_interval human_review_sha256 sampling timestamps regime_coverage_goals reviewer_codes blinding metrics configuration_hashes sha256')
    require(type(plan['pilot_version']) is int and plan['pilot_version']==1)
    require(type(plan['revision']) is int and plan['revision']>=1);identifier(plan['pilot_id'])
    require((plan['revision']==1 and plan['parent_plan_sha256'] is None) or (plan['revision']>1 and isinstance(plan['parent_plan_sha256'],str) and len(plan['parent_plan_sha256'])==64))
    require(plan['mode'] in ('REAL','SYNTHETIC_ONLY') and plan['metrics']==METRICS)
    for field in ('dataset_id','dataset_manifest_sha256'):
        require(isinstance(plan[field],str) and re.fullmatch('[a-f0-9]{64}',plan[field]) is not None)
    if plan['parent_plan_sha256'] is not None:require(re.fullmatch('[a-f0-9]{64}',plan['parent_plan_sha256']) is not None)
    if plan['mode']=='REAL':require(isinstance(plan['human_review_sha256'],str) and re.fullmatch('[a-f0-9]{64}',plan['human_review_sha256']) is not None)
    else:require(plan['human_review_sha256'] is None)
    keys(plan['qualified_interval'],'start end');require(utc(plan['qualified_interval']['start'])<utc(plan['qualified_interval']['end']))

    require(plan['blinding']=='ALL_ASSIGNED_REVIEWERS_SUBMIT_BEFORE_OPERATOR_AUTHORIZED_REVEAL')
    names=plan['reviewer_codes'];require(isinstance(names,list) and 2<=len(names)<=16 and names==sorted(set(names)))
    for name in names:identifier(name)
    sampling=plan['sampling'];keys(sampling,'method start_utc end_utc step_minutes predeclared_without_iat_or_outcome_access')
    require(sampling['method']=='FIXED_UTC_GRID' and sampling['predeclared_without_iat_or_outcome_access'] is True)
    step=sampling['step_minutes'];require(type(step) is int and 1<=step<=1440)
    start,end=(utc(sampling[k]) for k in ('start_utc','end_utc'));require(start<=end and start.timestamp()%60==end.timestamp()%60==0)
    count=int((end-start).total_seconds()//(step*60))+1;require(1<=count<=32 and start+timedelta(minutes=(count-1)*step)==end)
    require(plan['timestamps']==[iso(start+timedelta(minutes=i*step)) for i in range(count)])
    keys(plan['regime_coverage_goals'],' '.join((*REGIMES[:-1],'UNCERTAIN')))
    require(all(type(n) is int and 0<=n<=32 for n in plan['regime_coverage_goals'].values()))
    return True


def register_plan(manifest_path,spec,review_path=None,*,synthetic_only=False,config=None,intelligence_config=None):
    """No assessment/replay performed here. Caller persists this plan before packets."""
    config,phase7,hashes=_configs(config,intelligence_config)
    if synthetic_only:
        ds=load_dataset(manifest_path);require(ds.metadata['dataset_kind']=='SYNTHETIC_FIXTURE','Synthetic path requires synthetic input')
        checked=dataset_preflight(ds,intelligence_config=phase7);require(checked['status']=='READY')
        qualification={'status':'SYNTHETIC_ONLY','dataset_id':digest(ds.metadata),'dataset':ds.metadata,'human_review_sha256':None}
    else:
        qualification=qualify_historical(manifest_path,review_path,intelligence_config=phase7)
        if qualification['status']=='DATA_NOT_QUALIFIED':return None,qualification
    keys(spec,'pilot_id revision parent_plan_sha256 sampling regime_coverage_goals reviewer_codes')
    m=qualification['dataset'];require(m['manifest_version']==2,'Declared warm-up required')
    require(all(utc(v['start'])<utc(v['end']) for v in m['warmup'].values()),'Declared warm-up required')
    loaded=load_dataset(manifest_path);require(loaded.metadata==m,'Dataset changed during registration')
    minimum=max(2*config.range_period,config.atr_period+1,config.roc_period+2,phase7.range_window,phase7.atr_period+1,phase7.left_strength+phase7.right_strength+1)
    warmup_counts={tf:sum(utc(row['timestamp'])+timedelta(minutes=minutes)<=utc(m['evaluation']['start']) for row in loaded.rows[tf]) for tf,minutes in (('M1',1),('M5',5))}
    if any(n<minimum for n in warmup_counts.values()):
        if synthetic_only:raise ValueError('Pilot warm-up insufficient')
        qualification.update(status='DATA_NOT_QUALIFIED',reason_codes=['PILOT_WARMUP_INSUFFICIENT']);return None,qualification

    sampling=deepcopy(spec['sampling']);start,end=(utc(sampling[k]) for k in ('start_utc','end_utc'))
    step=sampling['step_minutes'];require(type(step) is int and step>0)
    count=int((end-start).total_seconds()//(step*60))+1;require(1<=count<=32)
    plan=hashed({'pilot_version':1,**deepcopy(spec),'reviewer_codes':sorted(spec['reviewer_codes']),
        'mode':'SYNTHETIC_ONLY' if synthetic_only else 'REAL','dataset_id':qualification['dataset_id'],
        'dataset_manifest_sha256':m['manifest_sha256'],'qualified_interval':m['utc_range'],
        'human_review_sha256':qualification['human_review_sha256'],
        'timestamps':[iso(start+timedelta(minutes=i*step)) for i in range(count)],
        'blinding':'ALL_ASSIGNED_REVIEWERS_SUBMIT_BEFORE_OPERATOR_AUTHORIZED_REVEAL','metrics':deepcopy(METRICS),'configuration_hashes':hashes})
    _validate_plan(plan)
    require(utc(m['evaluation']['start'])<start<=end<=utc(m['evaluation']['end']),'Sampling outside evaluation')
    return plan,qualification


def generate_pilot(plan,manifest_path,review_path=None,*,config=None,intelligence_config=None):
    _validate_plan(plan);config,phase7,hashes=_configs(config,intelligence_config);require(hashes==plan['configuration_hashes'],'Configuration differs from registration')
    ds=load_dataset(manifest_path);m=ds.metadata;require(digest(m)==plan['dataset_id'],'Dataset differs from registration')
    if plan['mode']=='REAL':
        q=qualify_historical(manifest_path,review_path,intelligence_config=phase7)
        require(q['status']=='HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED' and q['human_review_sha256']==plan['human_review_sha256'],'DATA_NOT_QUALIFIED')
    else:require(m['dataset_kind']=='SYNTHETIC_FIXTURE')
    benchmark=prepare_benchmark(manifest_path,plan['timestamps'],plan['reviewer_codes'],config=config,intelligence_config=phase7)
    from iat.intelligence.engine import analyze_at
    from iat.intelligence.context import context_at
    observations={}
    for packet in benchmark['packets']:
        at=utc(packet['timestamp_utc']);options=dict(provenance=ds.provenance,calendar=ds.calendar,observed_finality=ds.finality_attested)
        structural=analyze_at('XAUUSD',ds.rows['M1'],ds.rows['M5'],at,config=phase7,**options)
        context=context_at('XAUUSD',ds.rows['M1'],ds.rows['M5'],at,config=config,intelligence_config=phase7,**options)
        events=[]
        for tf,frame in structural.frames.items():
            state=frame.structure.classification
            if state in ('BULLISH','BEARISH'):
                events.append({'timeframe':tf,'event':'HH_HL' if state=='BULLISH' else 'LH_LL',
                    'available_at':frame.data_as_of,'evidence_id':digest(frame.structure.evidence)})
            for e in frame.events:
                for suffix,label in (('_BOS','BOS'),('_CHOCH','CHOCH')):
                    if e.event_type.endswith(suffix):events.append({'timeframe':tf,'event':label+('_UP' if e.event_type.startswith('BULLISH') else '_DOWN'),'available_at':e.confirmed_at,'evidence_id':e.id})
        for tf,frame in context.interpretations.get('frames',{}).items():
            pools={p.id:p for p in frame['liquidity_pools']}
            for e in frame['liquidity_events']:
                if e.event_type=='CONFIRMED_SWEEP':events.append({'timeframe':tf,'event':'LIQUIDITY_SWEEP_UP' if pools[e.pool_id].kind.endswith('HIGHS') else 'LIQUIDITY_SWEEP_DOWN','available_at':e.available_at,'evidence_id':e.id})
        require(all(utc(e['available_at'])<=at for e in events))
        observations[packet['packet_id']]=events
    return hashed({'pilot_bundle_version':1,'plan':deepcopy(plan),'benchmark':benchmark,'structure_observations':observations})


def validate_pilot(bundle):
    keys(bundle,'pilot_bundle_version plan benchmark structure_observations sha256');check_hash(bundle)
    require(type(bundle['pilot_bundle_version']) is int and bundle['pilot_bundle_version']==1)
    plan=bundle['plan'];_validate_plan(plan);benchmark=bundle['benchmark'];validate_bundle(benchmark)
    require(plan['reviewer_codes']==benchmark['reviewer_ids'])
    result=benchmark['journal_dataset_result'];require(digest(result['dataset'])==plan['dataset_id'])
    require(result['configuration_hashes']==plan['configuration_hashes'])
    require([p['timestamp_utc'] for p in benchmark['packets']]==plan['timestamps'])
    require((plan['mode']=='SYNTHETIC_ONLY')==(result['dataset']['dataset_kind']=='SYNTHETIC_FIXTURE'))
    require(set(bundle['structure_observations'])==set(benchmark['bindings']))
    for p in benchmark['packets']:
        for event in bundle['structure_observations'][p['packet_id']]:
            keys(event,'timeframe event available_at evidence_id')
            require(event['timeframe'] in ('M1','M5') and event['event'] in EVENTS and utc(event['available_at'])<=utc(p['timestamp_utc']))
    return True


def annotation_v2_template(packet,reviewer):
    a=annotation_template(packet,reviewer);a.update(annotation_version=2,regime='UNCERTAIN',directional_bias='UNCERTAIN',
        structure_events=[],confidence='UNCERTAIN',best_decision={'action':'WAIT','reason':'Record research trade/wait opinion, never execution permission.'})
    return a


def _as_v1(annotation,packet):
    a=deepcopy(annotation)
    extra={'directional_bias','structure_events','confidence','best_decision'}
    require(type(a.get('annotation_version')) is int and a['annotation_version']==2 and extra<=set(a))
    require(a['regime'] in (*REGIMES[:-1],'UNCERTAIN'))
    require(a['directional_bias'] in (*SCENARIOS,'UNCERTAIN') and a['confidence'] in ('LOW','MEDIUM','HIGH','UNCERTAIN'))
    keys(a['best_decision'],'action reason');require(a['best_decision']['action'] in ('TRADE','WAIT','UNCERTAIN'));text(a['best_decision']['reason'])
    refs={tf:{c['candle_id'] for c in rows} for tf,rows in packet['frames'].items()}
    require(isinstance(a['structure_events'],list) and len(a['structure_events'])<=32)
    for event in a['structure_events']:
        keys(event,'event timeframe candle_ids description');require(event['event'] in EVENTS and event['timeframe'] in refs);text(event['description'])
        require(isinstance(event['candle_ids'],list) and event['candle_ids'] and len(set(event['candle_ids']))==len(event['candle_ids']) and set(event['candle_ids'])<=refs[event['timeframe']])
    for level in a['key_levels']:
        if level['kind'] in ('SUPPLY','DEMAND'):level['kind']='OTHER'
    for name in extra:a.pop(name)
    a.update(annotation_version=1,regime='UNKNOWN' if a['regime']=='UNCERTAIN' else a['regime'])
    validate_annotation(a,packet);return a


def pilot_receipt(bundle,annotation):
    validate_pilot(bundle);b=bundle['benchmark'];p=next((p for p in b['packets'] if p['packet_id']==annotation.get('packet_id')),None);require(p is not None)
    legacy=receipt_for(b,_as_v1(annotation,p))
    require((bundle['plan']['mode']=='SYNTHETIC_ONLY')==(annotation['annotation_kind']=='SYNTHETIC_FIXTURE'))
    return hashed({'receipt_version':2,'plan_sha256':bundle['plan']['sha256'],'bundle_sha256':bundle['sha256'],
                   'annotation':deepcopy(annotation),'annotation_sha256':digest(annotation),'legacy_receipt':legacy})


def _relation(one,two):
    if one==two or one in ('UNCERTAIN','UNKNOWN') and two in ('UNCERTAIN','UNKNOWN'):return 'EXACT'
    if one in ('UNCERTAIN','UNKNOWN') or two in ('UNCERTAIN','UNKNOWN'):return 'PARTIAL_UNCERTAIN'
    return 'DISAGREEMENT'


def _set_relation(one,two):
    a,b=set(one),set(two);union=a|b;intersection=a&b
    return {'relation':'UNMEASURED' if not union else 'EXACT' if a==b else 'PARTIAL' if intersection else 'DISAGREEMENT',
            'intersection_count':len(intersection),'union_denominator':len(union),
            'reviewer_only':sorted(a-b),'reference_only':sorted(b-a)}


def _counts(rows,field):
    return {'denominator':len(rows),'counts':{label:sum(r[field]==label for r in rows) for label in ('EXACT','PARTIAL_UNCERTAIN','DISAGREEMENT')}}


def reveal_pilot(bundle,receipts,*,authorized=False):
    require(authorized is True,'Explicit operator reveal authorization required');validate_pilot(bundle)
    require(isinstance(receipts,list));normalized=[]
    for r in receipts:
        check_hash(r);require(r==pilot_receipt(bundle,r['annotation']),'Receipt differs from locked submission');normalized.append(r['legacy_receipt'])
    # Existing all-roster gate, frozen assessments and first-breach reports are reused intact.
    compared=compare_benchmark(bundle['benchmark'],normalized)
    plan=bundle['plan'];aliases={name:'R'+str(i+1).zfill(3) for i,name in enumerate(plan['reviewer_codes'])}
    annotations={(r['annotation']['packet_id'],r['annotation']['reviewer_id']):r['annotation'] for r in receipts}
    rows=[];pairwise=[];original_regimes=[]
    for reveal in compared['reveal']:
        packet=reveal['packet_id'];original=reveal['frozen_original']['adaptive_report'];original_regimes.append(original['regime']['directional'])
        leaders=original['assessment']['top_scenarios'];bias=leaders[0] if len(leaders)==1 else 'UNCERTAIN'
        for reviewer in plan['reviewer_codes']:
            a=annotations[packet,reviewer];events=sorted({(e['timeframe'],e['event']) for e in a['structure_events']});iat=sorted({(e['timeframe'],e['event']) for e in bundle['structure_observations'][packet]})
            base=next(r for r in compared['comparisons'] if r['packet_id']==packet and r['reviewer_id']==reviewer)
            rows.append({'packet_id':packet,'reviewer':aliases[reviewer],
                'regime_relation':_relation(a['regime'],original['regime']['directional']),'reviewer_regime':a['regime'],'iat_regime':original['regime']['directional'],
                'bias_relation':_relation(a['directional_bias'],bias),'reviewer_bias':a['directional_bias'],'iat_bias':bias,
                'structure':_set_relation(events,iat),'structure_scope':'ALL_CONFIRMED_PHASE7_EVENTS_AND_CONTEXT_SWEEPS_AVAILABLE_AT_CUTOFF',
                'evidence':base['evidence'],'uncertainty':base['uncertainty'],'confidence':a['confidence'],
                'research_decision':a['best_decision']['action'],
                'reasoning_comparison':'NOT_AUTOMATICALLY_GRADED_PRIVATE_ANNOTATIONS_RETAINED'})
        for i,one in enumerate(plan['reviewer_codes']):
            for two in plan['reviewer_codes'][i+1:]:
                a,b=(annotations[packet,x] for x in (one,two))
                pairwise.append({'packet_id':packet,'reviewers':[aliases[one],aliases[two]],'regime_relation':_relation(a['regime'],b['regime']),
                    'bias_relation':_relation(a['directional_bias'],b['directional_bias']),
                    'structure':_set_relation([(e['timeframe'],e['event']) for e in a['structure_events']],[(e['timeframe'],e['event']) for e in b['structure_events']]),
                    'evidence':{role:_set_relation([(e['category'],e['timeframe'],e['direction']) for e in a[role]],[(e['category'],e['timeframe'],e['direction']) for e in b[role]]) for role in ('supporting_evidence','conflicting_evidence')},
                    'confidence_agrees':a['confidence']==b['confidence'],'decision_agrees':a['best_decision']['action']==b['best_decision']['action']})
    synthetic=plan['mode']=='SYNTHETIC_ONLY'
    def set_counts(items):
        return {'denominator':len(items),'nonempty_union_denominator':sum(bool(r['union_denominator']) for r in items),
                'counts':{v:sum(r['relation']==v for r in items) for v in ('EXACT','PARTIAL','DISAGREEMENT','UNMEASURED')},
                'intersection_count':sum(r['intersection_count'] for r in items),'union_denominator':sum(r['union_denominator'] for r in items)}
    metrics={'iat_to_reviewer':{'regime':_counts(rows,'regime_relation'),'bias':_counts(rows,'bias_relation')},
        'reviewer_to_reviewer':{'regime':_counts(pairwise,'regime_relation'),'bias':_counts(pairwise,'bias_relation')},
        'structure':{'iat_to_reviewer':set_counts([r['structure'] for r in rows]),'reviewer_to_reviewer':set_counts([r['structure'] for r in pairwise])},
        'evidence_and_uncertainty':compared['synthetic_workflow_metrics' if synthetic else 'independent_analyst_metrics'],
        'pairwise_evidence':{role:set_counts([r['evidence'][role] for r in pairwise]) for role in ('supporting_evidence','conflicting_evidence')},
        'annotation_denominator':len(rows),'packet_denominator':len(original_regimes),
        'reviewer_uncertain_regime_count':sum(r['reviewer_regime']=='UNCERTAIN' for r in rows),
        'reviewer_trade_opinion_count':sum(r['research_decision']=='TRADE' for r in rows),
        'reviewer_wait_count':sum(r['research_decision']=='WAIT' for r in rows),
        'reviewer_uncertain_decision_count':sum(r['research_decision']=='UNCERTAIN' for r in rows),
        'confidence_counts':{v:sum(r['confidence']==v for r in rows) for v in ('LOW','MEDIUM','HIGH','UNCERTAIN')},
        'regime_goal_coverage':{g:{'goal':n,'observed_iat_count':sum(x==('UNKNOWN' if g=='UNCERTAIN' else g) for x in original_regimes),'observed_reviewer_counts':{alias:sum(r['reviewer']==alias and r['reviewer_regime']==g for r in rows) for alias in aliases.values()}} for g,n in plan['regime_coverage_goals'].items()}}
    # Allowlisted export: no reviewer codes, free prose, source paths or full journals.
    export=hashed({'pilot_report_version':1,'classification':'SYNTHETIC_ONLY' if synthetic else 'OPERATOR_ATTESTED_REAL_REVIEW',
        'plan_sha256':plan['sha256'],'dataset_id':plan['dataset_id'],'configuration_hashes':plan['configuration_hashes'],'metrics_policy':METRICS,
        'synthetic_workflow_metrics':metrics if synthetic else None,'independent_analyst_agreement':'UNMEASURED' if synthetic else 'OPERATOR_ATTESTED_BLINDED_ANNOTATIONS',
        'real_review_metrics':None if synthetic else metrics,'iat_to_reviewer':rows,'reviewer_to_reviewer':pairwise,
        'representative_disagreements':[r for r in rows if r['regime_relation']!='EXACT' or r['bias_relation']!='EXACT' or r['structure']['relation'] in ('PARTIAL','DISAGREEMENT') or any(v['reviewer_only'] or v['iat_only'] for v in r['evidence'].values())][:10],
        'reasoning_review':'PRIVATE_SIDE_BY_SIDE_ANNOTATIONS_NO_SEMANTIC_ACCURACY_SCORE',
        'structure_limitations':['EVENT_CATEGORY_MATCH_NOT_EXACT_LEVEL_OR_EVENT_ID_MATCH','LIQUIDITY_IS_OHLC_PROXY_NOT_OBSERVED_ORDERS'],
        'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','safety':safety(),'exness':'BLOCKED'})
    return {'export':export,'private_review':{'plan':plan,'receipts':receipts,'benchmark_comparison':compared,
              'reveal_authorization':{'explicit_operator_authorization':True,'plan_sha256':plan['sha256'],'receipt_set_sha256':digest(sorted(r['sha256'] for r in receipts))}}}
