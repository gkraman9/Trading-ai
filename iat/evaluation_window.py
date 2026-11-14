"""Declared evaluation coverage, separate from warm-up and internal aggregation."""
from datetime import timedelta
from iat.replay_dataset import keys,require,utc
from iat.intelligence.models import iso

REVIEW_ITEMS=('usage','instrument','timestamp','price_basis','calendar','finality')
MIN_EVALUATION_M5=12  # One hour is a scoped consistency sample, never market-accuracy proof.


def parse_declarations(manifest,start,end):
    keys(manifest['evaluation'],'start end')
    evaluation={k:iso(utc(manifest['evaluation'][k])) for k in ('start','end')}
    a,b=(utc(evaluation[k]) for k in ('start','end'))
    require(start<=a<b==end,'EVALUATION_RANGE_INVALID')
    require(a.timestamp()%300==b.timestamp()%300==0,'EVALUATION_BOUNDARY_MISALIGNED')
    keys(manifest['warmup'],'M1 M5')
    warmup={}
    for tf in ('M1','M5'):
        keys(manifest['warmup'][tf],'start end')
        x,y=(utc(manifest['warmup'][tf][k]) for k in ('start','end'))
        require(start<=x<=y==a,'WARMUP_RANGE_INVALID')
        warmup[tf]={'start':iso(x),'end':iso(y)}
    lineage=manifest['lineage']
    keys(lineage,'feed_id price_basis timestamp_convention m5_origin raw_sha256')
    import re
    require(isinstance(lineage['feed_id'],str) and re.fullmatch(r'[A-Za-z0-9._/-]{1,100}',lineage['feed_id']))
    require(lineage['price_basis'] in ('BID','ASK','MID','UNKNOWN'))
    require(lineage['timestamp_convention'] in ('INTERVAL_OPEN_UTC','PENDING'))
    require(lineage['m5_origin'] in ('NATIVE_SAME_FEED','AGGREGATED_FROM_M1','UNKNOWN'))
    require(isinstance(lineage['raw_sha256'],str) and re.fullmatch('[a-f0-9]{64}',lineage['raw_sha256']))
    review=manifest['evidence_review'];keys(review,' '.join(REVIEW_ITEMS))
    from urllib.parse import urlsplit
    for item in review.values():
        keys(item,'status reference reason_code')
        require(item['status'] in ('VERIFIED','PENDING'))
        require(isinstance(item['reason_code'],str) and re.fullmatch('[A-Z0-9_]{1,100}',item['reason_code']))
        if item['reference'] is not None:
            require(isinstance(item['reference'],str))
            url=urlsplit(item['reference'])
            require(url.scheme in ('https','synthetic') and not url.username and not url.password and not url.query and not url.fragment,'SOURCE_REFERENCE_UNSAFE')
        require(item['status']!='VERIFIED' or item['reference'] is not None,'EVIDENCE_REFERENCE_REQUIRED')
    return {'evaluation':evaluation,'warmup':warmup,'lineage':lineage,'evidence_review':review}


def coverage(dataset,tolerance):
    """Compare only evaluation bars; separately count legitimate preceding M5 history."""
    meta=dataset.metadata
    evaluation=meta.get('evaluation',meta['utc_range'])
    start,end=(utc(evaluation[k]) for k in ('start','end'))
    one={utc(r['timestamp']):r for r in dataset.rows['M1']}
    five={utc(r['timestamp']):r for r in dataset.rows['M5']}
    # Without verified calendar coverage this denominator is explicitly only a UTC grid.
    expected=[];basis='UTC_GRID_SESSION_COVERAGE_UNVERIFIED'
    calendar=dataset.calendar
    trusted=False
    if calendar is not None and getattr(calendar,'version',1)==2:
        try:
            calendar.validate_request('XAUUSD',end,timedelta(minutes=5))
            trusted=calendar.coverage_start<=start and end<calendar.coverage_end
        except ValueError:pass
    if trusted:
        expected=[t for t in calendar.expected_opens(start,end,timedelta(minutes=5)) if t+timedelta(minutes=5)<=end]
        basis='VERIFIED_CALENDAR_FULL_M5_INTERVALS'
    else:
        at=start
        if at.timestamp()%300:at+=timedelta(seconds=300-at.timestamp()%300)
        while at+timedelta(minutes=5)<=end:
            expected.append(at);at+=timedelta(minutes=5)
    eval_keys=[t for t in five if start<=t and t+timedelta(minutes=5)<=end]
    comparable=uncovered=mismatches=0
    for opened in eval_keys:
        times=[opened+timedelta(minutes=i) for i in range(5)]
        if not all(t in one for t in times):uncovered+=1;continue
        comparable+=1;rs=[one[t] for t in times];bar=five[opened]
        derived={'open':rs[0]['open'],'high':max(r['high'] for r in rs),'low':min(r['low'] for r in rs),'close':rs[-1]['close']}
        if any(abs(derived[k]-bar[k])>tolerance for k in derived):mismatches+=1
    missing=len(set(expected)-set(eval_keys))
    unexpected=len(set(eval_keys)-set(expected))
    warmup_keys=[t for t in five if t+timedelta(minutes=5)<=start]
    warmup_uncovered=sum(not all(t+timedelta(minutes=i) in one for i in range(5)) for t in warmup_keys)
    percentage=lambda n:100*n/len(expected) if expected else None
    complete=bool(expected) and not missing and not unexpected and not uncovered and not mismatches and comparable==len(expected)
    sufficient=complete and comparable>=MIN_EVALUATION_M5
    origin=meta.get('lineage',{}).get('m5_origin','UNKNOWN')
    review=meta.get('evidence_review',{})
    reviewed=bool(review) and all(review[k]['status']=='VERIFIED' for k in REVIEW_ITEMS)
    native_claim=(sufficient and trusted and reviewed and origin=='NATIVE_SAME_FEED'
        and meta['dataset_kind']=='INDEPENDENT_HISTORICAL' and meta['source']['independent_review']=='ATTESTED'
        and dataset.finality_attested is True and meta['lineage']['price_basis']!='UNKNOWN'
        and meta['lineage']['timestamp_convention']=='INTERVAL_OPEN_UTC')
    return {'start_utc':iso(start),'end_utc':iso(end),'denominator_basis':basis,
        'expected_m5_bars':len(expected),'provided_m5_bars':len(eval_keys),'comparable_m5_bars':comparable,
        'uncovered_m5_bars':uncovered,'missing_m5_bars':missing,'unexpected_m5_bars':unexpected,
        'mismatch_count':mismatches,'provided_coverage_percent':percentage(len(set(expected)&set(eval_keys))),
        'comparable_coverage_percent':percentage(sum(t in expected and all(t+timedelta(minutes=i) in one for i in range(5)) for t in eval_keys)),
        'matching_coverage_percent':percentage(max(0,comparable-mismatches)) if not unexpected else None,
        'minimum_comparable_m5_bars':MIN_EVALUATION_M5,'coverage_sufficient':sufficient,
        'warmup_m5_bars':len(warmup_keys),'warmup_uncovered_m5_bars':warmup_uncovered,
        'm5_origin':origin,'consistency_evidence':'INTERNAL_AGGREGATION_ONLY' if origin=='AGGREGATED_FROM_M1' else 'SAME_FEED_NATIVE_COMPARISON' if origin=='NATIVE_SAME_FEED' else 'LINEAGE_UNVERIFIED',
        'cross_frame_claim':'SCOPED_SAME_FEED_CONSISTENCY' if native_claim else 'NOT_ESTABLISHED'}
