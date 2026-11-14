"""Arithmetic ATR and disjoint range baselines; null rather than divide by zero."""
from iat.intelligence.candles import average,atr


def measure(candles,config):
    n=config.range_period
    current_atr=atr(candles,config.atr_period)
    if len(candles)<2*n or current_atr is None:
        return {'status':'INSUFFICIENT_EVIDENCE','atr':current_atr,'recent_range':None,'preceding_range':None,
                'relative_volatility':None,'regime':'INSUFFICIENT_EVIDENCE','change':'INSUFFICIENT_EVIDENCE',
                'reason_codes':['VOLATILITY_WARMUP']}
    recent=average([c.high-c.low for c in candles[-n:]])
    preceding=average([c.high-c.low for c in candles[-2*n:-n]])
    relative=recent/preceding if preceding>0 else None
    regime='INSUFFICIENT_EVIDENCE' if relative is None else 'HIGH_VOLATILITY' if relative>config.volatility_high else (
           'LOW_VOLATILITY' if relative<config.volatility_low else 'NORMAL_VOLATILITY')
    change='INSUFFICIENT_EVIDENCE' if relative is None else 'VOLATILITY_EXPANSION' if relative>config.volatility_high else (
           'VOLATILITY_CONTRACTION' if relative<config.volatility_low else 'STABLE_VOLATILITY')
    return {'status':'AVAILABLE' if relative is not None else 'INSUFFICIENT_EVIDENCE','atr':current_atr,
            'recent_range':recent,'preceding_range':preceding,'relative_volatility':relative,
            'regime':regime,'change':change,'reason_codes':['DISJOINT_RANGE_BASELINE' if relative is not None else 'ZERO_RANGE_BASELINE']}
