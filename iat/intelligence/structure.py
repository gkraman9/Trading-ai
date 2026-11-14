"""Structure requires two confirmed highs AND two confirmed lows."""
from iat.intelligence.models import Structure


def classify(pivots, available_at):
    highs = [p for p in pivots if p.kind == 'HIGH' and p.status == 'CONFIRMED'][-2:]
    lows = [p for p in pivots if p.kind == 'LOW' and p.status == 'CONFIRMED'][-2:]
    evidence = tuple(p.id for p in sorted(highs+lows, key=lambda p: (p.index, p.kind)))
    if len(highs) < 2 or len(lows) < 2:
        return Structure('UNKNOWN', available_at, evidence, ('STRUCTURE_INSUFFICIENT_PIVOTS',), (), True)
    pair = (highs[-1].relation, lows[-1].relation)
    state = {('HH','HL'): 'BULLISH', ('LH','LL'): 'BEARISH', ('EH','EL'): 'RANGING'}.get(pair, 'TRANSITIONAL')
    contradictions = tuple(pair) if state == 'TRANSITIONAL' else ()
    return Structure(state, available_at, evidence, ('STRUCTURE_'+state,), contradictions, False)
