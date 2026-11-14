"""Timestamp/content identity; Phase 7 window-relative IDs are NEVER durable keys."""
from dataclasses import asdict
from hashlib import sha256
import json
from iat.intelligence.models import iso


def identity(symbol, timeframe, kind, *parts):
    payload=json.dumps([symbol,timeframe,kind,*parts],sort_keys=True,separators=(',',':'),allow_nan=False)
    return f'{timeframe}:{kind}:'+sha256(payload.encode()).hexdigest()


def candle_id(symbol,timeframe,c):
    return identity(symbol,timeframe,'CANDLE',iso(c.timestamp),c.open,c.high,c.low,c.close)


def pivot_id(symbol,timeframe,p):
    return identity(symbol,timeframe,'PIVOT',p.kind,p.occurred_at,p.confirmed_at,p.price)


def clusters(pivots, tolerance):
    """Chronological, same-kind clustering against a fixed first-pivot anchor."""
    groups=[]
    for p in pivots:
        if p.status!='CONFIRMED':continue
        group=next((g for g in groups if g[0].kind==p.kind and abs(g[0].price-p.price)<=tolerance),None)
        if group is None:groups.append([p])
        else:group.append(p)
    return groups


class ReplayLedger:
    """Unique canonical observations and distinct snapshot revisions; no accumulated score."""
    def __init__(self):
        self.seen=set()
        self.latest={}
        self.previous_at=None

    def record(self,report):
        if self.previous_at is not None and report.analysis_at<=self.previous_at:
            raise ValueError('Context replay must be strictly chronological')
        self.previous_at=report.analysis_at
        new=[]
        revisions=[]
        for item in report.evidence:
            if item.id not in self.seen:
                new.append(item.id)
                self.seen.add(item.id)
        for hypothesis in report.hypotheses:
            key=hypothesis.hypothesis_type
            # A revision includes current support/opposition and zones, but not generation time.
            state=asdict(hypothesis)
            state.pop('generated_at')
            digest=json.dumps(state,sort_keys=True,separators=(',',':'))
            if self.latest.get(key)!=digest:revisions.append(key)
            self.latest[key]=digest
        active={h.hypothesis_type for h in report.hypotheses}
        withdrawn=sorted(set(self.latest)-active)
        for key in withdrawn:del self.latest[key]
        return {'report':report.to_dict(),'new_evidence':sorted(new),
                'unique_evidence_count':len(self.seen),'hypothesis_revisions':sorted(revisions),
                'withdrawn_hypotheses':withdrawn}
