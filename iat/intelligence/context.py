"""Quality-gated market context; pure analysis has no broker/clock/order dependencies."""
from dataclasses import asdict
from datetime import datetime,timedelta
from iat.analysis import validate_candles
from iat.intelligence.engine import analyze_intelligence,_finite_tree,IntelligenceStream
from iat.intelligence.candles import closed_at,prefix
from iat.intelligence.models import IntelligenceConfig,iso
from iat.intelligence.context_models import ContextConfig,ContextReport,Evidence
from iat.intelligence.context_evidence import identity,candle_id,pivot_id,ReplayLedger
from iat.intelligence import support_resistance,supply_demand,liquidity,momentum,volatility,confluence,hypotheses


DIRECTIONS={'BULLISH':'BULLISH','BEARISH':'BEARISH','RANGING':'RANGING'}
BULL_PATTERNS={'BULLISH_ENGULFING','HAMMER','INVERTED_HAMMER','MORNING_STAR','BULLISH_MOMENTUM_CANDLE'}
BEAR_PATTERNS={'BEARISH_ENGULFING','SHOOTING_STAR','HANGING_MAN','EVENING_STAR','BEARISH_MOMENTUM_CANDLE'}


def aggregate(intelligence):
    frames=intelligence.frames
    a=frames.get('M1')
    b=frames.get('M5')
    limitations=[]
    if not intelligence.data_quality['valid']:limitations.append('BLOCKED_DATA_QUALITY')
    if a is None or b is None or any(f.structure.insufficient_evidence for f in frames.values()):
        limitations.append('INSUFFICIENT_STRUCTURAL_CONTEXT')
    state=intelligence.alignment.classification
    if 'BLOCKED_DATA_QUALITY' in limitations:state='BLOCKED_DATA_QUALITY'
    elif limitations:state='INSUFFICIENT_DATA'
    elif state=='RANGING_OR_MIXED':state='SIDEWAYS_OR_RANGING' if all(f.structure.classification=='RANGING' for f in frames.values()) else 'CONFLICTING_EVIDENCE'
    return {'classification':state,'phase7_alignment':intelligence.alignment.classification,
            'm1_structure':a.structure.classification if a else 'UNKNOWN',
            'm5_structure':b.structure.classification if b else 'UNKNOWN',
            'm1_as_of':a.data_as_of if a else None,'m5_as_of':b.data_as_of if b else None,
            'limitations':limitations}


