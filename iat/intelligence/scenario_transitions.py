"""Causal scenario transitions v1; embedded witnesses enable semantic validation."""
import json,re
from dataclasses import fields
from math import isfinite
from iat.replay_dataset import utc
from iat.intelligence.context_models import Hypothesis
from iat.intelligence.confluence import CATEGORY_BUCKETS
from iat.intelligence.scenario_assessment import validate_scenario_assessment,NO_DIRECTION,SCORE_KIND,need
from iat.intelligence.strategy_replay import digest

VERSION=1
TRANSITION_MODEL='IAT_SCENARIO_TRANSITIONS_V1'
STATES={'NEW','PERSISTING','STRENGTHENING','WEAKENING','INVALIDATED','REPLACED','ABSTAINED','BLOCKED'}
CONDITION='New confirmed structure contradicts this scenario.'
DIRECTIONS={'BULLISH_CONTINUATION_POSSIBILITY':'BULLISH','BULLISH_STRUCTURAL_TRANSITION':'BULLISH',
    'BEARISH_CONTINUATION_POSSIBILITY':'BEARISH','BEARISH_STRUCTURAL_TRANSITION':'BEARISH','RANGE_CONTINUATION':'RANGING'}
MAX_INPUT_BYTES=8*1024*1024
LIMITATIONS=['CONTENT_HASHES_ARE_NOT_SOURCE_AUTHENTICATION','HEURISTIC_SCORES_ARE_NOT_PROBABILITIES',
    'RAW_HISTORY_EXTENT_AND_CALENDAR_FINALITY_IDENTITY_ARE_NOT_IN_ASSESSMENT_V1',
    'ZONE_AND_SESSION_INVALIDATION_PROOF_UNAVAILABLE','PAIRWISE_DESCRIPTIONS_NOT_TRADING_PERMISSIONS']


def _plain(value):return json.loads(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False))


def _hash(value):need(isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value),'TRANSITION_DIGEST_INVALID')


def _evidence_id(value):need(isinstance(value,str) and re.fullmatch(r'M[15]:[A-Z_]+:[a-f0-9]{64}',value),'TRANSITION_EVIDENCE_ID_INVALID')


