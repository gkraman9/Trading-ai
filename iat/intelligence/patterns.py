"""Causal shape recognition; contextual names require preceding directional context."""
from iat.intelligence.candles import closed_at, measure
from iat.intelligence.models import Pattern, iso


def recognize(candles, timeframe, config, refs):
    current = candles[-1]
    m = measure(current, candles[:-1], config)
    e = config.epsilon
    result = []
    trend = 'UNKNOWN'
    preceding = candles[-config.trend_window-1:-1]
    if len(preceding) == config.trend_window:
        if all(b.close > a.close + e for a, b in zip(preceding, preceding[1:])):
            trend = 'UP'
        elif all(b.close < a.close - e for a, b in zip(preceding, preceding[1:])):
            trend = 'DOWN'
    m['preceding_trend'] = trend

    def add(name, count=1, interpretation='SHAPE_ONLY'):
        result.append(Pattern(name, iso(closed_at(current, timeframe)), tuple(refs[-count:]),
                              interpretation, (name, 'NO_PREDICTIVE_GUARANTEE')))

    if m['zero_range']:
        add('DOJI')
        return m, tuple(result)
    body, span, upper, lower = (m[k] for k in ('body', 'range', 'upper_wick', 'lower_wick'))
    if m['direction'] == 'DOJI':
        add('DOJI')
        if upper <= config.short_wick_range * span + e and lower >= (1-config.doji_ratio-config.short_wick_range)*span-e:
            add('DRAGONFLY_DOJI')
        if lower <= config.short_wick_range * span + e and upper >= (1-config.doji_ratio-config.short_wick_range)*span-e:
            add('GRAVESTONE_DOJI')
    elif body <= config.small_body_ratio * span + e:
        if lower + e >= config.long_wick_body * body and upper <= config.short_wick_range * span + e:
            add('BULLISH_PIN_BAR')
            if trend == 'DOWN': add('HAMMER', config.trend_window+1, 'CONTEXTUAL_CANDIDATE')
            if trend == 'UP': add('HANGING_MAN', config.trend_window+1, 'CONTEXTUAL_CANDIDATE')
        if upper + e >= config.long_wick_body * body and lower <= config.short_wick_range * span + e:
            add('BEARISH_PIN_BAR')
            if trend == 'DOWN': add('INVERTED_HAMMER', config.trend_window+1, 'CONTEXTUAL_CANDIDATE')
            if trend == 'UP': add('SHOOTING_STAR', config.trend_window+1, 'CONTEXTUAL_CANDIDATE')
    if (m['relative_range'] is not None and m['range_context_count'] == config.range_window
            and body + e >= config.momentum_body_ratio * span
            and m['relative_range'] + e >= config.momentum_relative_range):
        if m['direction'] != 'DOJI':
            add(m['direction'] + '_MOMENTUM_CANDLE', config.range_window+1)
    if len(candles) >= 2:
        previous = candles[-2]
        if current.high <= previous.high + e and current.low >= previous.low - e:
            add('INSIDE_BAR', 2)
        if current.high >= previous.high - e and current.low <= previous.low + e and (
                current.high > previous.high + e or current.low < previous.low - e):
            add('OUTSIDE_BAR', 2)
        if previous.open > previous.close + e and current.close > current.open + e and (
                current.open <= previous.close + e and current.close >= previous.open - e and body > abs(previous.close-previous.open)+e):
            add('BULLISH_ENGULFING', 2)
        if previous.close > previous.open + e and current.open > current.close + e and (
                current.open >= previous.close - e and current.close <= previous.open + e and body > abs(previous.close-previous.open)+e):
            add('BEARISH_ENGULFING', 2)
    if len(candles) >= 3:
        a, b, c = candles[-3:]
        abody, bbody = abs(a.close-a.open), abs(b.close-b.open)
        arange = a.high-a.low
        if arange > e and abody + e >= config.momentum_body_ratio*arange and bbody <= config.small_body_ratio*abody+e:
            if a.open > a.close+e and c.close > c.open+e and c.close >= a.close+config.star_recovery*abody-e:
                add('MORNING_STAR', 3, 'THREE_CANDLE_CANDIDATE_NO_GAP_REQUIRED')
            if a.close > a.open+e and c.open > c.close+e and c.close <= a.close-config.star_recovery*abody+e:
                add('EVENING_STAR', 3, 'THREE_CANDLE_CANDIDATE_NO_GAP_REQUIRED')
    return m, tuple(result)