def derive(intelligence,candles_by_tf,config):
    evidence=[]
    sources={}
    results={}
    facts={}
    all_zones=[]
    for tf,frame in intelligence.frames.items():
        candles=candles_by_tf[tf]
        refs={r.id:candle_id(intelligence.symbol,tf,candles[r.index]) for r in frame.evidence}
        for r in frame.evidence:
            c=candles[r.index]
            sources[refs[r.id]]={'kind':'CANDLE','timeframe':tf,'observed_at':r.opened_at,
                'available_at':r.available_at,'ohlc':{'open':c.open,'high':c.high,'low':c.low,'close':c.close}}
        for p in frame.confirmed_pivots:
            pid=pivot_id(intelligence.symbol,tf,p)
            refs[p.id]=pid
            sources[pid]={'kind':'CONFIRMED_PIVOT','timeframe':tf,'observed_at':p.occurred_at,
                'available_at':p.confirmed_at,'price':p.price,'pivot_kind':p.kind,
                'references':[refs[c] for c in p.evidence]}
        def add(category,direction,observed,available,references,codes,details):
            eid=identity(intelligence.symbol,tf,category,observed,available,sorted(references),direction,sorted(codes),details,config.digest,
                         intelligence.configuration_sha256)
            evidence.append(Evidence(eid,category,tf,direction,observed,available,tuple(sorted(set(references))),tuple(codes),details))
        structure_refs=tuple(refs[p] for p in frame.structure.evidence)
        structure_at=max((sources[r]['available_at'] for r in structure_refs),default=frame.data_as_of)
        structure_origin=min((sources[r]['observed_at'] for r in structure_refs),default=frame.data_as_of)
        add('STRUCTURE',DIRECTIONS.get(frame.structure.classification,'NEUTRAL'),
            structure_origin,structure_at,structure_refs,frame.structure.reason_codes,
            {'classification':frame.structure.classification})
        # Do not rely on Phase 7's alignment label to discover opposing current CHoCH.
        for event in frame.events:
            if not event.event_type.endswith('_CHOCH') or event.confirmed_at!=frame.data_as_of:continue
            direction='BULLISH' if event.event_type.startswith('BULLISH') else 'BEARISH'
            add('TRANSITION',direction,sources[refs[event.break_candle]]['observed_at'],event.confirmed_at,
                tuple(refs[r] for r in event.evidence),event.reason_codes,
                {'event_type':event.event_type,'level':event.level,'fresh':True,'prior_structure':event.prior_structure,
                 'phase7_alignment':intelligence.alignment.classification})
        sr=support_resistance.detect(candles,frame,intelligence.symbol,config)
        sd=supply_demand.detect(candles,frame,intelligence.symbol,config)
        pools,events=liquidity.detect(candles,frame,intelligence.symbol,config)
        mom=momentum.measure(candles,config)
        vol=volatility.measure(candles,config)
        results[tf]={'support_resistance':sr,'supply_demand':sd,'liquidity_pools':pools,'liquidity_events':events,
                     'structure':dict(asdict(frame.structure),evidence=list(structure_refs)),
                     'patterns':[dict(asdict(p),evidence=[refs[r] for r in p.evidence]) for p in frame.patterns],
                     'momentum':mom,'volatility':vol}
        facts[tf]={'data_as_of':frame.data_as_of,'candle_count':len(candles),'measurements':frame.measurements,
                   'momentum':mom,'volatility':vol}
        all_zones.extend((*sr,*sd))
        for zone in (*sr,*sd):
            sources[zone.id]={'kind':'ZONE','timeframe':tf,'observed_at':zone.origin_at,'available_at':zone.confirmed_at,
                              'references':list(zone.evidence),'lower':zone.lower,'upper':zone.upper}
            if zone.status not in ('FRESH','TESTED','ROLE_REVERSAL_CANDIDATE'):continue
            if not zone.lower-config.cluster_tolerance<=candles[-1].close<=zone.upper+config.cluster_tolerance:continue
            direction='BULLISH' if zone.kind in ('SUPPORT','DEMAND') else 'BEARISH'
            if zone.potential_role_reversal:direction='BEARISH' if direction=='BULLISH' else 'BULLISH'
            add('SUPPORT_RESISTANCE' if zone.kind in ('SUPPORT','RESISTANCE') else 'SUPPLY_DEMAND',direction,
                zone.origin_at,frame.data_as_of,(zone.id,candle_id(intelligence.symbol,tf,candles[-1])),('CURRENT_PRICE_NEAR_CANDIDATE_ZONE','NO_GUARANTEED_REVERSAL'),
                {'kind':zone.kind,'status':zone.status,'lower':zone.lower,'upper':zone.upper})
        poolmap={p.id:p for p in pools}
        for pool in pools:
            sources[pool.id]={'kind':'LIQUIDITY_POOL','timeframe':tf,'observed_at':pool.confirmed_at,
                             'available_at':pool.confirmed_at,'references':list(pool.evidence),'level':pool.level}
        for event in events:
            sources[event.id]={'kind':'LIQUIDITY_EVENT','timeframe':tf,'observed_at':event.occurred_at,
                              'available_at':event.available_at,'references':list(event.evidence)}
            if event.available_at!=frame.data_as_of:continue
            pool=poolmap[event.pool_id]
            direction=('BULLISH' if pool.kind.endswith('HIGHS') else 'BEARISH') if event.event_type=='SUSTAINED_BREAKOUT' else 'NEUTRAL'
            add('LIQUIDITY',direction,event.occurred_at,event.available_at,(event.id,),event.reason_codes,
                {'event_type':event.event_type,'level':event.level,'pool_kind':pool.kind})
        momrefs=tuple(candle_id(intelligence.symbol,tf,c) for c in candles[-config.roc_period-2:])
        direction='BULLISH' if mom['regime']=='POSITIVE_MOMENTUM' else 'BEARISH' if mom['regime']=='NEGATIVE_MOMENTUM' else 'NEUTRAL'
        add('MOMENTUM',direction,iso(candles[max(0,len(candles)-config.roc_period-2)].timestamp),frame.data_as_of,
            momrefs,mom['reason_codes'],mom)
        volrefs=tuple(candle_id(intelligence.symbol,tf,c) for c in candles[-max(2*config.range_period,config.atr_period+1):])
        add('VOLATILITY','NEUTRAL',sources[volrefs[0]]['observed_at'],frame.data_as_of,volrefs,vol['reason_codes'],vol)
        for pattern in frame.patterns:
            direction='BULLISH' if pattern.name in BULL_PATTERNS else 'BEARISH' if pattern.name in BEAR_PATTERNS else 'NEUTRAL'
            pr=tuple(refs[r] for r in pattern.evidence)
            add('CANDLE',direction,min(sources[r]['observed_at'] for r in pr),pattern.detected_at,
                pr,pattern.reason_codes,{'name':pattern.name,'interpretation':pattern.interpretation})
    unique={}
    for e in evidence:
        if e.id in unique and unique[e.id]!=e:raise ValueError('Conflicting evidence identity')
        unique[e.id]=e
    return tuple(sorted(unique.values(),key=lambda e:e.id)),sources,results,facts,tuple(all_zones)


