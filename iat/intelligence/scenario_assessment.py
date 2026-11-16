"""Scenario assessment v1: a causal presentation of ContextReport, never a selector."""
from dataclasses import asdict,fields
from datetime import datetime,timedelta
from types import SimpleNamespace
import json,re
from iat.analysis import validate_candles
from iat.replay_dataset import utc
from iat.intelligence.context import context_at,replay_context,aggregate
from iat.intelligence.context_models import ContextReport,ContextConfig,Evidence,Hypothesis,Zone
from iat.intelligence.context_evidence import identity
from iat.intelligence.strategy_replay import digest
from iat.intelligence.multi_timeframe import align
from iat.intelligence import confluence,hypotheses

MODEL='IAT_MARKET_SCENARIO_ASSESSMENT_V1'
NO_DIRECTION='NO_CLEAR_DIRECTIONAL_HYPOTHESIS'
SCORE_KIND='HEURISTIC_EVIDENCE_NOT_PROBABILITY'
NAMES={NO_DIRECTION,'BULLISH_CONTINUATION_POSSIBILITY','BEARISH_CONTINUATION_POSSIBILITY',
    'BULLISH_STRUCTURAL_TRANSITION','BEARISH_STRUCTURAL_TRANSITION','RANGE_CONTINUATION'}
TIME_KEYS={'analysis_at','data_as_of','observed_at','available_at','occurred_at','confirmed_at',
    'detected_at','origin_at','broken_at','invalidated_at','generated_at','m1_as_of','m5_as_of'}
LIMITATIONS=['SCORES_ARE_HEURISTIC_NOT_PROBABILITIES','OHLC_EVIDENCE_IS_NOT_A_FORECAST',
    'CONTEXT_CONTRACT_CHECKS_ARE_NOT_INDEPENDENT_MARKET_DATA_VALIDATION',
    'NO_ENTRY_STOP_TARGET_OR_EXECUTION_AUTHORIZATION']


class ScenarioInputError(ValueError):pass


def need(value,code):
    if not value:raise ScenarioInputError(code)


def plain(value):return json.loads(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False))


def exact(value,model):need(isinstance(value,dict) and set(value)=={f.name for f in fields(model)},'CONTEXT_SCHEMA_INVALID')


def codes(values):
    need(isinstance(values,list) and len(values)<=256 and all(isinstance(x,str) and re.fullmatch('[A-Z0-9_]{1,128}',x) for x in values),'CONTEXT_REASON_CODES_INVALID')
    return sorted(set(values))


def _chronology(value,at,key=None,depth=0):
    need(depth<=64,'CONTEXT_RESOURCE_LIMIT')
    if isinstance(value,dict):
        for k,v in value.items():_chronology(v,at,k,depth+1)
    elif isinstance(value,list):
        for v in value:_chronology(v,at,key,depth+1)
    elif value is not None and key in TIME_KEYS|{'historical_touches','retests'}:
        need(utc(value)<=at,'FUTURE_CONTEXT_OBSERVATION')