def _check_snapshot(r):
    validate_scenario_assessment(r)
    if r['status']=='BLOCKED':return
    need(isinstance(r['symbol'],str) and 0<len(r['symbol'])<=128 and not any(c.isspace() or ord(c)<32 for c in r['symbol']),'TRANSITION_SYMBOL_INVALID')
    need(r['provenance'] in ('SYNTHETIC_RESEARCH','HISTORICAL_RESEARCH','VALIDATED_LIVE'),'TRANSITION_PROVENANCE_INVALID')
    _hash(r['context_report_sha256']);ctx=r['m1_m5_alignment']
    need(isinstance(ctx,dict) and set(ctx)=={'classification','phase7_alignment','m1_structure','m5_structure','m1_as_of','m5_as_of','limitations'},'TRANSITION_FRAME_SCOPE_INVALID')
    need(r['market_regime']==ctx['classification'],'TRANSITION_REGIME_INCONSISTENT')
    need(isinstance(ctx['limitations'],list) and all(isinstance(x,str) for x in ctx['limitations']),'TRANSITION_LIMITATIONS_INVALID')
    for tf in ('M1','M5'):
        need(ctx[tf.lower()+'_structure'] in ('BULLISH','BEARISH','RANGING','TRANSITIONAL','UNKNOWN'),'TRANSITION_STRUCTURE_INVALID')
        if ctx[tf.lower()+'_as_of'] is not None:
            moment=utc(ctx[tf.lower()+'_as_of']);need(moment<=utc(r['analysis_at']) and moment.timestamp()%(60 if tf=='M1' else 300)==0,'TRANSITION_FRAME_TIME_INVALID')
    if r['configuration_hashes']:
        need(set(r['configuration_hashes'])=={'context','intelligence'},'TRANSITION_CONFIGURATION_INVALID')
        for v in r['configuration_hashes'].values():_hash(v)
    es={e['id']:e for e in r['evidence_index']}
    need(len(es)<=10000,'TRANSITION_RESOURCE_LIMIT')
    for e in es.values():
        need(set(e)=={'id','event_id','category','timeframe','direction','observed_at','available_at','references','reason_codes'},'TRANSITION_EVIDENCE_SCHEMA_INVALID')
        _evidence_id(e['id']);need(e['category'] in CATEGORY_BUCKETS and e['timeframe'] in ('M1','M5') and e['direction'] in ('BULLISH','BEARISH','RANGING','NEUTRAL'),'TRANSITION_EVIDENCE_SCHEMA_INVALID')
        need(e['id'].startswith(e['timeframe']+':'+e['category']+':'),'TRANSITION_EVIDENCE_ID_INVALID')
        bound=ctx[e['timeframe'].lower()+'_as_of'];need(bound is not None and utc(e['observed_at'])<=utc(e['available_at'])<=utc(bound),'TRANSITION_EVIDENCE_CHRONOLOGY_INVALID')
        need(isinstance(e['references'],list) and e['references']==sorted(set(e['references'])),'TRANSITION_EVIDENCE_REFERENCES_INVALID')
        for ref in e['references']:_evidence_id(ref);need(ref.startswith(e['timeframe']+':'),'TRANSITION_EVIDENCE_REFERENCES_INVALID')
        need(isinstance(e['reason_codes'],list) and all(isinstance(x,str) and re.fullmatch('[A-Z0-9_]{1,128}',x) for x in e['reason_codes']),'TRANSITION_CODES_INVALID')
        if e['category']=='STRUCTURE':
            state=ctx[e['timeframe'].lower()+'_structure'];direction=state if state in ('BULLISH','BEARISH','RANGING') else 'NEUTRAL'
            need(e['direction']==direction and ('STRUCTURE_INSUFFICIENT_PIVOTS' if state=='UNKNOWN' else 'STRUCTURE_'+state) in e['reason_codes'],'TRANSITION_STRUCTURE_EVIDENCE_INCONSISTENT')
        if e['event_id'] is not None:need(e['category']=='TRANSITION' and e['event_id'] in e['references'] and re.fullmatch(r'M[15]:CHOCH_EVENT:[a-f0-9]{64}',e['event_id']),'TRANSITION_EVENT_REFERENCE_INVALID')
    need(isinstance(r['fresh_opposing_m1_choch'],list) and set(r['fresh_opposing_m1_choch'])<=set(es),'TRANSITION_EVENT_REFERENCE_INVALID')
    for key in r['fresh_opposing_m1_choch']:
        e=es[key];need(e['timeframe']=='M1' and e['category']=='TRANSITION' and e['event_id'] is not None and e['available_at']==ctx['m1_as_of'],'TRANSITION_EVENT_REFERENCE_INVALID')
    for h in r['ranked_hypotheses']:
        need(set(h)=={f.name for f in fields(Hypothesis)}|{'rank','selected_by_context','explanation'},'TRANSITION_HYPOTHESIS_SCHEMA_INVALID')
        need(h['generated_at']==r['analysis_at'] and h['timeframe_context']==ctx,'TRANSITION_HYPOTHESIS_SCOPE_INVALID')
        need(isinstance(h['model_version'],str) and 0<len(h['model_version'])<=128 and type(h['configuration_version']) is int and h['configuration_version']>0,'TRANSITION_SCORING_METHOD_INVALID')
        need(type(h['heuristic_score']) in (int,float) and isfinite(h['heuristic_score']) and h['heuristic_score']>=0,'TRANSITION_SCORE_INVALID')
        for k in ('supporting_evidence','contradictory_evidence','relevant_zones'):
            need(isinstance(h[k],list) and h[k]==sorted(set(h[k])),'TRANSITION_EVIDENCE_REFERENCES_INVALID')
        for k in ('supporting_evidence','contradictory_evidence'):need(set(h[k])<=set(es),'TRANSITION_EVIDENCE_REFERENCES_INVALID')
        for k in ('assumptions','invalidation_conditions','data_quality_limitations'):
            need(isinstance(h[k],list) and len(h[k])<=256 and all(isinstance(v,str) and len(v)<=2000 for v in h[k]),'TRANSITION_HYPOTHESIS_SCHEMA_INVALID')
    need(len({(h['model_version'],h['configuration_version']) for h in r['ranked_hypotheses']})==1,'TRANSITION_SCORING_METHOD_INCONSISTENT')


def _descriptor(value):
    if value is None:return {'validation':'MISSING','input_digest':None,'assessment':None}
    checksum=None
    try:
        need(isinstance(value,dict),'TRANSITION_INPUT_INVALID')
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False);need(len(raw.encode())<=MAX_INPUT_BYTES,'TRANSITION_RESOURCE_LIMIT')
        copied=json.loads(raw);checksum=digest(copied);_check_snapshot(copied)
        return {'validation':'VALID','input_digest':checksum,'assessment':copied}
    except (ValueError,TypeError,KeyError,AttributeError,IndexError,OverflowError,RecursionError):
        return {'validation':'INVALID','input_digest':checksum,'assessment':None}


