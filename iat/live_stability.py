"""Bounded local observer sampling; never independent broker stability certification."""
from collections import Counter
from math import isfinite
import re
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import utc


class StabilitySampler:
    def __init__(self):
        self.reasons=Counter();self.connected=0;self.bid_updates=0;self.tick_updates=0;self.acquisition_updates=0;self.reconnects=0
        self.cutoff_updates={'M1':0,'M5':0};self.previous_status=None;self.previous_connected=None;self.metadata=[];self.unsafe=False
    def add(self,item):
        """Retain only summary metadata and one previous quote, never raw histories."""
        try:
            if not isinstance(item,dict):raise ValueError('Malformed sample')
            if item.get('diagnostic_error'):raise ValueError('Local observer unavailable')
            if (item['signal']!='WAIT' or item['execution_allowed'] is not False or item['broker_access'] is not False
                or type(item['orders_requested']) is not int or item['orders_requested']!=0 or item['profitability_tested'] is not False
                or item['exness']!='BLOCKED' or item['qualification']!='DATA_NOT_QUALIFIED'
                or item['historical_validation']!='PENDING' or item['historical_comparisons']!='NOT_RUN'):
                self.unsafe=True;raise ValueError('Safety invariant')
            if item['snapshot_id']!=digest({k:v for k,v in item.items() if k!='snapshot_id'}):raise ValueError('Snapshot identity')
            if not all(isinstance(code,str) and re.fullmatch('[A-Z0-9_]{1,128}',code) for code in item['reason_codes']):raise ValueError('Reason codes')
            if item['feed_status']=='CONNECTED':
                quote=item['quote'];at=utc(item['acquired_at_utc']);tick=utc(quote['observed_at_utc'])
                if type(quote['bid']) not in (int,float) or not isfinite(quote['bid']) or quote['bid']<=0:raise ValueError('Bid')
                if not -2<=(at-tick).total_seconds()<=30:raise ValueError('Stale or future quote')
                for tf,seconds in (('M1',60),('M5',300)):
                    cutoff=utc(item['cutoffs'][tf])
                    if cutoff.timestamp()%seconds or not 0<=(at-cutoff).total_seconds()<=seconds*2:raise ValueError('Invalid candle cutoff')
                old=self.previous_connected
                if old:
                    if at<utc(old['acquired_at_utc']) or tick<utc(old['quote']['observed_at_utc']):raise ValueError('Backward observation')
                    for tf in ('M1','M5'):
                        if utc(item['cutoffs'][tf])<utc(old['cutoffs'][tf]):raise ValueError('Backward candle cutoff')
                    self.acquisition_updates+=at>utc(old['acquired_at_utc']);self.tick_updates+=tick>utc(old['quote']['observed_at_utc'])
                    self.bid_updates+=quote['bid']!=old['quote']['bid']
                    for tf in ('M1','M5'):self.cutoff_updates[tf]+=item['cutoffs'][tf]!=old['cutoffs'][tf]
                self.connected+=1
                if self.previous_status is not None and self.previous_status!='CONNECTED':self.reconnects+=1
                self.previous_connected=dict(acquired_at_utc=item['acquired_at_utc'],quote=dict(bid=quote['bid'],observed_at_utc=quote['observed_at_utc']),cutoffs=dict(item['cutoffs']))
            elif item['feed_status']=='DATA_UNAVAILABLE':
                if item['quote'] is not None or item['observations']:self.unsafe=True;raise ValueError('Stale observations not cleared')
                self.previous_connected=None
                for code in item['reason_codes']:self.reasons[code]+=1
            else:raise ValueError('Unknown status')
            self.metadata.append(dict(snapshot_id=item['snapshot_id'],acquired_at_utc=item['acquired_at_utc'],status=item['feed_status'],cutoffs=dict(item['cutoffs']),reason_codes=list(item['reason_codes'])))
            self.previous_status=item['feed_status']
        except (ValueError,KeyError,TypeError,OverflowError):
            code='LOCAL_OBSERVER_UNAVAILABLE' if isinstance(item,dict) and item.get('diagnostic_error') else 'SNAPSHOT_INVALID_OR_INVARIANT_FAILED'
            self.reasons[code]+=1;self.previous_connected=None;self.previous_status='DATA_UNAVAILABLE'
            self.metadata.append(dict(status='DATA_UNAVAILABLE',reason_codes=[code]))
    def report(self):
        issues=[]
        if not self.connected:issues.append('NO_CONNECTED_SAMPLES')
        if not self.tick_updates:issues.append('QUOTE_TIMESTAMP_PROGRESS_NOT_OBSERVED')
        for tf,n in self.cutoff_updates.items():
            if not n:issues.append(tf+'_CLOSE_TRANSITION_NOT_OBSERVED')
        if self.reasons:issues.append('BLOCKED_OR_INVALID_SAMPLES_OBSERVED')
        critical=self.unsafe or self.reasons['SNAPSHOT_INVALID_OR_INVARIANT_FAILED']>0
        result=dict(stability_version=1,scope='LOCAL_OBSERVER_SAMPLING_NOT_BROKER_CERTIFICATION',
            status='FAIL' if critical or not self.connected else 'WARN' if issues else 'PASS',sample_count=len(self.metadata),connected_samples=self.connected,
            blocked_samples=len(self.metadata)-self.connected,bid_changes=self.bid_updates,quote_timestamp_updates=self.tick_updates,
            acquisition_updates=self.acquisition_updates,closed_cutoff_transitions=dict(self.cutoff_updates),reconnections=self.reconnects,
            reason_counts=dict(sorted(self.reasons.items())),issues=issues,samples=list(self.metadata),
            signal='WAIT',execution_allowed=False,broker_access=False,orders_requested=0,profitability_tested=False,exness='BLOCKED',qualification='DATA_NOT_QUALIFIED',historical_validation='PENDING',historical_comparisons='NOT_RUN')
        result['sha256']=digest(result);return result


def assess_samples(samples):
    sampler=StabilitySampler()
    for item in samples:sampler.add(item)
    return sampler.report()