def _normalize(report):
    need(isinstance(report,(ContextReport,dict)),'CONTEXT_REPORT_UNAVAILABLE')
    raw=report.to_dict() if isinstance(report,ContextReport) else report
    encoded=json.dumps(raw,sort_keys=True,separators=(',',':'),allow_nan=False)
    need(len(encoded.encode())<=8*1024*1024,'CONTEXT_RESOURCE_LIMIT')
    r=json.loads(encoded);exact(r,ContextReport)
    need(type(r['report_version']) is int and r['report_version']==1 and r['model_version']=='IAT_MARKET_CONTEXT_V1','CONTEXT_VERSION_UNSUPPORTED')
    need(r['mode']=='READ_ONLY_SHADOW' and r['signal']=='WAIT' and r['execution_allowed'] is False,'UNSAFE_CONTEXT_CONTRACT')
    need(isinstance(r['symbol'],str) and 0<len(r['symbol'])<=128 and not any(c.isspace() or ord(c)<32 for c in r['symbol']),'CONTEXT_SYMBOL_INVALID')
    need(r['provenance'] in ('SYNTHETIC_RESEARCH','HISTORICAL_RESEARCH','VALIDATED_LIVE'),'CONTEXT_PROVENANCE_INVALID')
    for k in ('configuration_sha256','intelligence_configuration_sha256'):need(isinstance(r[k],str) and re.fullmatch('[a-f0-9]{64}',r[k]),'CONTEXT_CONFIGURATION_INVALID')
    config=ContextConfig.from_dict(r['configuration'])
    need(r['configuration']==asdict(config) and type(r['configuration_version']) is int and r['configuration_version']==config.version and r['configuration_sha256']==config.digest,'CONTEXT_CONFIGURATION_MISMATCH')
    q=r['data_quality'];need(isinstance(q,dict) and set(q)=={'valid','status','diagnostics'} and type(q['valid']) is bool and q['status']==('VALID' if q['valid'] else 'BLOCKED'),'CONTEXT_QUALITY_INVALID')
    need(isinstance(q['diagnostics'],list) and len(q['diagnostics'])<=256,'CONTEXT_QUALITY_INVALID')
    for d in q['diagnostics']:
        need(isinstance(d,dict) and d.get('severity') in ('INFO','WARNING','ERROR') and isinstance(d.get('message'),str),'CONTEXT_QUALITY_INVALID');codes([d.get('code')])
    codes(r['abstention_reasons']);codes(r['context']['limitations'])
    need(isinstance(r['explanation'],list) and len(r['explanation'])<=64 and all(isinstance(x,str) and len(x)<=2000 for x in r['explanation']),'CONTEXT_EXPLANATION_INVALID')
    at=utc(r['analysis_at']);_chronology(r,at)
    return r,config,at