def _validate_descriptor(d):
    need(isinstance(d,dict) and set(d)=={'validation','input_digest','assessment'},'TRANSITION_INPUT_DESCRIPTOR_INVALID')
    need(d['validation'] in ('VALID','MISSING','INVALID'),'TRANSITION_INPUT_DESCRIPTOR_INVALID')
    if d['validation']=='VALID':
        need(isinstance(d['assessment'],dict) and d['input_digest']==digest(d['assessment']),'TRANSITION_INPUT_DESCRIPTOR_INVALID');_check_snapshot(d['assessment'])
    else:
        need(d['assessment'] is None,'TRANSITION_INPUT_DESCRIPTOR_INVALID')
        if d['validation']=='MISSING':need(d['input_digest'] is None,'TRANSITION_INPUT_DESCRIPTOR_INVALID')
        elif d['input_digest'] is not None:_hash(d['input_digest'])


def _hypothesis(r,name=None):return next(h for h in r['ranked_hypotheses'] if h['hypothesis_type']==(r['selected_hypothesis'] if name is None else name))


def _method(r):
    h=r['ranked_hypotheses'][0]
    return {'assessment_model':r['model_version'],'assessment_version':r['scenario_assessment_version'],
        'score_kind':r['score_kind'],'hypothesis_model':h['model_version'],'configuration_version':h['configuration_version'],
        'configuration_hashes':r['configuration_hashes'],'provenance':r['provenance'],'timeframes':['M1','M5']}


def _identity(r):
    if r is None or r['status']=='BLOCKED' or r['selected_hypothesis']==NO_DIRECTION or not r['configuration_hashes']:return None
    return digest({'symbol':r['symbol'],'hypothesis_type':r['selected_hypothesis'],'method':_method(r)})


def _structural(r,tf):return [e for e in r['evidence_index'] if e['category']=='STRUCTURE' and e['timeframe']==tf]


def _history_ready(r):
    c=r['m1_m5_alignment']
    eligible=(r['status']!='ASSESSED' or not _hypothesis(r)['data_quality_limitations'] and 'REQUIRED_STRUCTURAL_PRECONDITION_UNESTABLISHED' not in _hypothesis(r)['assumptions'])
    return bool(eligible and r['configuration_hashes'] and not c['limitations'] and all(c[k+'_as_of'] is not None and c[k+'_structure']!='UNKNOWN' and len(_structural(r,k.upper()))==1 for k in ('m1','m5')))


def _invalidation(p,c):
    old=_hypothesis(p);direction=DIRECTIONS[p['selected_hypothesis']]
    if CONDITION not in old['invalidation_conditions']:return []
    prev=_structural(p,'M5')[0];now=_structural(c,'M5')[0];opposite={'BULLISH':{'BEARISH'},'BEARISH':{'BULLISH'},'RANGING':{'BULLISH','BEARISH'}}[direction]
    if not (prev['direction']==direction and now['direction'] in opposite and p['m1_m5_alignment']['m5_structure']==direction
            and c['m1_m5_alignment']['m5_structure']==now['direction'] and 'STRUCTURE_'+now['direction'] in now['reason_codes']
            and prev['id'] in old['supporting_evidence'] and now['id'] in _hypothesis(c,p['selected_hypothesis'])['contradictory_evidence']
            and utc(p['analysis_at'])<utc(now['available_at'])<=utc(c['analysis_at']) and now['id']!=prev['id']
            and len(now['references'])>=4 and all(ref.startswith('M5:PIVOT:') for ref in now['references'])):return []
    return [{'condition':CONDITION,'evidence_id':now['id'],'source_references':now['references'],
        'available_at':now['available_at'],'previous_structure_evidence_id':prev['id'],
        'timeframe':'M5','direction':now['direction'],'reason_code':'NEW_OPPOSING_CONFIRMED_M5_STRUCTURE'}]


def _support(r,name):
    h=_hypothesis(r,name);index={e['id']:e for e in r['evidence_index']}
    def buckets(ids):return {e['timeframe']+':'+CATEGORY_BUCKETS[e['category']]+':'+e['direction'] for e in (index[k] for k in ids)}
    return h,buckets(h['supporting_evidence']),buckets(h['contradictory_evidence'])


