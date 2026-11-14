"""Leftmost plateau policy: strict left dominance; tolerant right ties allowed."""
from iat.intelligence.candles import closed_at
from iat.intelligence.models import Pivot, iso


def detect(candles, timeframe, config, refs):
    confirmed, candidates = [], []
    last = {}
    for index in range(config.left_strength, len(candles)):
        for kind, attr in (('HIGH', 'high'), ('LOW', 'low')):
            sign = 1 if kind == 'HIGH' else -1
            price = getattr(candles[index], attr)
            left = candles[index-config.left_strength:index]
            right = candles[index+1:index+config.right_strength+1]
            if not all(sign*(price-getattr(c, attr)) > config.equal_tolerance for c in left):
                continue
            if any(sign*(getattr(c, attr)-price) > config.equal_tolerance for c in right):
                continue
            complete = len(right) == config.right_strength
            confirmation = index + config.right_strength if complete else None
            relation = 'UNCLASSIFIED'
            if complete and kind in last:
                difference = price-last[kind]
                if abs(difference) <= config.equal_tolerance:
                    relation = 'EH' if kind == 'HIGH' else 'EL'
                elif kind == 'HIGH': relation = 'HH' if difference > 0 else 'LH'
                else: relation = 'HL' if difference > 0 else 'LL'
            pivot = Pivot(f'{timeframe}:P:{kind}:{index}', kind, index, iso(candles[index].timestamp),
                          confirmation, iso(closed_at(candles[confirmation], timeframe)) if complete else None,
                          price, relation, tuple(refs[index-config.left_strength:index+len(right)+1]),
                          'CONFIRMED' if complete else 'CANDIDATE')
            (confirmed if complete else candidates).append(pivot)
            if complete: last[kind] = price
    return tuple(confirmed), tuple(candidates)