def _validated_view(r,config,at):
    need(not any(d['severity']=='ERROR' for d in r['data_quality']['diagnostics']),'CONTEXT_QUALITY_INCONSISTENT')
    ctx=r['context'];need(set(ctx)=={'classification','phase7_alignment','m1_structure','m5_structure','m1_as_of','m5_as_of','limitations'},'CONTEXT_ALIGNMENT_INVALID')
    facts=r['observed_facts'];frames=r['interpretations']['frames'];sources=r['interpretations']['source_registry']
    need(isinstance(facts,dict) and facts and set(facts)<= {'M1','M5'} and set(facts)==set(frames),'CONTEXT_FRAMES_UNAVAILABLE')
    need(isinstance(sources,dict) and len(sources)<=20000 and isinstance(r['evidence'],list) and len(r['evidence'])<=10000,'CONTEXT_RESOURCE_LIMIT')
    def sid(key):need(isinstance(key,str) and re.fullmatch(r'M[15]:[A-Z_]+:[a-f0-9]{64}',key),'NONCANONICAL_EVIDENCE_IDENTITY')
    for key,s in sources.items():
        sid(key);tf=s['timeframe'];need(tf in facts and key.startswith(tf+':'),'SOURCE_TIMEFRAME_INCONSISTENT')
        need(utc(s['observed_at'])<=utc(s['available_at'])<=utc(facts[tf]['data_as_of']),'SOURCE_CHRONOLOGY_INVALID')
        refs=s.get('references',[]);need(isinstance(refs,list) and len(refs)==len(set(refs)),'SOURCE_REFERENCES_INVALID')
        for ref in refs:need(ref in sources and sources[ref]['timeframe']==tf and utc(sources[ref]['available_at'])<=utc(s['available_at']),'SOURCE_REFERENCE_UNAVAILABLE')
        if s['kind']=='CANDLE':
            values=s['ohlc'];need(set(values)=={'open','high','low','close'},'SOURCE_CANDLE_INVALID')
            need(key==identity(r['symbol'],tf,'CANDLE',s['observed_at'],values['open'],values['high'],values['low'],values['close']),'SOURCE_IDENTITY_MISMATCH')
            need(utc(s['available_at'])==utc(s['observed_at'])+timedelta(minutes=1 if tf=='M1' else 5) and utc(s['observed_at']).timestamp()%(60 if tf=='M1' else 300)==0,'UNCLOSED_OR_MISALIGNED_SOURCE_CANDLE')
        elif s['kind']=='CONFIRMED_PIVOT':
            need(key==identity(r['symbol'],tf,'PIVOT',s['pivot_kind'],s['observed_at'],s['available_at'],s['price']),'SOURCE_IDENTITY_MISMATCH')
        else:need(s['kind'] in ('ZONE','LIQUIDITY_POOL','LIQUIDITY_EVENT','CHOCH_EVENT'),'SOURCE_KIND_INVALID')
    done=set();visiting=set()
    def visit(key,depth=0):
        need(depth<=32 and key not in visiting,'SOURCE_REFERENCE_CYCLE')
        if key in done:return
        visiting.add(key)
        for ref in sources[key].get('references',[]):visit(ref,depth+1)
        visiting.remove(key);done.add(key)
    for key in sources:visit(key)
    canonical={};active_events={}
    for raw in r['evidence']:
        exact(raw,Evidence);e=Evidence(**raw);sid(e.id)
        need(e.category in confluence.CATEGORY_BUCKETS and e.timeframe in facts and e.direction in ('BULLISH','BEARISH','RANGING','NEUTRAL'),'CONTEXT_EVIDENCE_INVALID')
        need(utc(e.observed_at)<=utc(e.available_at) and utc(e.available_at)<=utc(facts[e.timeframe]['data_as_of']),'EVIDENCE_CHRONOLOGY_INVALID')
        codes(raw['reason_codes']);need(raw['references']==sorted(set(raw['references'])),'EVIDENCE_REFERENCES_INVALID')
        identity_refs=list(e.references)
        if e.category=='TRANSITION':
            need(e.event_id in sources and e.event_id in e.references and sources[e.event_id]['kind']=='CHOCH_EVENT','EVENT_IDENTITY_INCONSISTENT')
            need(e.details.get('phase7_alignment')==ctx['phase7_alignment'],'EVENT_CONTEXT_INCONSISTENT')
            occurrence=sources[e.event_id];pivot,broken=occurrence['references']
            need(sources[pivot]['kind']=='CONFIRMED_PIVOT' and sources[broken]['kind']=='CANDLE' and occurrence['level']==e.details['level']==sources[pivot]['price'],'EVENT_IDENTITY_INCONSISTENT')
            need(e.details['event_type']==e.direction+'_CHOCH' and e.details['fresh'] is True and utc(e.available_at)==utc(facts[e.timeframe]['data_as_of']),'EVENT_CHRONOLOGY_INCONSISTENT')
            need(e.event_id==identity(r['symbol'],e.timeframe,'CHOCH_EVENT',e.details['event_type'],e.details['level'],pivot,broken,e.available_at,e.details['confirmation_policy']),'EVENT_IDENTITY_INCONSISTENT')
            # Legacy derive() hashes break pivot + prior structure + break candle,
            # then stores unique refs. Preserve that identity; never mint a replacement.
            prior=[(k,s) for k,s in sources.items() if s['kind']=='CONFIRMED_PIVOT' and s['timeframe']==e.timeframe and utc(s['available_at'])<=utc(e.observed_at)]
            recent=[]
            for kind in ('HIGH','LOW'):recent+=sorted([(k,s) for k,s in prior if s['pivot_kind']==kind],key=lambda item:utc(item[1]['observed_at']))[-2:]
            recent.sort(key=lambda item:(utc(item[1]['observed_at']),item[1]['pivot_kind']))
            identity_refs=[e.event_id,pivot]+[k for k,s in recent]+[broken]
            need(sorted(set(identity_refs))==e.references,'EVENT_REFERENCES_INCONSISTENT')
        need(e.id==identity(r['symbol'],e.timeframe,e.category,e.observed_at,e.available_at,sorted(identity_refs),e.direction,sorted(e.reason_codes),e.details,config.digest,r['intelligence_configuration_sha256']),'CANONICAL_EVIDENCE_IDENTITY_MISMATCH')
        for ref in e.references:need(ref in sources and sources[ref]['timeframe']==e.timeframe and utc(sources[ref]['available_at'])<=utc(e.available_at),'EVIDENCE_REFERENCE_UNAVAILABLE')
        if e.event_id is not None:
            need(e.event_id not in active_events or active_events[e.event_id]==e.id,'CONFLICTING_EVENT_REVISIONS')
            active_events[e.event_id]=e.id
        if e.event_id is not None:need(e.category=='TRANSITION' and e.event_id in e.references and sources[e.event_id]['kind']=='CHOCH_EVENT','EVENT_IDENTITY_INCONSISTENT')
        need(e.id not in canonical or canonical[e.id]==raw,'CONFLICTING_CANONICAL_EVIDENCE')
        canonical[e.id]=raw
    r['evidence']=[canonical[k] for k in sorted(canonical)];es=tuple(Evidence(**e) for e in r['evidence']);aligned={};zones=[]
    for tf,f in facts.items():
        frame=frames[tf];state=frame['structure'];need(state['classification']==ctx[tf.lower()+'_structure'] and f['data_as_of']==ctx[tf.lower()+'_as_of'],'CONTEXT_FRAME_INCONSISTENT')
        need(state['classification'] in ('BULLISH','BEARISH','RANGING','TRANSITIONAL','UNKNOWN') and type(state['insufficient_evidence']) is bool,'CONTEXT_STRUCTURE_INVALID')
        cs=sorted(({'timestamp':s['observed_at'],**s['ohlc']} for s in sources.values() if s['timeframe']==tf and s['kind']=='CANDLE'),key=lambda c:utc(c['timestamp']))
        validate_candles(cs);need(type(f['candle_count']) is int and f['candle_count']==len(cs) and utc(cs[-1]['timestamp'])+timedelta(minutes=1 if tf=='M1' else 5)==utc(f['data_as_of']),'CONTEXT_FRAME_COVERAGE_INCONSISTENT')
        structures=[e for e in es if e.category=='STRUCTURE' and e.timeframe==tf]
        need(len(structures)==1 and structures[0].details['classification']==state['classification'] and set(structures[0].references)==set(state['evidence']),'CONTEXT_STRUCTURE_INCONSISTENT')
        for category,key in (('MOMENTUM','momentum'),('VOLATILITY','volatility')):
            measurements=[e for e in es if e.category==category and e.timeframe==tf]
            need(len(measurements)==1 and measurements[0].details==frame[key]==f[key],'CONTEXT_MEASUREMENTS_INCONSISTENT')
        aligned[tf]=SimpleNamespace(structure=SimpleNamespace(**state),data_as_of=f['data_as_of'],
            events=[SimpleNamespace(event_type=e.details['event_type'],confirmed_at=e.available_at) for e in es if e.category=='TRANSITION' and e.timeframe==tf and e.details.get('fresh')])
        for raw in frame['support_resistance']+frame['supply_demand']:
            exact(raw,Zone);zone=Zone(**raw);need(zone.id in sources and zone.timeframe==tf and set(zone.evidence)<=set(sources),'CONTEXT_ZONE_INCONSISTENT')
            source=sources[zone.id]
            need(zone.id==identity(r['symbol'],tf,zone.kind,zone.evidence,zone.lower,zone.upper) and source['kind']=='ZONE'
                and source['lower']==zone.lower and source['upper']==zone.upper and source['references']==list(zone.evidence)
                and source['observed_at']==zone.origin_at and source['available_at']==zone.confirmed_at,'CONTEXT_ZONE_INCONSISTENT')
            zones.append(zone)
    expected=aggregate(SimpleNamespace(frames=aligned,alignment=align(aligned,at),data_quality={'valid':True}))
    for key in expected:
        if key!='limitations':need(ctx[key]==expected[key],'CONTEXT_ALIGNMENT_INCONSISTENT')
    for tf,frame in frames.items():
        for key in ('momentum','volatility'):
            if frame[key]['status']!='AVAILABLE':expected['limitations'].append(tf+'_'+key.upper()+'_INSUFFICIENT')
    need(ctx['limitations']==expected['limitations'],'CONTEXT_LIMITATIONS_INCONSISTENT')
    scores=confluence.evaluate(es,config,ctx)
    expected_hypotheses=hypotheses.build(es,ctx,tuple(zones),scores,r['analysis_at'],config)
    normalize_h={}
    need(isinstance(r['hypotheses'],list) and len(r['hypotheses'])==len(NAMES),'CONTEXT_HYPOTHESES_INVALID')
    for h in r['hypotheses']:
        exact(h,Hypothesis);need(h['hypothesis_type'] in NAMES and h['hypothesis_type'] not in normalize_h,'CONTEXT_HYPOTHESES_INVALID')
        for key in ('supporting_evidence','contradictory_evidence','relevant_zones'):h[key]=sorted(set(h[key]))
        normalize_h[h['hypothesis_type']]=h
    for h in expected_hypotheses:
        expected_h=plain(asdict(h))
        for key in ('supporting_evidence','contradictory_evidence','relevant_zones'):expected_h[key]=sorted(set(expected_h[key]))
        need(normalize_h[h.hypothesis_type]==expected_h,'CONTEXT_HYPOTHESIS_INCONSISTENT')
    r['hypotheses']=[normalize_h[k] for k in sorted(normalize_h)]
    weighted=r['confluence']['weighted_evidence'];need(isinstance(weighted,list),'CONFLUENCE_INCONSISTENT')
    unique_weights={digest(v):v for v in weighted};r['confluence']['weighted_evidence']=sorted(unique_weights.values(),key=lambda e:e['evidence_id'])
    need(r['confluence']==plain(scores) and r['abstention_reasons']==scores['abstention_reasons'],'CONFLUENCE_INCONSISTENT')
    return r


