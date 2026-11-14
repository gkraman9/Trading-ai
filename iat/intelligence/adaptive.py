"""Adaptive Market Intelligence v1: causal regime-conditioned research, never execution."""
from copy import deepcopy
from dataclasses import asdict,replace
from datetime import datetime,timedelta
from iat.replay_dataset import utc
from iat.intelligence.context import context_at
from iat.intelligence.context_models import ContextReport,ContextConfig
from iat.intelligence.models import iso
from iat.intelligence.engine import _finite_tree
from iat.intelligence.strategies import evaluate_strategies
from iat.intelligence.strategy_registry import registry
from iat.intelligence.strategy_replay import digest
from iat.intelligence.adaptive_models import AdaptiveConfig,COMPATIBILITY,RANKING
from iat.intelligence import confluence


STATES={'BULLISH','BEARISH','RANGING','TRANSITIONAL'}


def _fresh_changes(report):
    current=report.observed_facts.get('M1',{}).get('data_as_of')
    return [e for e in report.evidence if e.category=='TRANSITION' and e.timeframe=='M1'
            and e.direction in ('BULLISH','BEARISH') and e.details.get('fresh') is True
            and e.details.get('event_type')==e.direction+'_CHOCH'
            and current is not None and utc(e.available_at)==utc(current)]


def _regime(report):
    classifications={};support=[]
    sources=report.interpretations.get('source_registry',{})
    for tf in ('M1','M5'):
        es=[e for e in report.evidence if e.category=='STRUCTURE' and e.timeframe==tf]
        frame=report.observed_facts.get(tf)
        if not frame or len(es)!=1 or 'INSUFFICIENT_STRUCTURAL_CONTEXT' in report.context.get('limitations',[]):
            return 'UNKNOWN',[],['CONFIRMED_M1_M5_STRUCTURE_REQUIRED']
        e=es[0];state=e.details.get('classification')
        pivots=[sources[r] for r in set(e.references) if r in sources and sources[r].get('kind')=='CONFIRMED_PIVOT' and sources[r].get('timeframe')==tf]
        if (state not in STATES or e.direction!=(state if state in ('BULLISH','BEARISH','RANGING') else 'NEUTRAL')
                or report.context.get(tf.lower()+'_structure')!=state
                or sum(p.get('pivot_kind')=='HIGH' for p in pivots)<2
                or sum(p.get('pivot_kind')=='LOW' for p in pivots)<2
                or utc(e.available_at)>utc(frame['data_as_of'])):
            return 'UNKNOWN',[],['CONFIRMED_M1_M5_STRUCTURE_REQUIRED']
        classifications[tf]=state;support.append(e.id)
    one,five=classifications['M1'],classifications['M5']
    fresh=_fresh_changes(report)
    opposing=[e for e in fresh if five not in ('BULLISH','BEARISH') or e.direction!=five]
    if opposing:
        return 'TRANSITION',support+[e.id for e in opposing],['FRESH_M1_STRUCTURE_CHANGE_AGAINST_M5']
    if one==five=='BULLISH':return 'TREND_UP',support,['CONFIRMED_UP_STRUCTURE_BOTH_FRAMES']
    if one==five=='BEARISH':return 'TREND_DOWN',support,['CONFIRMED_DOWN_STRUCTURE_BOTH_FRAMES']
    if one==five=='RANGING':return 'RANGE',support,['CONFIRMED_RANGE_BOTH_FRAMES']
    return 'TRANSITION',support,['CONFIRMED_STRUCTURE_DISAGREEMENT_OR_TRANSITION']


def _volatility(report):
    frames={}
    for tf in ('M1','M5'):
        measured=report.interpretations.get('frames',{}).get(tf,{}).get('volatility')
        frames[tf]=deepcopy(measured) if measured else {'status':'INSUFFICIENT_EVIDENCE','regime':'INSUFFICIENT_EVIDENCE'}
    regimes=[v['regime'] for v in frames.values()]
    if 'HIGH_VOLATILITY' in regimes:overall='HIGH'
    elif any(v not in ('LOW_VOLATILITY','NORMAL_VOLATILITY') for v in regimes):overall='UNKNOWN'
    elif len(set(regimes))>1:overall='MIXED'
    else:overall='LOW' if regimes[0]=='LOW_VOLATILITY' else 'NORMAL'
    return {'overall':overall,'aggregation':'ANY_FRAME_HIGH_OTHERWISE_BOTH_FRAMES_REQUIRED','frames':frames}


