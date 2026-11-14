"""ROC, body momentum and acceleration are descriptive evidence, never entries."""
from iat.intelligence.candles import average


def measure(candles,config):
    n=config.roc_period
    if len(candles)<n+2:
        return {'status':'INSUFFICIENT_EVIDENCE','roc':None,'previous_roc':None,'acceleration':None,
                'body_momentum':None,'regime':'INSUFFICIENT_EVIDENCE','change':'INSUFFICIENT_EVIDENCE',
                'reason_codes':['MOMENTUM_WARMUP']}
    roc=candles[-1].close/candles[-n-1].close-1
    previous=candles[-2].close/candles[-n-2].close-1
    acceleration=roc-previous
    body=average([(c.close-c.open)/(c.high-c.low) if c.high>c.low else 0.0 for c in candles[-n:]])
    regime='POSITIVE_MOMENTUM' if roc>config.momentum_threshold and body>0 else (
        'NEGATIVE_MOMENTUM' if roc < -config.momentum_threshold and body<0 else 'WEAK_OR_MIXED_MOMENTUM')
    magnitude_change=abs(roc)-abs(previous)
    change='ACCELERATING' if magnitude_change>config.acceleration_threshold else (
        'DECELERATING' if magnitude_change < -config.acceleration_threshold else 'STABLE_OR_MIXED')
    return {'status':'AVAILABLE','roc':roc,'previous_roc':previous,'acceleration':acceleration,
            'body_momentum':body,'regime':regime,'change':change,'reason_codes':['ROC_AND_BODY_OBSERVATION']}