def _base():
    return {'scenario_assessment_version':1,'model_version':MODEL,'status':'BLOCKED','analysis_at':None,'symbol':None,'provenance':None,
        'market_regime':'UNKNOWN','m1_m5_alignment':None,'configuration_hashes':{},'context_report_sha256':None,
        'selected_hypothesis':None,'selection_source':'CONTEXT_CONFLUENCE_UNMODIFIED_NOT_AUTHORIZATION',
        'score_kind':SCORE_KIND,'ranked_hypotheses':[],'leading_hypotheses':[],'evidence_index':[],
        'fresh_opposing_m1_choch':[],'abstention_reasons':[],'reason_codes':[],'limitations':list(LIMITATIONS),
        'explanation':[],'source_explanation':[],'historical_validation':'PENDING','historical_comparisons':'NOT_RUN',
        'qualification':'DATA_NOT_QUALIFIED','exness':'BLOCKED','mode':'READ_ONLY_SHADOW','signal':'WAIT',
        'execution_allowed':False,'broker_access':False,'orders_requested':0,'profitability_tested':False}


def assess_scenarios(report,*,as_of=None):
    """Accept ContextReport or its exact to_dict schema. No mutation or new selection."""
    out=_base()
    try:
        r,config,at=_normalize(report)
        out.update(analysis_at=r['analysis_at'],symbol=r['symbol'],provenance=r['provenance'])
        selected=r['confluence']['selected_hypothesis'];need(selected in NAMES,'CONFLUENCE_INCONSISTENT');out['selected_hypothesis']=selected
        need(as_of is None or isinstance(as_of,(str,datetime)),'ASSESSMENT_CUTOFF_INVALID')
        cutoff=at if as_of is None else utc(as_of.isoformat() if isinstance(as_of,datetime) else as_of)
        need(at<=cutoff,'FUTURE_CONTEXT_REPORT')
        need(at==cutoff,'CONTEXT_ASSESSMENT_CUTOFF_MISMATCH')
        reasons={d['code'] for d in r['data_quality']['diagnostics'] if d['code']!='DATA_VALID'}
        if not r['data_quality']['valid']:
            out.update(abstention_reasons=codes(r['abstention_reasons']),reason_codes=sorted(reasons|{'BLOCKED_DATA_QUALITY'}),
                explanation=['Upstream data quality is blocked; no hypotheses or evidence are assessed.'])
            return dict(out,sha256=digest(out))
        r=_validated_view(r,config,at)
        out.update(status='ABSTAINED' if r['abstention_reasons'] or selected==NO_DIRECTION else 'ASSESSED',
            market_regime=r['context']['classification'],m1_m5_alignment=plain(r['context']),
            configuration_hashes={'context':r['configuration_sha256'],'intelligence':r['intelligence_configuration_sha256']},
            context_report_sha256=digest(r),abstention_reasons=r['abstention_reasons'],
            reason_codes=sorted(reasons|set(r['abstention_reasons'])),fresh_opposing_m1_choch=r['confluence']['fresh_opposing_m1_choch'],
            limitations=sorted(set(LIMITATIONS+r['context']['limitations'])),source_explanation=r['explanation'])
        values=sorted({h['heuristic_score'] for h in r['hypotheses']},reverse=True)
        for h in sorted(r['hypotheses'],key=lambda h:(-h['heuristic_score'],h['hypothesis_type'])):
            row=plain(h);row.update(rank=values.index(h['heuristic_score'])+1,selected_by_context=h['hypothesis_type']==selected,
                explanation='Inherited heuristic score and evidence; rank is a display order, not a prediction or authorization.')
            out['ranked_hypotheses'].append(row)
        out['leading_hypotheses']=[h['hypothesis_type'] for h in out['ranked_hypotheses'] if h['rank']==1]
        out['evidence_index']=[{k:e[k] for k in ('id','event_id','category','timeframe','direction','observed_at','available_at','references','reason_codes')} for e in r['evidence']]
        out['explanation']=['Regime and M1/M5 alignment are inherited ContextReport classifications.',
            'Ranks preserve score ties; the upstream selected hypothesis is retained independently of display rank.',
            'Heuristic scores are not probabilities, predictions, trading signals or execution permission.']
    except (ValueError,TypeError,KeyError,AttributeError,IndexError,OverflowError,RecursionError) as exc:
        out.update(status='BLOCKED',reason_codes=[str(exc) if isinstance(exc,ScenarioInputError) else 'CONTEXT_REPORT_INVALID'],
            abstention_reasons=['SCENARIO_INPUT_UNESTABLISHED'],ranked_hypotheses=[],leading_hypotheses=[],evidence_index=[],
            explanation=['Context integrity or chronology could not be established; assessment withheld.'])
    return dict(out,sha256=digest(out))


