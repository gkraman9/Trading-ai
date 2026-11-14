"""Local bid-tick aggregation. Source review never authorizes calendar or finality."""
from datetime import timedelta
from math import isfinite
from iat.intelligence.models import iso


def aggregate_bid_ticks(ticks,start,end):
    """Half-open UTC minutes, input order preserved; no invented no-quote candles."""
    iso(start);iso(end)
    if start>=end or start.timestamp()%300 or end.timestamp()%300:raise ValueError('Aligned finite sample required')
    bars={};previous=None;sealed_by=None
    for tick in ticks:
        at=tick['timestamp'];iso(at)
        if at.utcoffset()!=timedelta(0):raise ValueError('UTC tick input required')
        if previous is not None and at<previous:raise ValueError('Out-of-order ticks')
        previous=at
        if at>=end:
            sealed_by=iso(at);break
        if at<start:continue
        price=tick['bid_price']
        if type(price) not in (float,int) or not isfinite(price) or price<=0:raise ValueError('Invalid bid quote')
        key=at.replace(second=0,microsecond=0)
        if key not in bars:bars[key]={'timestamp':iso(key),'open':float(price),'high':float(price),'low':float(price),'close':float(price)}
        else:
            b=bars[key];b['high']=max(b['high'],price);b['low']=min(b['low'],price);b['close']=float(price)
    if sealed_by is None:raise ValueError('Archive does not extend beyond sample end')
    expected=int((end-start).total_seconds()/60)
    if len(bars)!=expected:raise ValueError('Missing quoted M1 interval; no filling permitted')
    one=list(bars.values());five=[]
    for i in range(0,len(one),5):
        group=one[i:i+5]
        five.append({'timestamp':group[0]['timestamp'],'open':group[0]['open'],'high':max(b['high'] for b in group),
                     'low':min(b['low'] for b in group),'close':group[-1]['close']})
    return one,five,{'boundary_tick_utc':sealed_by,'m1_rows':len(one),'m5_rows':len(five),
                    'finality_claim':'INTERVAL_ELAPSED_ONLY_CAPTURE_COMPLETENESS_PENDING',
                    'aggregation':'M1_FROM_BID_TICKS_M5_FROM_EXACT_FIVE_M1_BARS'}