def _base(inputs):
    refs={};timestamps={};scenarios={}
    for role,d in inputs.items():
        r=d['assessment'];refs[role]=r['sha256'] if r is not None else None
        try:timestamps[role]=r['analysis_at'] if r is not None and utc(r['analysis_at']) is not None else None
        except (ValueError,TypeError,KeyError):timestamps[role]=None
        scenarios[role]={'hypothesis_type':r['selected_hypothesis'] if r is not None else None,'scenario_id':_identity(r)}
    return {'transition_version':VERSION,'model_version':TRANSITION_MODEL,'policy_version':VERSION,'inputs':inputs,
        'assessment_ids':refs,'observation_timestamps':timestamps,'scenario_identifiers':scenarios,'classification':'BLOCKED',
        'comparability':{'status':'BLOCKED','scope':'ADJACENT_COMPLETED_M1_M5_SNAPSHOT_DECLARATIONS','method':None},
        'support_comparison':None,'evidence_references':{'previous':[],'current':[]},'invalidation_evidence':[],
        'reason_codes':[],'explanation':[],'limitations':list(LIMITATIONS),
        'mode':'READ_ONLY_SHADOW','signal':'WAIT','execution_allowed':False,'broker_access':False,'orders_requested':0,
        'profitability_tested':False,'exness':'BLOCKED','qualification':'DATA_NOT_QUALIFIED',
        'historical_validation':'PENDING','historical_comparisons':'NOT_RUN'}


def _derive(inputs):
    for d in inputs.values():_validate_descriptor(d)
    out=_base(inputs);p=inputs['previous']['assessment'];c=inputs['current']['assessment']
    def finish(state,reason,comparability=None):
        out['classification']=state;out['reason_codes']=[reason]
        out['explanation']=[{'NEW':'A newly selected scenario follows an observed abstention.',
            'PERSISTING':'The same upstream-selected scenario retains equal heuristic support.',
            'STRENGTHENING':'Comparable capped support increased without increasing opposition.',
            'WEAKENING':'Comparable capped support decreased without decreasing opposition.',
            'INVALIDATED':'Newly available opposing confirmed M5 structure satisfies the recorded condition.',
            'REPLACED':'A different upstream scenario is selected; invalidation has not been established.',
            'ABSTAINED':'A descriptive transition cannot be established under this comparison policy.',
            'BLOCKED':'Inputs or chronology do not establish a valid transition.'}[state]]
        if comparability is not None:out['comparability']['status']=comparability
        key={role:{'validation':d['validation'],'input_digest':d['input_digest']} for role,d in inputs.items()}
        out['transition_id']='SCENARIO_TRANSITION:'+digest({'policy_version':VERSION,'inputs':key})
        return dict(out,sha256=digest(out))
    if inputs['current']['validation']!='VALID':return finish('BLOCKED','CURRENT_ASSESSMENT_UNAVAILABLE_OR_INVALID')
    if c['status']=='BLOCKED':return finish('BLOCKED','CURRENT_ASSESSMENT_BLOCKED')
    if inputs['previous']['validation']=='INVALID':return finish('BLOCKED','PREVIOUS_ASSESSMENT_INVALID')
    if p is None:return finish('ABSTAINED','PREVIOUS_OBSERVATION_MISSING','UNESTABLISHED')
    if p['status']=='BLOCKED':return finish('BLOCKED','PREVIOUS_ASSESSMENT_BLOCKED')
    a,b=utc(p['analysis_at']),utc(c['analysis_at'])
    if b<=a:return finish('BLOCKED','DUPLICATE_OBSERVATION_TIMESTAMP' if b==a else 'REVERSED_OBSERVATION_TIMESTAMPS')
    if p['symbol']!=c['symbol']:return finish('ABSTAINED','INSTRUMENT_MISMATCH','INCOMPATIBLE')
    if not p['configuration_hashes'] or not c['configuration_hashes']:return finish('ABSTAINED','SCORING_IDENTITY_UNAVAILABLE','UNESTABLISHED')
    if _method(p)!=_method(c):return finish('ABSTAINED','SCORING_METHOD_OR_CONFIGURATION_MISMATCH','INCOMPATIBLE')
    out['comparability']['method']=_method(c)
    if not _history_ready(p) or not _history_ready(c):return finish('ABSTAINED','UPSTREAM_HISTORY_OR_STRUCTURE_INSUFFICIENT','UNESTABLISHED')
    for r in (p,c):
        if utc(r['analysis_at'])!=utc(r['m1_m5_alignment']['m1_as_of']):return finish('ABSTAINED','OBSERVATION_SCOPE_UNESTABLISHED','UNESTABLISHED')
    if (b-a).total_seconds()!=60:return finish('ABSTAINED','OBSERVATION_GAP','UNESTABLISHED')
    m5a,m5b=(utc(r['m1_m5_alignment']['m5_as_of']) for r in (p,c))
    if m5b<m5a:return finish('BLOCKED','REVERSED_M5_SNAPSHOT_ORDER')
    if (m5b-m5a).total_seconds() not in (0,300):return finish('ABSTAINED','M5_OBSERVATION_GAP','UNESTABLISHED')
    for tf in ('M1','M5'):
        before,after=_structural(p,tf)[0],_structural(c,tf)[0]
        if before['id']!=after['id'] and utc(after['available_at'])<=a:return finish('ABSTAINED','STRUCTURE_REVISION_WITHOUT_NEW_CONFIRMATION','UNESTABLISHED')
    out['comparability']['status']='COMPARABLE'
    out['evidence_references']={role:sorted(e['id'] for e in r['evidence_index']) for role,r in (('previous',p),('current',c))}
    if p['status']=='ASSESSED':
        proof=_invalidation(p,c)
        if proof:out['invalidation_evidence']=proof;return finish('INVALIDATED','EXPLICIT_CONFIRMED_STRUCTURE_INVALIDATION')
    if c['status']!='ASSESSED':return finish('ABSTAINED','CURRENT_UPSTREAM_ABSTENTION')
    if p['status']!='ASSESSED':
        return finish('NEW','SCENARIO_SELECTED_AFTER_ABSTENTION') if p['selected_hypothesis']==NO_DIRECTION else finish('ABSTAINED','PREVIOUS_SELECTION_UNESTABLISHED')
    if p['selected_hypothesis']!=c['selected_hypothesis']:return finish('REPLACED','UPSTREAM_SCENARIO_REPLACED_WITHOUT_INVALIDATION_PROOF')
    name=p['selected_hypothesis'];ph,ps,po=_support(p,name);ch,cs,co=_support(c,name)
    comparison={'previous_score':ph['heuristic_score'],'current_score':ch['heuristic_score'],'score_kind':SCORE_KIND,
        'support_buckets_added':sorted(cs-ps),'support_buckets_removed':sorted(ps-cs),
        'opposition_buckets_added':sorted(co-po),'opposition_buckets_removed':sorted(po-co)}
    out['support_comparison']=comparison
    if ph['heuristic_score']==ch['heuristic_score']:return finish('PERSISTING','SAME_SCENARIO_EQUAL_HEURISTIC_SUPPORT')
    anchors=all({e['id'] for e in _structural(p,tf)}=={e['id'] for e in _structural(c,tf)} for tf in ('M1','M5'))
    if not anchors or ph['relevant_zones']!=ch['relevant_zones']:return finish('ABSTAINED','SUPPORT_ANCHOR_SCOPE_CHANGED','UNESTABLISHED')
    if ch['heuristic_score']>ph['heuristic_score'] and ps<cs and co<=po:return finish('STRENGTHENING','MONOTONE_CAPPED_SUPPORT_INCREASE')
    if ch['heuristic_score']<ph['heuristic_score'] and cs<ps and po<=co:return finish('WEAKENING','MONOTONE_CAPPED_SUPPORT_DECREASE')
    return finish('ABSTAINED','SUPPORT_CHANGE_NOT_COMPARABLE','UNESTABLISHED')