def _rank(rows):
    values=sorted({r['heuristic_score'] for r in rows if r['heuristic_score'] is not None},reverse=True)
    for r in rows:r['rank']=values.index(r['heuristic_score'])+1 if r['heuristic_score'] is not None else None


def _scenarios(report,config,regime):
    # Reuse the current category/timeframe/direction caps and configured weights.
    view={'classification':report.context.get('classification','UNKNOWN'),
          'm5_structure':report.context.get('m5_structure','UNKNOWN'),
          'limitations':report.context.get('limitations',[])}
    votes=confluence.evaluate(report.evidence,config,view)
    scenarios=[]
    for name,direction in (('BULLISH','BULLISH'),('BEARISH','BEARISH'),('NEUTRAL','RANGING')):
        support=sorted(e.id for e in report.evidence if e.direction==direction)
        opposition=sorted(e.id for e in report.evidence if e.direction in ('BULLISH','BEARISH','RANGING') and e.direction!=direction)
        own=votes['scores'][direction];against=max(v for d,v in votes['scores'].items() if d!=direction)
        scenarios.append({'scenario':name,'supporting_evidence':support,'opposing_evidence':opposition,
                          'score_kind':RANKING['score_kind'],'support_score':own,'opposition_score':against,
                          'heuristic_score':own-against,'rank':None,
                          'assumptions':['DATA_REMAINS_ELIGIBLE','OHLC_INTERPRETATIONS_ARE_NOT_FORECASTS',
                                         'RANGE_EVIDENCE_SUPPORTS_NEUTRAL' if name=='NEUTRAL' else 'DIRECTIONAL_EVIDENCE_PERSISTS'],
                          'invalidation_conditions':['DATA_OR_SESSION_GATE_FAILS',
                              'CONFIRMED_DIRECTIONAL_BREAK_ENDS_RANGE' if name=='NEUTRAL' else 'NEW_OPPOSING_CONFIRMED_STRUCTURE_OR_CHoCH'],
                          'assessment_would_change_with':['ADDITIONAL_CLOSED_M1_M5_CANDLES',
                              'NEW_CONFIRMED_PIVOTS_OR_STRUCTURE_CHANGE','NEW_ZONE_OR_SWEEP_CONFIRMATION',
                              'CONFIRMED_DIRECTIONAL_RANGE_BREAK' if name=='NEUTRAL' else
                              'FRESH_'+('BEARISH' if name=='BULLISH' else 'BULLISH')+'_M1_CHOCH']})
    _rank(scenarios)
    return scenarios,votes


def _safe_contract(report,config):
    if report.provenance not in ('SYNTHETIC_RESEARCH','HISTORICAL_RESEARCH'):return 'OFFLINE_RESEARCH_PROVENANCE_REQUIRED'
    if config.digest!=report.configuration_sha256:return 'CONTEXT_CONFIGURATION_HASH_MISMATCH'
    try:
        _finite_tree(report.to_dict())
        at=utc(report.analysis_at);sources=report.interpretations.get('source_registry',{})
        ids={}
        for e in report.evidence:
            if e.id in ids and ids[e.id]!=e:return 'CONFLICTING_EVIDENCE_IDENTITY'
            ids[e.id]=e
            if (utc(e.observed_at)>utc(e.available_at) or utc(e.available_at)>at
                    or any(r not in sources or utc(sources[r]['available_at'])>utc(e.available_at) for r in e.references)):
                return 'EVIDENCE_UNAVAILABLE_AT_TIMESTAMP'
        for source in sources.values():
            if utc(source['available_at'])>at:return 'EVIDENCE_UNAVAILABLE_AT_TIMESTAMP'
        for frame in report.observed_facts.values():
            if utc(frame['data_as_of'])>at:return 'UNCLOSED_FRAME'
    except (ValueError,TypeError,KeyError,OverflowError):return 'ADAPTIVE_OBSERVATION_CONTRACT_INVALID'
    return None


