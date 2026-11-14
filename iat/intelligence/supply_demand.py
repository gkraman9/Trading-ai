"""Base/departure candidates are OHLC geometry, never institutional order-flow claims."""
from math import isfinite
from iat.intelligence.candles import average, atr, closed_at
from iat.intelligence.models import iso
from iat.intelligence.context_models import Zone
from iat.intelligence.context_evidence import identity, candle_id
from iat.intelligence.structure import classify
from iat.intelligence.support_resistance import lifecycle


def detect(candles,frame,symbol,config):
    tf=frame.timeframe
    zones=[]
    for i in range(config.base_bars+config.range_period,len(candles)):
        base=candles[i-config.base_bars:i]
        preceding=candles[i-config.base_bars-config.range_period:i-config.base_bars]
        baseline=average([c.high-c.low for c in preceding])
        if baseline is None or baseline<=0:continue
        lower=min(c.low for c in base)
        upper=max(c.high for c in base)
        if not isfinite(baseline*config.base_width_ratio):raise ValueError('Unsafe base width')
        if (average([c.high-c.low for c in base])>baseline*config.base_range_ratio
                or upper-lower>baseline*config.base_width_ratio):continue
        c=candles[i]
        span=c.high-c.low
        if span<=0 or abs(c.close-c.open)<span*config.departure_body_ratio:continue
        threshold=baseline*config.departure_range_multiple
        if config.departure_atr_multiple:
            value=atr(candles[:i],config.atr_period)
            if value is None:continue
            threshold=max(threshold,value*config.departure_atr_multiple)
        if not isfinite(threshold) or not isfinite(upper+threshold):raise ValueError('Unsafe departure threshold')
        if c.close>upper+threshold and c.close>c.open:kind='DEMAND'
        elif c.close<lower-threshold and c.close<c.open:kind='SUPPLY'
        else:continue
        at=iso(closed_at(c,tf))
        refs=tuple(candle_id(symbol,tf,b) for b in (*base,c))
        retests,status,broken,invalid,reversal=lifecycle(candles,tf,lower,upper,i,kind,config)
        previous=classify([p for p in frame.confirmed_pivots if p.confirmation_index<i],at)
        zones.append(Zone(identity(symbol,tf,kind,refs,lower,upper),kind,tf,lower,upper,
                     iso(base[0].timestamp),at,(),refs,(),retests,status,broken,invalid,reversal,
                     previous.classification,('BASE_DEPARTURE_CANDIDATE','AVAILABLE_AFTER_DEPARTURE_CLOSE',
                     'OHLC_GEOMETRY_NOT_INSTITUTIONAL_FLOW')))
    return tuple(zones)
