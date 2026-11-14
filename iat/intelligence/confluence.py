"""Capped, transparent evidence votes. Scores are NOT calibrated probabilities."""
CATEGORY_BUCKETS={'STRUCTURE':'STRUCTURE','TRANSITION':'TRANSITION','SUPPORT_RESISTANCE':'PRICE_ZONE',
                  'SUPPLY_DEMAND':'PRICE_ZONE','LIQUIDITY':'LIQUIDITY','MOMENTUM':'MOMENTUM',
                  'CANDLE':'CANDLE','VOLATILITY':'VOLATILITY'}


def evaluate(evidence,config,context):
    unique={}
    for e in evidence:
        if e.id in unique and unique[e.id]!=e:raise ValueError('Conflicting canonical evidence identity')
        unique[e.id]=e
    weights={'STRUCTURE':config.structure_weight,'TRANSITION':config.structure_weight,
             'PRICE_ZONE':config.zone_weight,'LIQUIDITY':config.liquidity_weight,
             'MOMENTUM':config.momentum_weight,'CANDLE':config.candle_weight,'VOLATILITY':0.0}
    scores={'BULLISH':0.0,'BEARISH':0.0,'RANGING':0.0}
    used=set()
    contributions=[]
    for e in sorted(unique.values(),key=lambda e:e.id):
        bucket=CATEGORY_BUCKETS[e.category]
        key=(e.timeframe,bucket,e.direction)
        weight=0.0
        if e.direction in scores and key not in used:
            weight=weights[bucket]
            used.add(key)
            scores[e.direction]+=weight
        contributions.append({'evidence_id':e.id,'bucket':bucket,'timeframe':e.timeframe,
                              'direction':e.direction,'weight':weight,
                              'reason':'CAPPED_CATEGORY_TIMEFRAME_DIRECTION' if weight==0 else 'HEURISTIC_WEIGHT'})
    ranked=sorted(scores,key=lambda k:(-scores[k],k))
    leader=ranked[0]
    opposition=max(scores[k] for k in scores if k!=leader)
    abstain=list(context['limitations'])
    if context['classification'] in ('STRUCTURAL_CONFLICT','CONFLICTING_EVIDENCE'):
        abstain.append('CONFLICTING_TIMEFRAME_STRUCTURE')
    if scores[leader]<config.minimum_score:abstain.append('INSUFFICIENT_HEURISTIC_SUPPORT')
    if scores[leader]-opposition<config.minimum_margin:abstain.append('HEURISTIC_MARGIN_TOO_SMALL')
    if opposition>=config.contradiction_limit:abstain.append('MATERIAL_OPPOSING_EVIDENCE')
    # Explicitly independent from Phase 7 alignment (which gives matching structure precedence).
    reference=context['m5_structure'] if context['m5_structure'] in ('BULLISH','BEARISH') else leader
    opposing_choch=[e.id for e in unique.values() if e.category=='TRANSITION' and e.timeframe=='M1'
        and e.details.get('fresh') is True and e.direction in ('BULLISH','BEARISH')
        and e.direction!=reference and reference in ('BULLISH','BEARISH')]
    if opposing_choch:abstain.append('FRESH_OPPOSING_M1_CHOCH')
    if any(e.category=='VOLATILITY' and e.details.get('regime')=='HIGH_VOLATILITY' for e in unique.values()):
        abstain.append('HIGH_VOLATILITY_REQUIRES_FURTHER_RESEARCH')
    return {'score_kind':'HEURISTIC_EVIDENCE_NOT_PROBABILITY','scores':scores,'leader':leader,
            'opposition_score':opposition,'margin':scores[leader]-opposition,
            'weighted_evidence':contributions,'fresh_opposing_m1_choch':sorted(opposing_choch),
            'abstention_reasons':sorted(set(abstain)),'selected_hypothesis':'NO_CLEAR_DIRECTIONAL_HYPOTHESIS'}