def assess_adaptive(report, *, adaptive_config=None, session_sha256=None, finality_sha256=None):
    """Consume a typed context contract; adaptive_at is the gated raw-OHLC path."""
    if not isinstance(report,ContextReport):raise ValueError('Typed context report required')
    policy=AdaptiveConfig() if adaptive_config is None else adaptive_config
    if not isinstance(policy,AdaptiveConfig):raise ValueError('Typed adaptive configuration required')
    try:config=ContextConfig.from_dict(report.configuration)
    except (ValueError,TypeError):config=None
    blocked=not report.data_quality['valid']
    problem=_safe_contract(report,config) if config is not None else 'CONTEXT_CONFIGURATION_INVALID'
    if problem:blocked=True
    regime,regime_refs,codes=('UNKNOWN',[],['BLOCKED_DATA_QUALITY' if not report.data_quality['valid'] else problem]) if blocked else _regime(report)
    status='BLOCKED' if blocked else 'UNKNOWN' if regime=='UNKNOWN' else 'READY'
    reasons=set(codes);uncertainty={'EXPERIMENTAL_RULES_NO_VALIDATED_EDGE','HISTORICAL_SOURCE_ELIGIBILITY_UNESTABLISHED'}
    if problem:reasons.add(problem)
    reasons.update(d['code'] for d in report.data_quality.get('diagnostics',[]) if d.get('severity')=='ERROR')
    volatility=_volatility(report) if not blocked else {'overall':'UNKNOWN','frames':{},'aggregation':'QUARANTINED'}
    if volatility['overall']=='HIGH':uncertainty.add('HIGH_VOLATILITY_RESEARCH_CAUTION')
    if volatility['overall']=='UNKNOWN':uncertainty.add('VOLATILITY_EVIDENCE_INCOMPLETE')
    for tf,v in volatility['frames'].items():
        if v.get('status')!='AVAILABLE':uncertainty.add(tf+'_VOLATILITY_EVIDENCE_INCOMPLETE')
    uncertainty.update(report.context.get('limitations',[]))
    uncertainty.update(d['code'] for d in report.data_quality.get('diagnostics',[]) if d.get('severity')=='WARNING')
    candidates=[];scenarios=[];votes=None;conflicts=[]
    if not blocked:
        strategy_report=evaluate_strategies(report)
        if regime!='UNKNOWN':scenarios,votes=_scenarios(report,config,regime)
        for r in strategy_report['evaluations']:
            compatibility=COMPATIBILITY[r['strategy_id']].get(regime,{}).get(r['direction'],'UNKNOWN')
            eligible=status=='READY' and r['status']=='QUALIFIES' and compatibility=='SUPPORTED'
            candidate=deepcopy(r)
            candidate.update(rule_status=candidate.pop('status'),compatibility=compatibility,
                             compatibility_version=policy.compatibility_version,
                             assessment_status='CANDIDATE' if eligible else 'UNKNOWN' if status=='UNKNOWN' else
                                'RULES_FAILED' if r['status']!='QUALIFIES' else 'REGIME_UNSUITABLE',
                             heuristic_score=next(s['heuristic_score'] for s in scenarios if s['scenario']==r['direction']) if eligible else None,
                             score_kind=RANKING['score_kind'],rank=None,
                             assessment_reason_codes=sorted(set(r['reason_codes']+['REGIME_'+compatibility])))
            candidates.append(candidate)
        fresh=_fresh_changes(report)
        opposite=[e.id for e in fresh if report.context.get('m5_structure') in ('BULLISH','BEARISH') and e.direction!=report.context['m5_structure']]
        if opposite:conflicts.append({'reason_code':'FRESH_OPPOSING_M1_CHOCH','evidence_ids':sorted(opposite)})
        if report.context.get('m1_structure')!=report.context.get('m5_structure'):
            conflicts.append({'reason_code':'M1_M5_STRUCTURE_DISAGREEMENT','evidence_ids':sorted(regime_refs)})
        if votes:
            if votes['scores']['BULLISH']>0 and votes['scores']['BEARISH']>0:
                conflicts.append({'reason_code':'BIDIRECTIONAL_EVIDENCE_PRESENT',
                                  'evidence_ids':sorted(e.id for e in report.evidence if e.direction in ('BULLISH','BEARISH'))})
            uncertainty.update(votes['abstention_reasons'])
            for e in report.evidence:
                if e.category=='TRANSITION' and e.id not in opposite and report.context.get('m5_structure') in ('BULLISH','BEARISH') and e.direction!=report.context['m5_structure']:
                    uncertainty.add('NONCURRENT_TRANSITION_EVIDENCE_PRESENT')
    else:
        for spec in registry()['strategies']:
            for direction in ('BULLISH','BEARISH'):
                candidates.append({'strategy_id':spec['strategy_id'],'rule_version':spec['rule_version'],'direction':direction,
                                   'rule_status':'NOT_EVALUATED','compatibility':'UNKNOWN','compatibility_version':1,
                                   'assessment_status':'BLOCKED','supporting_evidence':[],'contradictory_evidence':[],
                                   'reason_codes':sorted(reasons),'assessment_reason_codes':sorted(reasons),
                                   'heuristic_score':None,'score_kind':RANKING['score_kind'],'rank':None})
    _rank(candidates)
    candidate_leaders=[{'strategy_id':r['strategy_id'],'direction':r['direction']} for r in candidates if r['rank']==1]
    scenario_leaders=[s['scenario'] for s in scenarios if s['rank']==1]
    if not scenarios:
        for name in ('BULLISH','BEARISH','NEUTRAL'):
            scenarios.append({'scenario':name,'supporting_evidence':[],'opposing_evidence':[],
                'score_kind':RANKING['score_kind'],'support_score':None,'opposition_score':None,'heuristic_score':None,'rank':None,
                'assumptions':['ELIGIBLE_CONFIRMED_STRUCTURE_REQUIRED'],
                'invalidation_conditions':['DATA_OR_SESSION_GATE_FAILS'],
                'assessment_would_change_with':['ELIGIBLE_CLOSED_M1_M5_HISTORY','TWO_CONFIRMED_HIGHS_AND_LOWS_PER_FRAME']})
    if not candidate_leaders:reasons.add('NO_SUITABLE_STRATEGY_CANDIDATE')
    if len(candidate_leaders)>1:uncertainty.add('MULTIPLE_TOP_CANDIDATES')
    if any(c['rank']==1 and c['heuristic_score']<=0 for c in candidates):uncertainty.add('NONPOSITIVE_TOP_CANDIDATE_HEURISTIC')
    if any(c['rank']==1 and c['direction'] not in scenario_leaders for c in candidates):uncertainty.add('TOP_CANDIDATE_SCENARIO_NOT_LEADING')
    if len(scenario_leaders)>1:uncertainty.add('SCENARIO_SCORE_TIE')
    evidence=[] if blocked else [asdict(e) for e in sorted(report.evidence,key=lambda e:e.id)]
    facts={} if blocked else {'closed_frames':{tf:{k:v for k,v in f.items() if k in ('data_as_of','candle_count')}
                                             for tf,f in report.observed_facts.items()},
                             'candles':{k:deepcopy(v) for k,v in report.interpretations.get('source_registry',{}).items() if v['kind']=='CANDLE'}}
    result={'report_version':1,'model_version':'IAT_ADAPTIVE_MARKET_INTELLIGENCE_V1','symbol':report.symbol,
            'timestamp_utc':iso(utc(report.analysis_at)),'provenance':report.provenance if report.provenance in ('SYNTHETIC_RESEARCH','HISTORICAL_RESEARCH') else 'UNVERIFIED','status':status,
            'policy_versions':asdict(policy),
            'observation_contract':{'valid':problem is None,'reason_codes':[problem] if problem else []},
            'regime':{'directional':regime,'supporting_evidence':sorted(regime_refs),'reason_codes':codes},
            'volatility':volatility,'data_quality':deepcopy(report.data_quality),
            'observed_facts':facts,'interpretations':{'evidence':evidence,'existing_context':{} if blocked else deepcopy(report.context),
                'sources':{} if blocked else deepcopy(report.interpretations.get('source_registry',{})),
                'confluence_votes':votes},
            'assessment':{'candidate_assessments':candidates,'scenarios':scenarios,'top_candidates':candidate_leaders,
                          'top_scenarios':scenario_leaders,'score_kind':RANKING['score_kind']},
            'conflicts':conflicts,'uncertainty':sorted(uncertainty),'reason_codes':sorted(reasons),
            'configuration_hashes':{'context':report.configuration_sha256,'intelligence':report.intelligence_configuration_sha256,
                'strategy_registry':registry()['sha256'],'adaptive':policy.digest,'compatibility':digest(COMPATIBILITY),
                'ranking':digest(RANKING),'session':session_sha256,'observed_finality':finality_sha256},
            'historical_validation':'PENDING','historical_decision_log_comparisons':'NOT_RUN',
            'exness':'BLOCKED','mode':'READ_ONLY_SHADOW','signal':'WAIT','execution_allowed':False}
    _finite_tree(result)
    result['sha256']=digest(result)
    validate_adaptive_report(result)
    return result