def assess_scenario_transition(previous,current):
    """Compare two snapshots, without mutation, look-ahead or execution permission."""
    return _derive({'previous':_descriptor(previous),'current':_descriptor(current)})


def validate_scenario_transition(report):
    """Recompute semantics from embedded input witnesses, not from caller state flags."""
    need(isinstance(report,dict) and type(report.get('transition_version')) is int and report['transition_version']==VERSION,'TRANSITION_VERSION_UNSUPPORTED')
    need(isinstance(report.get('inputs'),dict) and set(report['inputs'])=={'previous','current'},'TRANSITION_INPUT_DESCRIPTOR_INVALID')
    expected=_derive(_plain(report['inputs']))
    need(set(report)==set(expected) and report.get('sha256')==digest({k:v for k,v in report.items() if k!='sha256'}),'TRANSITION_CHECKSUM_OR_SCHEMA_INVALID')
    need(report['sha256']==expected['sha256'] and report==expected,'TRANSITION_SEMANTIC_MISMATCH')
    return True


def replay_scenario_transitions(assessments):
    """Synthetic-only streamed audit: a missing observation breaks pair continuity."""
    previous=None
    for i,current in enumerate(assessments):
        need(i<5000,'TRANSITION_REPLAY_LIMIT')
        if isinstance(current,dict) and current.get('provenance') not in (None,'SYNTHETIC_RESEARCH'):
            current={'synthetic_replay_only':True}
        yield assess_scenario_transition(previous,current)
        previous=current
