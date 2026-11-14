"""Confirmed-pivot zones with fixed formation bounds, causal retests and breaks."""
from iat.intelligence.context_models import Zone
from iat.intelligence.context_evidence import clusters, identity, pivot_id, candle_id
from iat.intelligence.candles import closed_at
from iat.intelligence.models import iso


def lifecycle(candles,tf,lower,upper,formation_index,kind,config):
    tested=[]
    broken=invalid=None
    reversal=False
    previous_touch=False
    support=kind in ('SUPPORT','DEMAND')
    for c in candles[formation_index+1:]:
        at=iso(closed_at(c,tf))
        touch=c.high>=lower and c.low<=upper
        violation=c.close<lower-config.break_tolerance if support else c.close>upper+config.break_tolerance
        if invalid is not None:break
        if kind in ('SUPPLY','DEMAND') and violation:
            invalid=at
        elif kind in ('SUPPORT','RESISTANCE'):
            if broken is None and violation:broken=at
            elif broken is not None:
                reclaimed=c.close>upper+config.break_tolerance if support else c.close<lower-config.break_tolerance
                if reclaimed:invalid=at
                elif touch and violation:reversal=True
        if touch and not previous_touch and invalid is None:tested.append(at)
        previous_touch=touch
    status=('INVALIDATED' if invalid else 'ROLE_REVERSAL_CANDIDATE' if reversal else 'BROKEN' if broken
            else 'TESTED' if tested else 'FRESH')
    return tuple(tested),status,broken,invalid,reversal


def detect(candles,frame,symbol,config):
    zones=[]
    tf=frame.timeframe
    for group in clusters(frame.confirmed_pivots,config.cluster_tolerance):
        if len(group)<config.minimum_touches:continue
        initial=group[:config.minimum_touches]
        lower=max(0.0,min(p.price for p in initial)-config.zone_half_width)
        upper=max(p.price for p in initial)+config.zone_half_width
        formed=max(p.confirmation_index for p in initial)
        at=iso(closed_at(candles[formed],tf))
        ids=tuple(pivot_id(symbol,tf,p) for p in initial)
        kind='RESISTANCE' if initial[0].kind=='HIGH' else 'SUPPORT'
        retests,status,broken,invalid,reversal=lifecycle(candles,tf,lower,upper,formed,kind,config)
        zones.append(Zone(identity(symbol,tf,kind,ids,lower,upper),kind,tf,lower,upper,
             initial[0].occurred_at,at,tuple(pivot_id(symbol,tf,p) for p in group),ids,
             tuple(p.confirmed_at for p in group),retests,status,broken,invalid,reversal,'UNSPECIFIED',
             ('CONFIRMED_PIVOT_CLUSTER','FIXED_FORMATION_BOUNDS','POTENTIAL_ZONE_NOT_GUARANTEED_LEVEL')))
    return tuple(zones)