def adaptive_at(symbol,m1_history,m5_history,as_of,*,adaptive_config=None,**options):
    """Pure offline causal query; no broker/provider/network access."""
    try:
        report=context_at(symbol,m1_history,m5_history,as_of,**options)
    except (ValueError,TypeError,KeyError,OverflowError):
        # Keep configuration/session gates; invalid request options still raise here.
        report=context_at(symbol,None,None,as_of,**options)
        quality=deepcopy(report.data_quality)
        quality['diagnostics'].append({'code':'ADAPTIVE_HISTORY_SELECTION_FAILED','severity':'ERROR',
                                       'message':'A causal closed history could not be selected safely.'})
        report=replace(report,data_quality=quality)
    calendar=options.get('calendar')
    session=None
    if calendar is not None:
        if hasattr(calendar,'configuration_sha256'):session=calendar.configuration_sha256
        else:
            data=asdict(calendar);data['coverage_start']=iso(calendar.coverage_start);data['coverage_end']=iso(calendar.coverage_end)
            data['windows']=[[iso(a),iso(b)] for a,b in calendar.windows];session=digest(data)
    finality=options.get('observed_finality')
    return assess_adaptive(report,adaptive_config=adaptive_config,session_sha256=session,
                           finality_sha256=digest(finality) if finality is not None else None)