def _adapter_blocked():
    out=_base();out.update(reason_codes=['UPSTREAM_GATED_CONTEXT_REQUIRED'],abstention_reasons=['SCENARIO_INPUT_UNESTABLISHED'],
        explanation=['Raw causal adapters are synthetic-fixture helpers; use an existing gated ContextReport for other provenance.'])
    return dict(out,sha256=digest(out))


def scenario_at(symbol,m1_history,m5_history,as_of,**options):
    """Synthetic-fixture helper using the existing causal prefix/quality path."""
    if options.get('provenance','SYNTHETIC_RESEARCH')!='SYNTHETIC_RESEARCH':return _adapter_blocked()
    try:return assess_scenarios(context_at(symbol,m1_history,m5_history,as_of,**options),as_of=as_of)
    except (ValueError,TypeError,KeyError,OverflowError):return assess_scenarios(None)


def replay_scenarios(symbol,m1_history,m5_history,**options):
    """Synthetic replay views, with no accumulated scores or historical gate bypass."""
    if options.get('provenance','SYNTHETIC_RESEARCH')!='SYNTHETIC_RESEARCH':
        yield _adapter_blocked();return
    try:
        for entry in replay_context(symbol,m1_history,m5_history,**options):yield assess_scenarios(entry['report'])
    except (ValueError,TypeError,KeyError,OverflowError):yield assess_scenarios(None)


