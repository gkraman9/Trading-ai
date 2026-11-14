"""Confirmed-level concentration and rejection proxies; no hidden orders observed."""
from iat.intelligence.context_models import LiquidityPool,LiquidityEvent
from iat.intelligence.context_evidence import clusters,identity,pivot_id,candle_id
from iat.intelligence.candles import average,closed_at
from iat.intelligence.models import iso


def detect(candles,frame,symbol,config):
    pools=[]
    events=[]
    tf=frame.timeframe
    # A single confirmed swing is a potential pool; equal clusters add concentration evidence.
    for group in clusters(frame.confirmed_pivots,config.cluster_tolerance):
        for size in (1,config.minimum_touches):
            if len(group)<size:continue
            initial=group[:size]
            formed=max(p.confirmation_index for p in initial)
            level=average([p.price for p in initial])
            refs=tuple(pivot_id(symbol,tf,p) for p in initial)
            kind=('EQUAL_' if size>1 else 'SWING_')+('HIGHS' if initial[0].kind=='HIGH' else 'LOWS')
            pool=LiquidityPool(identity(symbol,tf,kind,refs,level),kind,tf,level,
                   iso(closed_at(candles[formed],tf)),refs,size,
                   ('POTENTIAL_LIQUIDITY_PROXY','REPEATED_RANGE_BOUNDARY' if size>1 else 'CONFIRMED_SWING_LEVEL'))
            pools.append(pool)
            sign=1 if initial[0].kind=='HIGH' else -1
            pending=None
            streak=0
            terminal=False
            for c in candles[formed+1:]:
                cid=candle_id(symbol,tf,c)
                at=iso(closed_at(c,tf))
                distance=sign*(c.close-level)
                penetration=sign*((c.high if sign==1 else c.low)-level)>config.break_tolerance
                def emit(event,origin):
                    events.append(LiquidityEvent(identity(symbol,tf,event,pool.id,origin,at),pool.id,event,
                        tf,origin,at,level,cid,(pool.id,cid),('OHLC_PROXY_NOT_ACTUAL_STOPS','NO_AUTOMATIC_REVERSAL')))
                if terminal:break
                if distance>config.break_tolerance:
                    if pending is None:
                        pending=iso(c.timestamp)
                        emit('LEVEL_PENETRATION',pending)
                    streak+=1
                    if streak>=config.breakout_closes:
                        emit('SUSTAINED_BREAKOUT',pending);terminal=True
                elif pending is not None:
                    emit('AMBIGUOUS_EVENT',pending);terminal=True  # Earlier close-through is not a wick sweep.
                elif penetration:
                    emit('LEVEL_PENETRATION',iso(c.timestamp))
                    emit('CONFIRMED_SWEEP' if distance < -config.break_tolerance else 'AMBIGUOUS_EVENT',iso(c.timestamp))
                    terminal=True
    return tuple(pools),tuple(events)
