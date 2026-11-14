"""Confirmed-level events. First qualifying break consumes a level; no re-arming."""
from math import isfinite
from iat.intelligence.candles import atr, closed_at
from iat.intelligence.models import StructuralEvent, iso
from iat.intelligence.structure import classify


def detect(candles, timeframe, pivots, config, refs):
    events, consumed, wick_seen, failed = [], {}, set(), set()
    for i, candle in enumerate(candles):
        moment = iso(closed_at(candle, timeframe))
        # A structural level must have been available BEFORE the break candle opened.
        known = [p for p in pivots if p.confirmation_index < i]
        prior = classify(known, moment)
        threshold = config.min_break_distance
        if config.atr_multiplier:
            baseline = atr(candles[:i], config.atr_period)
            if baseline is None: continue
            threshold = max(threshold, baseline*config.atr_multiplier)
        if not isfinite(threshold):
            raise ValueError('Unsafe break threshold')

        def emit(kind, p, distance, codes):
            events.append(StructuralEvent(f'{timeframe}:E:{p.id}:{kind}:{i}', kind, p.price, p.id,
                         prior.classification, refs[i], moment, max(0.0, distance), threshold,
                         config.break_policy, (p.id,)+prior.evidence+(refs[i],), tuple(codes)))

        for p in known:
            sign = 1 if p.kind == 'HIGH' else -1
            close_distance = sign*(candle.close-p.price)
            wick_distance = sign*((candle.high if sign == 1 else candle.low)-p.price)
            if p.id in consumed:
                if p.id not in failed and i > consumed[p.id] and close_distance < -config.epsilon:
                    emit('FAILED_STRUCTURAL_BREAK', p, abs(close_distance), ['BREAK_RETURNED_INSIDE', 'NO_AUTOMATIC_REVERSAL'])
                    failed.add(p.id)
                continue
            close_break = close_distance > threshold+config.epsilon
            wick_break = wick_distance > threshold+config.epsilon
            qualifies = close_break if config.break_policy == 'CLOSE' else wick_break
            if qualifies:
                direction = 'BULLISH' if sign == 1 else 'BEARISH'
                if prior.classification not in ('BULLISH', 'BEARISH'):
                    kind, codes = 'AMBIGUOUS_STRUCTURAL_EVENT', ['PRIOR_DIRECTION_UNESTABLISHED']
                else:
                    kind = direction + ('_BOS' if prior.classification == direction else '_CHOCH')
                    codes = ['CONFIRMED_LEVEL_BREAK', 'POSSIBLE_TRANSITION_ONLY' if kind.endswith('CHOCH') else 'DIRECTIONAL_CONTINUATION_OBSERVATION']
                if config.break_policy == 'WICK': codes.append('WICK_POLICY_NOT_CLOSE_CONFIRMATION')
                emit(kind, p, close_distance if config.break_policy == 'CLOSE' else wick_distance, codes)
                consumed[p.id] = i
            elif wick_break and p.id not in wick_seen:
                emit('WICK_PENETRATION', p, wick_distance, ['CLOSE_BREAK_UNCONFIRMED'])
                if close_distance < -config.epsilon:
                    emit('POTENTIAL_LIQUIDITY_SWEEP', p, wick_distance, ['WICK_REJECTED_LEVEL', 'OHLC_PROXY_NOT_ORDER_FLOW', 'NO_AUTOMATIC_REVERSAL'])
                wick_seen.add(p.id)
    return tuple(events)