def analyze_context(symbol,m1_rows,m5_rows,as_of,*,config=None,intelligence_config=None,
                    provenance='SYNTHETIC_RESEARCH',calendar=None,observed_finality=None):
    config=ContextConfig() if config is None else config
    if not isinstance(config,ContextConfig):raise ValueError('Typed context configuration required')
    intelligence=analyze_intelligence(symbol,m1_rows,m5_rows,as_of,config=intelligence_config,
                  provenance=provenance,calendar=calendar,observed_finality=observed_finality)
    ctx=aggregate(intelligence)
    facts={};interpretations={};evidence=();scenarios=();abstain=[]
    scored={'score_kind':'HEURISTIC_EVIDENCE_NOT_PROBABILITY','scores':{},'weighted_evidence':[],
            'selected_hypothesis':'NO_CLEAR_DIRECTIONAL_HYPOTHESIS','abstention_reasons':['BLOCKED_DATA_QUALITY']}
    quality=intelligence.data_quality
    if quality['valid']:
        try:
            cs={tf:tuple(validate_candles(rows)) for tf,rows in (('M1',m1_rows),('M5',m5_rows)) if tf in intelligence.frames}
            evidence,sources,frames,facts,zones=derive(intelligence,cs,config)
            interpretations={'frames':frames,'source_registry':sources}
            _finite_tree(asdict(ContextReport(1,'IAT_MARKET_CONTEXT_V1',config.version,config.digest,
                intelligence.configuration_sha256,asdict(config),symbol,iso(as_of),intelligence.provenance,
                quality,facts,interpretations,evidence,ctx,scored,(),(),())))
            for tf,frame in frames.items():
                if frame['momentum']['status']!='AVAILABLE':ctx['limitations'].append(tf+'_MOMENTUM_INSUFFICIENT')
                if frame['volatility']['status']!='AVAILABLE':ctx['limitations'].append(tf+'_VOLATILITY_INSUFFICIENT')
            scored=confluence.evaluate(evidence,config,ctx)
            scenarios=hypotheses.build(evidence,ctx,zones,scored,iso(as_of),config)
        except (ValueError,OverflowError,ZeroDivisionError):
            quality={'valid':False,'status':'BLOCKED','diagnostics':[{'code':'CONTEXT_ARITHMETIC_UNSAFE',
                'severity':'ERROR','message':'Context calculations could not be established safely'}]}
            ctx={'classification':'BLOCKED_DATA_QUALITY','phase7_alignment':intelligence.alignment.classification,
                 'm1_structure':'UNKNOWN','m5_structure':'UNKNOWN','m1_as_of':None,'m5_as_of':None,'limitations':['BLOCKED_DATA_QUALITY']}
            facts={};interpretations={};evidence=();scenarios=()
    if not quality['valid']:
        scored={'score_kind':'HEURISTIC_EVIDENCE_NOT_PROBABILITY','scores':{},'weighted_evidence':[],
                'selected_hypothesis':'NO_CLEAR_DIRECTIONAL_HYPOTHESIS','abstention_reasons':['BLOCKED_DATA_QUALITY']}
    abstain=tuple(scored['abstention_reasons'])
    explanation=(f"Context: {ctx['classification']}; Phase 7 alignment: {ctx['phase7_alignment']}.",
                 f"Selected research scenario: {scored['selected_hypothesis']}; {len(evidence)} current evidence records.",
                 'Abstention reasons: '+(', '.join(abstain) if abstain else 'none under configured research rules')+'.',
                 'Scores are heuristic evidence summaries, not probabilities. Signal WAIT; execution disabled.')
    return ContextReport(1,'IAT_MARKET_CONTEXT_V1',config.version,config.digest,intelligence.configuration_sha256,
        asdict(config),symbol,iso(as_of),intelligence.provenance,quality,facts,interpretations,evidence,ctx,
        scored,scenarios,abstain,explanation)


def context_at(symbol,m1_history,m5_history,as_of,**options):
    selected=[prefix(rows,tf,as_of) if rows is not None else None for tf,rows in (('M1',m1_history),('M5',m5_history))]
    return analyze_context(symbol,*selected,as_of,**options)


def replay_context(symbol,m1_history,m5_history,*,window=None,**options):
    """Chronological evidence log. Rolling windows retain canonical identity, not local indexes."""
    if window is not None and (type(window) is not int or not 3<=window<=5000):raise ValueError('Invalid replay window')
    ledger=ReplayLedger()
    for row in m1_history:
        at=datetime.fromisoformat(str(row['timestamp']).replace('Z','+00:00'))+timedelta(minutes=1)
        selected=[prefix(rows,tf,at) if rows is not None else None for tf,rows in (('M1',m1_history),('M5',m5_history))]
        if window is not None:selected=[rows[-window:] if rows is not None else None for rows in selected]
        yield ledger.record(analyze_context(symbol,*selected,at,**options))


class ContextStream(IntelligenceStream):
    """Reuse Phase 7's append-only/late-data protections; emit Phase 8 observations."""
    def snapshot(self,as_of,*,window=None):
        iso(as_of)
        if self.previous_as_of is not None and as_of<self.previous_as_of:
            raise ValueError('Stream clock moved backwards')
        if window is not None and (type(window) is not int or not 3<=window<=5000):
            raise ValueError('Invalid context window')
        selected=[prefix(self.rows[tf],tf,as_of) for tf in ('M1','M5')]
        if window is not None:selected=[rows[-window:] for rows in selected]
        report=analyze_context(self.symbol,*selected,as_of,**self.options)
        self.previous_as_of=as_of
        return report
