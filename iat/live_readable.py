"""Evidence-grounded presentation only. No market classification or selection rules."""
from copy import deepcopy
from iat.intelligence.strategy_replay import digest

LABELS={'BULLISH':'bullish','BEARISH':'bearish','RANGING':'ranging','TRANSITIONAL':'transitional',
        'TRANSITION':'transitional','UNKNOWN':'uncertain','BULLISH_ALIGNMENT':'bullishly aligned',
        'BEARISH_ALIGNMENT':'bearishly aligned','RANGING_OR_MIXED':'ranging or mixed',
        'STRUCTURAL_CONFLICT':'in disagreement','COUNTERTREND_TRANSITION':'in a countertrend transition',
        'INSUFFICIENT_EVIDENCE':'not yet established'}
RELATIONS={'HH':'Higher high','HL':'Higher low','LH':'Lower high','LL':'Lower low','EH':'Equal high','EL':'Equal low'}
EVENT_NAMES={'WICK_PENETRATION':'Wick penetration of a confirmed level','FAILED_STRUCTURAL_BREAK':'Failed structural break','POTENTIAL_LIQUIDITY_SWEEP':'Potential liquidity sweep (OHLC proxy)'}

def event_label(value):
    if value.endswith('_CHOCH'):return value.split('_')[0].lower()+' change of character (CHoCH)'
    if value.endswith('_BOS'):return value.split('_')[0].lower()+' break of structure (BOS)'
    return EVENT_NAMES.get(value,value.replace('_',' ').lower())

CATEGORY={'STRUCTURE':'confirmed structure','TRANSITION':'confirmed structure change','SUPPORT_RESISTANCE':'support or resistance',
          'SUPPLY_DEMAND':'supply or demand','LIQUIDITY':'liquidity observation','MOMENTUM':'candle momentum',
          'CANDLE':'candlestick pattern','VOLATILITY':'volatility'}
REASONS={
 'OBSERVER_POLL_FAILED':('integrity','The observer encountered unexpected input and is waiting for a safe fresh snapshot.'),
 'BAR_UNCLOSED':('integrity','A returned candle is forming or future-dated; it cannot enter closed-candle analysis.'),
 'OHLC_MALFORMED':('integrity','Received prices are invalid or inconsistent; analysis is withheld.'),
 'M1_M5_OHLC_MISMATCH':('integrity','The received M1 and M5 candles disagree on their overlapping OHLC values.'),
 'TICK_FUTURE_OR_TIME_BASIS_AMBIGUOUS':('freshness','Quote timing conflicts with the local UTC clock; the time basis needs review.'),
 'TIMESTAMP_BASIS_UNVERIFIED':('freshness','The provider timestamp convention has not been established.'),
 'SESSION_CALENDAR_UNAVAILABLE':('session','Current broker session coverage has not been independently verified.'),
 'SESSION_CLOSED':('session','The configured session gate is closed.'),
 'GAP_UNVERIFIED':('integrity','The received history contains a gap that cannot be explained by a verified session calendar.'),
 'PROVIDER_DISCONNECTED':('connection','The terminal is disconnected. Previous market observations are withheld.'),
 'PROVIDER_UNAVAILABLE':('connection','The MT5 data provider is unavailable.'),
 'HISTORY_INCOMPLETE':('structure','There are not enough received closed candles. IAT does not fill missing history.'),
 'DATA_STALE':('freshness','The closed-candle history is stale.'),
 'TICK_STALE':('freshness','The latest Bid is stale. Previous prices and analysis are withheld.'),
 'OBSERVER_STALLED':('freshness','The observer has stopped updating; cached analysis is withheld.'),
 'CLOCK_MOVED_BACKWARD':('freshness','The acquisition clock moved backward, so chronology cannot be established.'),
 'CONFLICTING_TIMEFRAME_STRUCTURE':('mixed_timeframes','M1 and M5 provide conflicting directional structure.'),
 'INSUFFICIENT_STRUCTURAL_CONTEXT':('structure','Confirmed swing evidence is insufficient for a structural assessment.'),
 'INSUFFICIENT_HEURISTIC_SUPPORT':('structure','Existing evidence does not meet the unchanged confluence requirements.'),
 'HEURISTIC_MARGIN_TOO_SMALL':('mixed_timeframes','The evidence does not clearly distinguish the competing directions.'),
 'MATERIAL_OPPOSING_EVIDENCE':('mixed_timeframes','Material opposing evidence prevents a clear assessment.'),
 'FRESH_OPPOSING_M1_CHOCH':('mixed_timeframes','A fresh opposing M1 change of character conflicts with the broader context.'),
 'TRADING_PERMISSIONS_NOT_DISABLED':('safety','Keep Algo Trading and external Python trading permissions disabled.'),
 'DEMO_ACCOUNT_REQUIRED':('safety','The read-only observer requires a demo terminal.'),
 'SYMBOL_NOT_VISIBLE':('connection','Make the exact XAUUSD symbol visible in Market Watch manually.'),
 'SHADOW_LOG_FAILED':('integrity','Private research logging failed; the assessment is withheld.'),
 'SNAPSHOT_SERIALIZATION_FAILED':('integrity','The snapshot could not be represented safely; the assessment is withheld.'),
}