def validate_scenario_assessment(report):
    """Integrity/safety validation of a serialized view; never grants qualification."""
    need(isinstance(report,dict) and set(report)==set(_base())|{'sha256'},'SCENARIO_SCHEMA_INVALID')
    need(report['sha256']==digest({k:v for k,v in report.items() if k!='sha256'}),'SCENARIO_CHECKSUM_MISMATCH')
    need(type(report['scenario_assessment_version']) is int and report['scenario_assessment_version']==1 and report['model_version']==MODEL,'SCENARIO_VERSION_UNSUPPORTED')
    base=_base()
    for key in ('mode','signal','exness','qualification','historical_validation','historical_comparisons','score_kind','selection_source'):
        need(report[key]==base[key],'SCENARIO_SAFETY_CONTRACT_INVALID')
    for key in ('execution_allowed','broker_access','profitability_tested'):need(report[key] is False,'SCENARIO_SAFETY_CONTRACT_INVALID')
    need(type(report['orders_requested']) is int and report['orders_requested']==0,'SCENARIO_SAFETY_CONTRACT_INVALID')
    need(report['status'] in ('BLOCKED','ABSTAINED','ASSESSED') and report['selected_hypothesis'] in NAMES|{None},'SCENARIO_STATUS_INVALID')
    codes(report['reason_codes']);codes(report['abstention_reasons'])
    if report['status']=='BLOCKED':
        need(not report['ranked_hypotheses'] and not report['leading_hypotheses'] and not report['evidence_index'],'BLOCKED_SCENARIO_HAS_EVIDENCE')
        return True
    need(report['selected_hypothesis'] in NAMES and
        (report['status']!='ASSESSED' or report['selected_hypothesis']!=NO_DIRECTION),'SCENARIO_SELECTION_INVALID')
    at=utc(report['analysis_at']);_chronology(report,at)
    ids=[e['id'] for e in report['evidence_index']];need(ids==sorted(set(ids)),'SCENARIO_EVIDENCE_INCONSISTENT')
    hs=report['ranked_hypotheses'];need(len(hs)==len(NAMES) and {h['hypothesis_type'] for h in hs}==NAMES,'SCENARIO_HYPOTHESES_INCONSISTENT')
    need(hs==sorted(hs,key=lambda h:(-h['heuristic_score'],h['hypothesis_type'])),'SCENARIO_RANK_INVALID')
    need(all(type(h['selected_by_context']) is bool for h in hs) and
        sum(h['selected_by_context'] for h in hs)==1,'SCENARIO_SELECTION_INVALID')
    values=sorted({h['heuristic_score'] for h in hs},reverse=True)
    for h in hs:
        need(h['score_kind']==SCORE_KIND and h['rank']==values.index(h['heuristic_score'])+1 and h['selected_by_context']==(h['hypothesis_type']==report['selected_hypothesis']),'SCENARIO_RANK_INVALID')
        need(set(h['supporting_evidence'])|set(h['contradictory_evidence'])<=set(ids),'SCENARIO_EVIDENCE_INCONSISTENT')
    need(report['leading_hypotheses']==[h['hypothesis_type'] for h in hs if h['rank']==1],'SCENARIO_RANK_INVALID')
    need((report['status']=='ABSTAINED')==bool(report['abstention_reasons'] or report['selected_hypothesis']==NO_DIRECTION),'SCENARIO_STATUS_INVALID')
    return True
