"""Competing research scenarios with explicit assumptions and invalidation conditions."""
from iat.intelligence.context_models import Hypothesis


def build(evidence,context,zones,confluence,at,config):
    scenarios=(('BULLISH_CONTINUATION_POSSIBILITY','BULLISH','CONTINUATION'),
               ('BEARISH_CONTINUATION_POSSIBILITY','BEARISH','CONTINUATION'),
               ('BULLISH_STRUCTURAL_TRANSITION','BULLISH','TRANSITION'),
               ('BEARISH_STRUCTURAL_TRANSITION','BEARISH','TRANSITION'),
               ('RANGE_CONTINUATION','RANGING','RANGE'))
    output=[]
    eligible=[]
    for name,direction,kind in scenarios:
        support=tuple(sorted(e.id for e in evidence if e.direction==direction))
        opposition=tuple(sorted(e.id for e in evidence if e.direction in ('BULLISH','BEARISH','RANGING') and e.direction!=direction))
        required=(any(e.category=='TRANSITION' and e.direction==direction and e.details.get('fresh') for e in evidence)
                  if kind=='TRANSITION' else context['m5_structure']==direction if kind=='CONTINUATION'
                  else context['m1_structure']==context['m5_structure']=='RANGING')
        assumptions=['OHLC_EVIDENCE_IS_NOT_A_FORECAST','COVERED_HISTORY_MAY_OMIT_OLDER_CONTEXT',
                     'SCORES_ARE_HEURISTIC_NOT_PROBABILITIES']
        if not required:assumptions.append('REQUIRED_STRUCTURAL_PRECONDITION_UNESTABLISHED')
        invalidations=('Relevant price zone is invalidated by a qualifying close.',
                       'New confirmed structure contradicts this scenario.',
                       'Data/session eligibility expires or fails.')
        limitations=tuple(context['limitations'])
        if not required:limitations+=('STRUCTURAL_PRECONDITION_UNESTABLISHED',)
        if (required and not confluence['abstention_reasons'] and direction==confluence['leader']):eligible.append(name)
        output.append(Hypothesis(name,at,'IAT_MARKET_CONTEXT_V1',config.version,support,opposition,
            tuple(assumptions),invalidations,tuple(z.id for z in zones if z.status!='INVALIDATED'
                and any(z.id in e.references and e.id in support for e in evidence)),
            context,limitations,confluence['scores'][direction]))
    if len(eligible)==1:confluence['selected_hypothesis']=eligible[0]
    else:
        confluence['abstention_reasons']=sorted(set(confluence['abstention_reasons'])|{'NO_UNIQUE_ELIGIBLE_SCENARIO'})
    output.append(Hypothesis('NO_CLEAR_DIRECTIONAL_HYPOTHESIS',at,'IAT_MARKET_CONTEXT_V1',config.version,
        tuple(sorted(e.id for e in evidence if e.direction=='NEUTRAL')),
        tuple(sorted(e.id for e in evidence if e.direction!='NEUTRAL')),
        ('ABSTENTION_IS_AN_ANALYTICAL_OUTCOME',),('Additional independently eligible observations may clarify context.',),
        (),context,tuple(confluence['abstention_reasons']),0.0))
    return tuple(output)