def label(value):return LABELS.get(value,str(value or 'unknown').replace('_',' ').lower())


def readable(snapshot):
    """Never modifies the v1 snapshot, facts, thresholds or evidence identities."""
    r=deepcopy(snapshot);obs=r.get('observations',{});frames=obs.get('frames',{});ctx=obs.get('context',{})
    registry=obs.get('source_registry',{});evidence=obs.get('evidence',[]);scenario=r.get('scenario',{})
    known=set(registry)|{e['id'] for e in evidence}
    def refs(values):return sorted({v for v in values if v in known})
    structures={}
    for tf in ('M1','M5'):
        f=frames.get(tf,{});state=f.get('structure',{}).get('classification','UNKNOWN')
        ev=[e for e in evidence if e['timeframe']==tf and e['category']=='STRUCTURE']
        ids=refs([e['id'] for e in ev])
        pivots=[];mapping={}
        for p in f.get('confirmed_pivots',[]):
            found=[key for key,s in registry.items() if s.get('kind')=='CONFIRMED_PIVOT' and s.get('timeframe')==tf
                and s.get('observed_at')==p['occurred_at'] and s.get('pivot_kind')==p['kind'] and s.get('price')==p['price']]
            mapping[p['id']]=found
            pivots.append(dict(relation=p['relation'],description=RELATIONS.get(p['relation'],'Confirmed swing'),
                price=p['price'],occurred_at=p['occurred_at'],confirmed_at=p['confirmed_at'],evidence_ids=refs(found)))
        for c in f.get('evidence',[]):
            mapping[c['id']]=[key for key,s in registry.items() if s.get('kind')=='CANDLE' and s.get('timeframe')==tf and s.get('observed_at')==c['opened_at']]
        events=[dict(event_type=e['event_type'],level=e['level'],confirmed_at=e['confirmed_at'],
            description=event_label(e['event_type']),evidence_ids=refs([x for ref in e['evidence'] for x in mapping.get(ref,[])])) for e in f.get('events',[])[-6:]]
        text=f"{tf} confirmed-swing structure is {label(state)}."
        if state=='UNKNOWN':text=f"{tf} structure is uncertain because confirmed swings are insufficient."
        structures[tf]=dict(state=state,label=label(state),summary=text,evidence_ids=ids,
            recent_swings=pivots[-6:],recent_events=events,closed_at=f.get('data_as_of'),
            momentum=ctx.get(tf,{}).get('momentum',{}),volatility=ctx.get(tf,{}).get('volatility',{}))
    levels=[]
    for tf,f in ctx.items():
        for name in ('support_resistance','supply_demand','liquidity_pools'):
            for z in f.get(name,[]):
                levels.append(dict(id=z['id'],kind=z['kind'],timeframe=tf,lower=z.get('lower',z.get('level')),
                    upper=z.get('upper',z.get('level')),status=z.get('status','OBSERVED_PROXY'),
                    evidence_ids=refs([z['id'],*z.get('evidence',[])]),origin_at=z.get('origin_at',z.get('confirmed_at'))))
    levels.sort(key=lambda z:(z['timeframe'],z['kind'],z['lower'],z['id']))
    def explain_evidence(e):
        detail=e.get('details',{});message=CATEGORY.get(e['category'],e['category'].lower())
        qualifier=detail.get('event_type') or detail.get('classification') or detail.get('name') or detail.get('regime') or detail.get('kind')
        return dict(id=e['id'],timeframe=e['timeframe'],category=e['category'],direction=e['direction'],
            text=f"{e['timeframe']} {message}"+(f": {label(qualifier)}." if qualifier else '.'),evidence_ids=refs([e['id'],*e.get('references',[])]))
    panels={}
    for direction,prefix in (('BULLISH','BULLISH_'),('BEARISH','BEARISH_')):
        hs=[h for h in scenario.get('ranked_hypotheses',[]) if h['hypothesis_type'].startswith(prefix)]
        selected=scenario.get('status')=='ASSESSED' and str(scenario.get('selected_hypothesis','')).startswith(prefix)
        status='ASSESSED_SELECTED' if selected else 'EVALUATED_NOT_SELECTED' if scenario.get('status')=='ASSESSED' and hs else 'ABSTAINED' if scenario.get('status')=='ABSTAINED' and hs else 'NOT_ASSESSED'
        support=[explain_evidence(e) for e in evidence if e['direction']==direction]
        oppose=[explain_evidence(e) for e in evidence if e['direction'] in ('BULLISH','BEARISH','RANGING') and e['direction']!=direction]
        panels[direction]=dict(formal_status=status,selected=selected,
            summary=f"The existing engine has assessed a {direction.lower()} research hypothesis." if selected else
                f'The existing engine has not selected the {direction.lower()} direction.' if hs else f'Descriptive {direction.lower()} evidence only. No formal {direction.lower()} hypothesis is available.',
            supporting=support,contradictory=oppose,
            strengthening_conditions=sorted({a for h in hs for a in h['assumptions']}),
            invalidation_conditions=sorted({a for h in hs for a in h['invalidation_conditions']}),
            hypothesis_types=[h['hypothesis_type'] for h in hs])
    reason_codes=sorted(set(r.get('reason_codes',[])+scenario.get('abstention_reasons',[])))
    blockers=[]
    for code in reason_codes:
        category,text=REASONS.get(code,('session','A current session or assurance check is unresolved.') if any(x in code for x in ('SESSION','ASSURANCE','CALENDAR','HOLIDAY','FINALITY','MAINTENANCE')) else
            ('structure','The existing engine has insufficient structural evidence.') if 'STRUCTUR' in code or 'WARMUP' in code else
            ('integrity','A data-quality or eligibility check remains unresolved.'))
        if code=='BLOCKED_DATA_QUALITY' and len(reason_codes)>1:continue
        blockers.append(dict(category=category,code=code,text=text))
    if r.get('analysis_scope')=='DESCRIPTIVE_UNVERIFIED_SESSION' and not any(b['category']=='session' for b in blockers):
        blockers.append(dict(category='session',code='SESSION_ELIGIBILITY_UNVERIFIED',text='Descriptive observations have not passed the formal session eligibility gate.'))
    if r.get('research_assessment')=='DATA_UNAVAILABLE' and not blockers:
        blockers.append(dict(category='connection',code='DATA_UNAVAILABLE',text='No usable current market data is available. Previous observations are withheld.'))
    alignment=obs.get('alignment',{}).get('classification','INSUFFICIENT_EVIDENCE')
    for tf,structure in structures.items():
        if tf in frames and structure['state']=='UNKNOWN':
            blockers.append(dict(category='structure',code=tf+'_CONFIRMED_SWINGS_INSUFFICIENT',text=f"{tf} has insufficient confirmed swings for a structural assessment."))
    mixed=alignment in ('STRUCTURAL_CONFLICT','COUNTERTREND_TRANSITION') or (alignment=='RANGING_OR_MIXED' and not all(s['state']=='RANGING' for s in structures.values()))
    if mixed and not any(b['category']=='mixed_timeframes' for b in blockers):
        blockers.append(dict(category='mixed_timeframes',code='DESCRIPTIVE_ALIGNMENT_MIXED',text=f"M1 is {structures['M1']['label']} while M5 is {structures['M5']['label']}; the descriptive frames are {label(alignment)}."))
    regime=scenario.get('market_regime') or 'UNKNOWN'
    if regime in ('UNKNOWN','BLOCKED_DATA_QUALITY') or scenario.get('status')=='BLOCKED':regime='UNKNOWN'
    overview=dict(symbol='XAUUSD',quote=r.get('quote'),feed_status=r.get('feed_status','DATA_UNAVAILABLE'),
        acquired_at_utc=r.get('acquired_at_utc'),m1=structures['M1']['label'],m5=structures['M5']['label'],
        alignment=alignment,alignment_label=label(alignment),market_regime=regime,
        session_eligible=r.get('analysis_scope')=='SESSION_GATED_CONTEXT',research_assessment=r.get('research_assessment','DATA_UNAVAILABLE'),
        operational_signal='WAIT',execution_allowed=False)
    claims=[]
    def claim(name,text,alternative,ids=()):
        claims.append(dict(id='claim:'+digest([name,text,refs(ids)]),section=name,
            wordings=dict(plain=text,alternative=alternative),evidence_ids=refs(ids)))
    for tf,s in structures.items():claim(tf.lower(),s['summary'],f"The {tf} confirmed-swing view is {s['label']}.",s['evidence_ids'])
    alignment_ids=[e['id'] for e in evidence if e['category']=='STRUCTURE']
    claim('alignment',f"The M1/M5 alignment is {label(alignment)}.",f"The descriptive timeframes are {label(alignment)}.",alignment_ids)
    for direction,panel in panels.items():
        claim(direction.lower(),panel['summary'],panel['summary'],[e['id'] for e in panel['supporting']+panel['contradictory']])
    wait_text=' '.join(dict.fromkeys(b['text'] for b in blockers)) or 'The existing research assessment is separate from execution; this observer cannot place orders.'
    claim('wait',wait_text,wait_text)
    claim('safety','Operational signal remains WAIT and execution is disabled.','No research hypothesis can submit an order; operational signal stays WAIT.')
    bundle=dict(commentary_version=2,claims=claims,closed_evidence_sha256=digest(dict(
        cutoffs=r.get('cutoffs',{}),observations=obs,scenario_sha256=scenario.get('sha256'),reasons=reason_codes,
        feed_status=r.get('feed_status'),research_assessment=r.get('research_assessment'))))
    bundle['bundle_id']=digest(bundle)
    return dict(view_version=2,source_snapshot_id=r.get('snapshot_id'),overview=overview,structures=structures,levels=levels,
        scenarios=panels,wait=dict(summary=wait_text,blockers=blockers),claims=bundle,
        limitations=list(dict.fromkeys(r.get('limitations',[])+scenario.get('limitations',[]))))
