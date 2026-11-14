"""Append-only original assessments and separately versioned causal outcome reviews."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json
from datetime import timedelta
from iat.replay_dataset import utc
from iat.intelligence.models import iso
from iat.intelligence.adaptive import replay_adaptive,validate_adaptive_report
from iat.intelligence.strategy_replay import digest
from iat.intelligence.journal_policy import ReviewPolicy,CRITERIA


def _ranking(report):
    rows=report['assessment']['scenarios']
    return [sorted(s['scenario'] for s in rows if s['rank']==rank)
            for rank in sorted({s['rank'] for s in rows if s['rank'] is not None})]


def _state(report):
    return {'status':report['status'],'regime':report['regime']['directional'],
            'scenario_ranking':_ranking(report),'leading_scenarios':sorted(report['assessment']['top_scenarios']),
            'volatility':{'overall':report['volatility']['overall'],
                          'frames':{tf:v['regime'] for tf,v in report['volatility']['frames'].items()}},
            'strategy_fit':sorted([{k:c[k] for k in ('strategy_id','direction','rule_status','compatibility','assessment_status','rank')}
                            for c in report['assessment']['candidate_assessments']],key=lambda c:(c['strategy_id'],c['direction']))}


def _revision(previous,current):
    a,b=previous['adaptive_report'],current['adaptive_report'];one,two=_state(a),_state(b)
    changes={k:{'before':one[k],'after':two[k]} for k in one if one[k]!=two[k]}
    if not changes:return None
    before={e['id'] for e in a['interpretations']['evidence']};after={e['id'] for e in b['interpretations']['evidence']}
    links=[]
    old_scenarios={s['scenario']:s for s in a['assessment']['scenarios']}
    new_scenarios={s['scenario']:s for s in b['assessment']['scenarios']}
    for name in ('BULLISH','BEARISH','NEUTRAL'):
        old,new=old_scenarios[name],new_scenarios[name]
        links.append({'scenario':new['scenario'],'score_before':old['heuristic_score'],'score_after':new['heuristic_score'],
                      'support_added':sorted(set(new['supporting_evidence'])-set(old['supporting_evidence'])),
                      'support_withdrawn':sorted(set(old['supporting_evidence'])-set(new['supporting_evidence'])),
                      'opposition_added':sorted(set(new['opposing_evidence'])-set(old['opposing_evidence'])),
                      'opposition_withdrawn':sorted(set(old['opposing_evidence'])-set(new['opposing_evidence']))})
    codes=sorted({k.upper()+'_CHANGED' for k in changes}|set(b['regime']['reason_codes'])|set(b['reason_codes'])|
                 {c['reason_code'] for c in b['conflicts']})
    return {'revision_version':1,'timestamp_utc':current['timestamp_utc'],
            'previous_assessment_id':previous['assessment_id'],'assessment_id':current['assessment_id'],
            'changes':changes,'new_evidence_ids':sorted(after-before),'withdrawn_evidence_ids':sorted(before-after),
            'scenario_evidence_deltas':links,'reason_codes':codes,
            'explanation':'Material state changed in '+', '.join(sorted(changes))+'. See frozen before/after states and evidence deltas; no counterfactual causation is claimed.'}


def _envelope(report):
    if report['status']!='READY':return None
    sources=report['interpretations']['sources']
    cs=[(key,value) for key,value in report['observed_facts']['candles'].items() if value['timeframe']=='M1']
    if not cs:return None
    key,c=max(cs,key=lambda pair:(utc(pair[1]['available_at']),pair[0]))
    structural=[e for e in report['interpretations']['evidence'] if e['category']=='STRUCTURE' and e['timeframe']=='M1']
    refs=sorted({r for e in structural for r in e['references'] if r in sources and sources[r]['kind']=='CONFIRMED_PIVOT'})
    upper=[sources[r]['price'] for r in refs if sources[r]['pivot_kind']=='HIGH']+[c['ohlc']['high']]
    lower=[sources[r]['price'] for r in refs if sources[r]['pivot_kind']=='LOW']+[c['ohlc']['low']]
    if not refs or not min(lower)<max(upper):return None
    return {'lower':min(lower),'upper':max(upper),'evidence_ids':sorted(refs+[key]),'frozen_at_utc':report['timestamp_utc']}


def _review(original,horizon,now,assessments,observations,policy):
    r=original['adaptive_report'];start=utc(original['timestamp_utc']);due=start+timedelta(minutes=horizon)
    complete=now>=due;end=min(now,due);envelope=original['reference_envelope'];reasons=[]
    if not complete:reasons.append('HORIZON_INCOMPLETE')
    if r['status']!='READY':reasons.append('ORIGINAL_ASSESSMENT_'+r['status'])
    leaders=r['assessment']['top_scenarios']
    if len(leaders)>1:reasons.append('ORIGINAL_SCENARIO_TIE')
    if not leaders:reasons.append('NO_ORIGINAL_LEADING_SCENARIO')
    if envelope is None:reasons.append('REFERENCE_ENVELOPE_UNAVAILABLE')
    window=[o for o in observations.values() if o['timeframe']=='M1' and start<utc(o['closed_at_utc'])<=end
            and utc(o['first_seen_at_utc'])<=now]
    window.sort(key=lambda o:(utc(o['closed_at_utc']),o['observation_id']))
    expected={iso(start+timedelta(minutes=i)) for i in range(1,horizon+1) if start+timedelta(minutes=i)<=end}
    if {o['closed_at_utc'] for o in window}!=expected:reasons.append('REVIEW_M1_COVERAGE_INCOMPLETE')
    late=[o['observation_id'] for o in window if utc(o['first_seen_at_utc'])>utc(o['closed_at_utc'])]
    if late:reasons.append('REVIEW_OBSERVATIONS_ARRIVED_LATE')
    blocked=[a['assessment_id'] for a in assessments if start<utc(a['timestamp_utc'])<=end and a['adaptive_report']['status']=='BLOCKED']
    if blocked:reasons.append('REVIEW_INTERVAL_BLOCKED')
    event=None
    if envelope:
        for o in window:
            above=o['ohlc']['high']>envelope['upper'];below=o['ohlc']['low']<envelope['lower']
            if above or below:
                event={'observation_id':o['observation_id'],'closed_at_utc':o['closed_at_utc'],
                       'kind':'AMBIGUOUS_BOTH' if above and below else 'UPPER' if above else 'LOWER'}
                if above and below:reasons.append('OHLC_EVENT_ORDER_AMBIGUOUS')
                break
    # Ties are not a reason to suppress individual scenario reviews.
    unavailable=[c for c in reasons if c!='ORIGINAL_SCENARIO_TIE']
    outcomes=[]
    for name in ('BULLISH','BEARISH','NEUTRAL'):
        if unavailable:status='UNRESOLVED';codes=unavailable
        elif event is None:status='SUPPORTED' if name=='NEUTRAL' else 'UNRESOLVED';codes=['ENVELOPE_HELD'] if name=='NEUTRAL' else ['NO_DIRECTIONAL_BREACH']
        else:
            supported=(name=='BULLISH' and event['kind']=='UPPER') or (name=='BEARISH' and event['kind']=='LOWER')
            status='SUPPORTED' if supported else 'CONTRADICTED';codes=['FIRST_OBSERVED_'+event['kind']+'_BREACH']
        outcomes.append({'scenario':name,'was_original_leader':name in leaders,'status':status,'reason_codes':sorted(codes)})
    status=next(o['status'] for o in outcomes if o['scenario']==leaders[0]) if len(leaders)==1 else 'UNRESOLVED'
    if not reasons:
        reasons.extend(next(o['reason_codes'] for o in outcomes if o['scenario']==leaders[0]) if len(leaders)==1 else ['NO_ORIGINAL_LEADING_SCENARIO'])
    result={'review_version':1,'review_id':'REVIEW:'+digest([original['assessment_id'],horizon,iso(now),policy.sha256]),
            'assessment_id':original['assessment_id'],'assessment_sha256':r['sha256'],
            'original_configuration_hashes':deepcopy(r['configuration_hashes']),
            'review_policy_sha256':policy.sha256,'horizon_minutes':horizon,
            'window_start_utc':iso(start),'due_at_utc':iso(due),'reviewed_at_utc':iso(now),
            'horizon_complete':complete,'status':status,'reason_codes':sorted(set(reasons)),
            'scenario_outcomes':outcomes,'observation_ids':[o['observation_id'] for o in window],
            'blocked_assessment_ids':blocked,'late_observation_ids':late,'first_observed_boundary_event':event,
            'signal':'WAIT','execution_allowed':False}
    return result


class MarketReasoningJournal:
    def __init__(self,symbol,*,review_policy=None):
        self.symbol=symbol;self.policy=ReviewPolicy() if review_policy is None else review_policy
        if not isinstance(self.policy,ReviewPolicy):raise ValueError('Typed review policy required')
        if not isinstance(symbol,str) or not symbol or len(symbol)>128:raise ValueError('Invalid journal symbol')
        self._assessments=[];self._revisions=[];self._reviews=[];self._observations={};self._keys={};self._completed=set()
        self._configuration=None;self._provenance=None

    def record(self,report):
        validate_adaptive_report(report);now=utc(report['timestamp_utc'])
        if report['symbol']!=self.symbol:raise ValueError('Journal symbol changed')
        if self._assessments and now<=utc(self._assessments[-1]['timestamp_utc']):raise ValueError('Journal clock must strictly increase')
        if self._configuration is not None and self._configuration!=report['configuration_hashes']:raise ValueError('Start a new journal for changed configuration')
        if self._provenance is not None and self._provenance!=report['provenance']:raise ValueError('Journal provenance changed')
        original={'assessment_version':1,'assessment_id':'ASSESSMENT:'+digest([self.symbol,report['timestamp_utc'],report['sha256']]),
                  'timestamp_utc':report['timestamp_utc'],'adaptive_report':deepcopy(report),'reference_envelope':_envelope(report)}
        observations=deepcopy(self._observations);keys=dict(self._keys)
        for source_id,c in sorted(report['observed_facts'].get('candles',{}).items()):
            if (c.get('kind')!='CANDLE' or c.get('timeframe') not in ('M1','M5')
                    or c!=report['interpretations']['sources'].get(source_id)
                    or utc(c['available_at'])>now
                    or utc(c['observed_at'])+timedelta(minutes=1 if c['timeframe']=='M1' else 5)!=utc(c['available_at'])):
                raise ValueError('Unavailable or inconsistent journal candle observation')
            key=(c['timeframe'],iso(utc(c['observed_at'])))
            content=[self.symbol,c['timeframe'],iso(utc(c['observed_at'])),iso(utc(c['available_at'])),c['ohlc']]
            oid='OBSERVATION:'+digest(content)
            if key in keys and keys[key]!=oid:raise ValueError('Previously observed candle changed')
            if oid not in observations:
                keys[key]=oid
                observations[oid]={'observation_id':oid,'symbol':self.symbol,'timeframe':c['timeframe'],
                    'opened_at_utc':key[1],'closed_at_utc':iso(utc(c['available_at'])),
                    'first_seen_at_utc':iso(now),'source_assessment_id':original['assessment_id'],
                    'source_evidence_id':source_id,'ohlc':deepcopy(c['ohlc'])}
        assessments=self._assessments+[original];reviews=[];completed=set(self._completed)
        for a in assessments:
            for h in self.policy.horizons_minutes:
                key=(a['assessment_id'],h)
                if key in completed:continue
                review=_review(a,h,now,assessments,observations,self.policy)
                reviews.append(review)
                if review['horizon_complete']:completed.add(key)
        revision=_revision(self._assessments[-1],original) if self._assessments else None
        # Commit only after the entire new record/review batch has been established.
        self._configuration=deepcopy(report['configuration_hashes']);self._provenance=report['provenance']
        self._observations=observations;self._keys=keys;self._completed=completed
        self._assessments.append(original);self._reviews.extend(reviews)
        if revision:self._revisions.append(revision)
        return deepcopy(original)

    def to_dict(self):
        result={'journal_version':1,'kind':'MARKET_REASONING_JOURNAL','symbol':self.symbol,
                'review_policy':asdict(self.policy),'review_criteria':deepcopy(CRITERIA),'review_policy_sha256':self.policy.sha256,
                'adaptive_configuration_hashes':deepcopy(self._configuration),'provenance':self._provenance,
                'assessments':deepcopy(self._assessments),'assessment_revisions':deepcopy(self._revisions),
                'observations':sorted(deepcopy(list(self._observations.values())),key=lambda o:(o['first_seen_at_utc'],o['closed_at_utc'],o['observation_id'])),
                'outcome_reviews':deepcopy(self._reviews),'summary':_summary(self._assessments,self._revisions,self._reviews,self.policy),
                'historical_validation':'PENDING','historical_comparisons':'NOT_RUN','exness':'BLOCKED',
                'mode':'READ_ONLY_SHADOW','signal':'WAIT','execution_allowed':False}
        result['sha256']=digest(result);return result


def _summary(assessments,revisions,reviews,policy):
    latest={}
    for r in reviews:latest[r['assessment_id'],r['horizon_minutes']]=r
    originals={a['assessment_id']:a['adaptive_report'] for a in assessments}
    count=lambda statuses:{s:sum(v==s for v in statuses) for s in ('SUPPORTED','CONTRADICTED','UNRESOLVED')}
    horizons=[]
    for h in policy.horizons_minutes:
        rows=[r for (aid,hh),r in latest.items() if hh==h]
        unique=[r for r in rows if len(originals[r['assessment_id']]['assessment']['top_scenarios'])==1]
        tied=[r for r in rows if len(originals[r['assessment_id']]['assessment']['top_scenarios'])>1]
        per_scenario=[]
        for name in ('BULLISH','BEARISH','NEUTRAL'):
            all_rows=[o for r in rows for o in r['scenario_outcomes'] if o['scenario']==name]
            leaders=[o for o in all_rows if o['was_original_leader']]
            per_scenario.append({'scenario':name,'all_assessment_denominator':len(all_rows),
                'all_assessment_outcomes':count([o['status'] for o in all_rows]),
                'leader_membership_denominator':len(leaders),'leader_membership_outcomes':count([o['status'] for o in leaders])})
        horizons.append({'horizon_minutes':h,'assessment_review_denominator':len(rows),
            'complete_horizons':sum(r['horizon_complete'] for r in rows),'incomplete_horizons':sum(not r['horizon_complete'] for r in rows),
            'assessment_outcomes':count([r['status'] for r in rows]),'unique_leader_denominator':len(unique),
            'unique_leader_outcomes':count([r['status'] for r in unique]),'tied_leader_denominator':len(tied),
            'tied_leader_outcomes':count([r['status'] for r in tied]),
            'no_leader_denominator':len(rows)-len(unique)-len(tied),
            'original_status_denominators':{s:sum(originals[r['assessment_id']]['status']==s for r in rows) for s in ('READY','UNKNOWN','BLOCKED')},
            'reason_counts':dict(sorted(Counter(c for r in rows for c in r['reason_codes']).items())), 'scenario_reviews':per_scenario})
    return {'assessment_count':len(assessments),'transitions_denominator':max(0,len(assessments)-1),
            'material_assessment_changes':len(revisions),
            'change_counts':dict(sorted(Counter(k for r in revisions for k in r['changes']).items())),
            'original_status_counts':{s:sum(a['adaptive_report']['status']==s for a in assessments) for s in ('READY','UNKNOWN','BLOCKED')},
            'tied_assessments':sum(len(a['adaptive_report']['assessment']['top_scenarios'])>1 for a in assessments),
            'outcome_record_versions':len(reviews),'latest_assessment_horizon_pairs':len(latest),'horizons':horizons}


def replay_reasoning_journal(symbol,m1_history,m5_history,*,review_policy=None,as_of=None,**options):
    ledger=MarketReasoningJournal(symbol,review_policy=review_policy)
    for report in replay_adaptive(symbol,m1_history,m5_history,as_of=as_of,**options):ledger.record(report)
    return ledger.to_dict()


def journal_prefix(journal,cutoff):
    """Project only records actually available by a common UTC cutoff."""
    at=utc(iso(cutoff));result=deepcopy(journal)
    result['assessments']=[a for a in result['assessments'] if utc(a['timestamp_utc'])<=at]
    result['assessment_revisions']=[r for r in result['assessment_revisions'] if utc(r['timestamp_utc'])<=at]
    result['observations']=[o for o in result['observations'] if utc(o['first_seen_at_utc'])<=at]
    result['outcome_reviews']=[r for r in result['outcome_reviews'] if utc(r['reviewed_at_utc'])<=at]
    first=result['assessments'][0]['adaptive_report'] if result['assessments'] else None
    result['adaptive_configuration_hashes']=deepcopy(first['configuration_hashes']) if first else None
    result['provenance']=first['provenance'] if first else None
    result['summary']=_summary(result['assessments'],result['assessment_revisions'],result['outcome_reviews'],ReviewPolicy.from_dict(result['review_policy']))
    result['sha256']=digest({k:v for k,v in result.items() if k!='sha256'});return result


def validate_reasoning_journal(journal):
    """Rebuild all derived records from the frozen causal adaptive assessments."""
    if type(journal['journal_version']) is not int or journal['journal_version']!=1 or journal['kind']!='MARKET_REASONING_JOURNAL':
        raise ValueError('Unsupported reasoning journal')
    ledger=MarketReasoningJournal(journal['symbol'],review_policy=ReviewPolicy.from_dict(journal['review_policy']))
    for a in journal['assessments']:ledger.record(a['adaptive_report'])
    expected=ledger.to_dict()
    if digest(expected)!=digest(journal):raise ValueError('Reasoning journal content/checksum/derivation mismatch')
    return True


def write_reasoning_journal(path,journal):
    """Atomic private publication, preserving an explicit incomplete file on failure."""
    import os
    from pathlib import Path
    import tempfile
    validate_reasoning_journal(journal);path=Path(path)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as handle:
        handle.write(b'{"publication_status":"INCOMPLETE"}\n');handle.flush();os.fsync(handle.fileno())
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.iat-journal-',delete=False) as handle:
            temporary=Path(handle.name);handle.write((json.dumps(journal,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())
            handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