def replay_adaptive(symbol,m1_history,m5_history,*,as_of=None,**options):
    """Chronological snapshot sequence for software repeat/prefix research checks."""
    previous=None
    for index,row in enumerate(m1_history):
        at=utc(row['timestamp'])+timedelta(minutes=1)
        if as_of is not None and at>utc(iso(as_of)):break
        if index>=5000:raise ValueError('Adaptive visible history limit exceeded')
        if previous is not None and at<=previous:raise ValueError('Adaptive replay must be chronological')
        yield adaptive_at(symbol,m1_history,m5_history,at,**options)
        previous=at


def validate_adaptive_report(report):
    """Safety/version/checksum and causal reference checks for serialized reports."""
    if (type(report['report_version']) is not int or report['report_version']!=1
            or report['model_version']!='IAT_ADAPTIVE_MARKET_INTELLIGENCE_V1'
            or report['status'] not in ('READY','UNKNOWN','BLOCKED')
            or report['regime']['directional'] not in ('TREND_UP','TREND_DOWN','RANGE','TRANSITION','UNKNOWN')
            or report['mode']!='READ_ONLY_SHADOW' or report['signal']!='WAIT' or report['execution_allowed'] is not False
            or report['exness']!='BLOCKED' or report['historical_validation']!='PENDING'
            or report['historical_decision_log_comparisons']!='NOT_RUN'):
        raise ValueError('Unsafe/unsupported adaptive report')
    if (report['status']=='READY')!=(report['regime']['directional']!='UNKNOWN') or not report['data_quality']['valid'] and report['status']!='BLOCKED':
        raise ValueError('Adaptive availability/regime mismatch')
    _finite_tree(report)
    if digest({k:v for k,v in report.items() if k!='sha256'})!=report['sha256']:
        raise ValueError('Adaptive report checksum mismatch')
    if (AdaptiveConfig(**report['policy_versions']).digest!=report['configuration_hashes']['adaptive']
            or report['configuration_hashes']['strategy_registry']!=registry()['sha256']
            or report['configuration_hashes']['compatibility']!=digest(COMPATIBILITY)
            or report['configuration_hashes']['ranking']!=digest(RANKING)):
        raise ValueError('Adaptive policy hash mismatch')
    at=utc(report['timestamp_utc']);interpretations=report['interpretations']
    refs=set(interpretations['sources']);es={e['id']:e for e in interpretations['evidence']}
    for e in interpretations['evidence']:
        if utc(e['available_at'])>at or not set(e['references'])<=refs:raise ValueError('Unavailable adaptive evidence')
    for source in interpretations['sources'].values():
        if utc(source['available_at'])>at:raise ValueError('Future adaptive source')
    candidates=report['assessment']['candidate_assessments'];scenarios=report['assessment']['scenarios']
    expected={(s['strategy_id'],d) for s in registry()['strategies'] for d in ('BULLISH','BEARISH')}
    if len(candidates)!=4 or {(c['strategy_id'],c['direction']) for c in candidates}!=expected:
        raise ValueError('Incomplete adaptive candidates')
    if len(scenarios)!=3 or {s['scenario'] for s in scenarios}!={'BULLISH','BEARISH','NEUTRAL'}:
        raise ValueError('Incomplete adaptive scenarios')
    for s in scenarios:
        if not (set(s['supporting_evidence'])|set(s['opposing_evidence']))<=set(es):raise ValueError('Unresolved scenario evidence')
    versions={s['strategy_id']:s['rule_version'] for s in registry()['strategies']}
    for c in candidates:
        if c['rule_version']!=versions[c['strategy_id']] or type(c['compatibility_version']) is not int or c['compatibility_version']!=1:
            raise ValueError('Unsupported candidate rule/policy version')
        if c['rule_status'] not in ('QUALIFIES','ABSTAINS','INVALIDATED','NOT_EVALUATED'):
            raise ValueError('Unknown underlying strategy outcome')
        if not (set(c['supporting_evidence'])|set(c['contradictory_evidence']))<=refs|set(es):raise ValueError('Unresolved candidate evidence')
        fit=COMPATIBILITY[c['strategy_id']].get(report['regime']['directional'],{}).get(c['direction'],'UNKNOWN')
        eligible=report['status']=='READY' and c['rule_status']=='QUALIFIES' and fit=='SUPPORTED'
        if (c['compatibility']!=fit or (c['assessment_status']=='CANDIDATE')!=eligible
                or (c['heuristic_score'] is not None)!=eligible):
            raise ValueError('Adaptive candidate bypassed compatibility/rules')
    for rows in (candidates,scenarios):
        ranked=deepcopy(rows);_rank(ranked)
        if [r['rank'] for r in rows]!=[r['rank'] for r in ranked]:raise ValueError('Inconsistent adaptive ranks')
        if any(r['score_kind']!=RANKING['score_kind'] for r in rows):raise ValueError('Unlabeled research score')
    if [s['scenario'] for s in scenarios if s['rank']==1]!=report['assessment']['top_scenarios']:
        raise ValueError('Adaptive scenario leaders mismatch')
    for s in scenarios:
        if s['heuristic_score'] is not None and s['heuristic_score']!=s['support_score']-s['opposition_score']:
            raise ValueError('Adaptive scenario score mismatch')
    for c in candidates:
        if c['heuristic_score'] is not None and c['heuristic_score']!=next(s['heuristic_score'] for s in scenarios if s['scenario']==c['direction']):
            raise ValueError('Adaptive candidate score mismatch')
    tops=[{'strategy_id':c['strategy_id'],'direction':c['direction']} for c in candidates if c['rank']==1]
    if tops!=report['assessment']['top_candidates']:raise ValueError('Adaptive candidate leaders mismatch')
    if report['status']!='READY' and (tops or any(s['heuristic_score'] is not None for s in scenarios)):
        raise ValueError('Unavailable context cannot be ranked')
    return True
