"""Procedural SYNTHETIC OHLC replay plus labeled observation-contract state tests."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta
from pathlib import Path
import json
import unittest
import tempfile
from unittest.mock import patch
from iat.intelligence.context import analyze_context
from iat.intelligence.strategy_replay import (StrategyReplayLedger,replay_strategies,
                                             validate_strategy_replay_log,setup_identity,digest,write_strategy_replay_log)
from test_research_strategies import observation_fixture,synthetic_ohlc_fixture
from test_context_components import CONFIG
from test_context_engine import P7


def replay_fixture(reversal=False,mirror=False):
    """SYNTHETIC only: no acquired bars and no historical-feed claim."""
    a,b,at=synthetic_ohlc_fixture(reversal,False)
    if reversal:
        a[-1].update(open=100.12,high=100.121,low=100.059,close=100.06)
        a.append(dict(timestamp=at.isoformat(),open=100.18,high=100.181,low=100.019,close=100.02))
        for i in range(1,7):
            a.append(dict(timestamp=(at+timedelta(minutes=i)).isoformat(),open=100.02,high=100.025,low=100.015,close=100.02))
    else:
        a.append(dict(timestamp=at.isoformat(),open=100.07,high=100.13,low=100.069,close=100.125))
        a.append(dict(timestamp=(at+timedelta(minutes=1)).isoformat(),open=100.12,high=100.121,low=99.799,close=99.8))
    if mirror:
        for cs in (a,b):
            for c in cs:
                o,h,l,cl=(c[k] for k in ('open','high','low','close'))
                c.update(open=200-o,high=200-l,low=200-h,close=200-cl)
    return a,b,at


def group(log,strategy='M5_TREND_M1_CONFIRMATION',direction='BULLISH'):
    return next(g for g in log['summary']['groups'] if g['strategy_id']==strategy and g['direction']==direction)


def contract(report,minutes=0,*,opposing=False,new_anchor=False):
    """Explicit synthetic contract: stable canonical pivot/sweep anchors across revisions."""
    r=deepcopy(report);at=datetime.fromisoformat(r.analysis_at)+timedelta(minutes=minutes)
    sources=r.interpretations['source_registry'];es=[]
    for e in r.evidence:
        details=dict(e.details)
        if opposing and e.category=='TRANSITION':
            direction='BEARISH' if e.direction=='BULLISH' else 'BULLISH'
            details['event_type']=direction+'_CHOCH';e=replace(e,direction=direction,details=details)
        if e.category=='STRUCTURE' and e.timeframe=='M5':
            pivot='SYNTHETIC:canonical-pivot'+(':new' if new_anchor else '')
            sources[pivot]={'kind':'CONFIRMED_PIVOT','timeframe':'M5','available_at':e.available_at,'observed_at':e.observed_at}
            e=replace(e,references=(pivot,))
        # Context evidence IDs may change every minute, while canonical anchors do not.
        es.append(replace(e,id=e.id+':revision'+str(minutes),available_at=at.isoformat()))
    frame=r.interpretations['frames']['M1'];sweep=frame['liquidity_events'][0]
    if new_anchor:sweep=replace(sweep,id=sweep.id+':new')
    frame['liquidity_events']=(sweep,)
    sources[sweep.id]={'kind':'LIQUIDITY_EVENT','timeframe':'M1','available_at':sweep.available_at,'observed_at':sweep.occurred_at}
    for tf in ('M1','M5'):r.observed_facts[tf]['data_as_of']=at.isoformat()
    return replace(r,analysis_at=at.isoformat(),evidence=tuple(es))


def ledger():return StrategyReplayLedger('SYNTHETIC_XAUUSD',config=CONFIG,intelligence_config=P7)


class LifecycleTests(unittest.TestCase):
    def test_consecutive_qualifications_count_once_for_each_strategy_and_direction(self):
        for direction in ('BULLISH','BEARISH'):
            base=observation_fixture(direction);l=ledger()
            l.record(contract(base));l.record(contract(base,1))
            log=l.to_dict();validate_strategy_replay_log(log)
            for strategy in ('M5_TREND_M1_CONFIRMATION','SWEEP_M1_STRUCTURE_CHANGE'):
                g=group(log,strategy,direction)
                self.assertEqual(g['snapshot_outcomes']['QUALIFIES'],2)
                self.assertEqual(g['unique_qualified_setups'],1)
                self.assertEqual(g['active_qualified_setups'],1)
            self.assertTrue(any(e['event']=='REPEATED_QUALIFICATION' for e in log['entries'][1]['lifecycle_events']))
    def test_invalidation_after_qualification_and_no_rearming_retired_anchor(self):
        for direction in ('BULLISH','BEARISH'):
            base=observation_fixture(direction);l=ledger()
            l.record(contract(base));l.record(contract(base,1,opposing=True));l.record(contract(base,2))
            log=l.to_dict()
            for strategy in ('M5_TREND_M1_CONFIRMATION','SWEEP_M1_STRUCTURE_CHANGE'):
                g=group(log,strategy,direction)
                self.assertEqual(g['unique_qualified_setups'],1)
                self.assertEqual(g['invalidated_qualified_setups'],1)
                self.assertEqual(g['active_qualified_setups'],0)
            self.assertTrue(any(e['event']=='ANCHOR_RETIRED_NO_REARM' for e in log['entries'][-1]['lifecycle_events']))
    def test_invalidation_without_qualification_is_not_an_invalidated_qualified_setup(self):
        base=observation_fixture();l=ledger();l.record(contract(base,opposing=True));l.record(contract(base,1))
        for strategy in ('M5_TREND_M1_CONFIRMATION','SWEEP_M1_STRUCTURE_CHANGE'):
            g=group(l.to_dict(),strategy)
            self.assertEqual(g['invalidated_qualified_setups'],0)
            self.assertEqual(g['unique_qualified_setups'],0)
            self.assertEqual(g['unqualified_invalidated_anchors'],1)
    def test_distinct_anchors_rearm_and_scope_prevents_strategy_direction_symbol_collisions(self):
        base=observation_fixture();l=ledger()
        l.record(contract(base));l.record(contract(base,1,opposing=True));l.record(contract(base,2,new_anchor=True))
        for strategy in ('M5_TREND_M1_CONFIRMATION','SWEEP_M1_STRUCTURE_CHANGE'):
            g=group(l.to_dict(),strategy)
            self.assertEqual(g['unique_qualified_setups'],2);self.assertEqual(g['active_qualified_setups'],1)
        anchor={'kind':'test','references':['canonical']}
        ids={setup_identity(s,v,symbol,d,anchor) for s in ('a','b') for v in ('1','2') for symbol in ('X','Y') for d in ('BULLISH','BEARISH')}
        self.assertEqual(len(ids),16)
    def test_sweep_expires_strictly_after_five_minutes_and_not_on_abstention(self):
        base=observation_fixture();l=ledger();l.record(contract(base))
        # Sweep available two minutes before first snapshot: inclusive age=5 at +3.
        l.record(contract(base,3));self.assertEqual(group(l.to_dict(),'SWEEP_M1_STRUCTURE_CHANGE')['expired_qualified_setups'],0)
        l.record(contract(base,4));self.assertEqual(group(l.to_dict(),'SWEEP_M1_STRUCTURE_CHANGE')['expired_qualified_setups'],1)
        self.assertEqual(group(l.to_dict())['active_qualified_setups'],1)
    def test_continuation_anchor_supersession_expires_previous_setup(self):
        base=observation_fixture();l=ledger();l.record(contract(base));l.record(contract(base,1,new_anchor=True))
        g=group(l.to_dict());self.assertEqual(g['expired_qualified_setups'],1);self.assertEqual(g['unique_qualified_setups'],2)
    def test_lost_continuation_anchor_expires_and_cannot_rearm_on_return(self):
        base=observation_fixture();l=ledger();l.record(contract(base))
        changed=contract(base,1);changed=replace(changed,context=dict(changed.context,m5_structure='BEARISH'))
        changed=replace(changed,evidence=tuple(replace(e,direction='BEARISH') if e.category=='STRUCTURE' and e.timeframe=='M5' else e for e in changed.evidence))
        l.record(changed);l.record(contract(base,2))
        g=group(l.to_dict());self.assertEqual(g['unique_qualified_setups'],1)
        self.assertEqual(g['expired_qualified_setups'],1);self.assertEqual(g['active_qualified_setups'],0)

    def test_blocked_snapshot_is_separate_and_does_not_invalidate_or_expire(self):
        base=observation_fixture();l=ledger();l.record(contract(base))
        blocked=replace(contract(base,4),data_quality={'valid':False,'status':'BLOCKED','diagnostics':[]})
        entry=l.record(blocked)
        self.assertFalse(entry['lifecycle_events'])
        self.assertTrue(all(r['snapshot_outcome']=='BLOCKED_DATA' for r in entry['evaluations']))
        self.assertEqual(group(l.to_dict(),'SWEEP_M1_STRUCTURE_CHANGE')['expired_qualified_setups'],0)
        l.record(contract(base,5))
        self.assertEqual(group(l.to_dict(),'SWEEP_M1_STRUCTURE_CHANGE')['expired_qualified_setups'],1)
    def test_rejected_snapshot_does_not_mutate_state_or_earlier_entries(self):
        base=observation_fixture();l=ledger();first=l.record(contract(base));before=l.to_dict()
        with self.assertRaises(ValueError):l.record(contract(base))
        self.assertEqual(before,l.to_dict())
        with self.assertRaises(ValueError):l.record(replace(contract(base,1),configuration_sha256='f'*64))
        self.assertEqual(before,l.to_dict());first['evaluations'].clear()
        self.assertTrue(l.to_dict()['entries'][0]['evaluations'])
    def test_future_evidence_is_rejected_without_advancing_ledger(self):
        base=observation_fixture();l=ledger();r=contract(base)
        r.interpretations['source_registry']['future']={'available_at':'2099-01-01T00:00:00Z','kind':'CANDLE','timeframe':'M1','ohlc':{'close':100}}
        before=l.to_dict()
        with self.assertRaises(ValueError):l.record(r)
        self.assertEqual(before,l.to_dict())


class SyntheticOHLCReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.logs={}
        for rev in (False,True):
            for mirror in (False,True):
                a,b,_=replay_fixture(rev,mirror)
                cls.logs[rev,mirror]=replay_strategies('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7)
    def test_actual_ohlc_counts_consecutive_qualifications_invalidations_and_expiry(self):
        for (rev,mirror),log in self.logs.items():
            with self.subTest(reversal=rev,mirror=mirror):
                validate_strategy_replay_log(log)
                direction=('BULLISH' if mirror else 'BEARISH') if rev else ('BEARISH' if mirror else 'BULLISH')
                strategy='SWEEP_M1_STRUCTURE_CHANGE' if rev else 'M5_TREND_M1_CONFIRMATION'
                g=group(log,strategy,direction)
                self.assertEqual(log['summary']['timestamps'],30 if rev else 23)
                self.assertEqual(log['summary']['blocked_timestamps'],2)
                self.assertEqual(g['snapshot_outcomes']['QUALIFIES'],2)
                self.assertEqual(g['unique_qualified_setups'],1)
                self.assertEqual(g['expired_qualified_setups'],1 if rev else 0)
                self.assertEqual(g['invalidated_qualified_setups'],0 if rev else 1)
    def test_repeatability_prefix_equivalence_and_future_append_invariance(self):
        for (rev,mirror),full in self.logs.items():
            a,b,at=replay_fixture(rev,mirror)
            repeated=replay_strategies('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7)
            self.assertEqual(full['sha256'],repeated['sha256'])
            cutoff=at+timedelta(minutes=1)
            prefix_a=[r for r in a if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=1)<=cutoff]
            prefix_b=[r for r in b if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=5)<=cutoff]
            p=replay_strategies('SYNTHETIC_XAUUSD',prefix_a,prefix_b,config=CONFIG,intelligence_config=P7)
            bounded=replay_strategies('SYNTHETIC_XAUUSD',a,b,as_of=cutoff,config=CONFIG,intelligence_config=P7)
            self.assertEqual(p,bounded)
            self.assertEqual(p['entries'],full['entries'][:len(p['entries'])])
            # An additional closed/future candle and an unfinished M5 cannot revise the prefix.
            a.append(dict(timestamp=(datetime.fromisoformat(a[-1]['timestamp'])+timedelta(minutes=1)).isoformat(),open=100,high=999,low=1,close=998))
            b.append(dict(timestamp=(datetime.fromisoformat(b[-1]['timestamp'])+timedelta(minutes=5)).isoformat(),open=100,high=999,low=1,close=998))
            self.assertEqual(p,replay_strategies('SYNTHETIC_XAUUSD',a,b,as_of=cutoff,config=CONFIG,intelligence_config=P7))
    def test_actual_ohlc_invalidation_without_prior_qualification_counts_zero(self):
        for mirror in (False,True):
            a,b,_=replay_fixture(False,mirror)
            for row in a[-3:-1]:row['open']=row['close']
            log=replay_strategies('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7)
            g=group(log,direction='BEARISH' if mirror else 'BULLISH')
            self.assertEqual(g['snapshot_outcomes']['QUALIFIES'],0)
            self.assertEqual(g['snapshot_outcomes']['INVALIDATED'],1)
            self.assertEqual(g['unique_qualified_setups'],0)
            self.assertEqual(g['invalidated_qualified_setups'],0)
            self.assertEqual(g['unqualified_invalidated_anchors'],1)

    def test_validator_rejects_forged_counts_and_lifecycle_transitions(self):
        for defect in ('counts','state','identity','transition','blocked'):
            log=deepcopy(self.logs[False,False])
            if defect=='counts':log['summary']['timestamps']+=1
            elif defect=='state':log['setups'][0]['state']='ACTIVE'
            elif defect=='identity':log['setups'][0]['setup_id']='SETUP:'+'0'*64
            elif defect=='transition':
                for e in log['entries']:
                    for event in e['lifecycle_events']:
                        if event['event']=='QUALIFIED':event['event']='INVALIDATED_QUALIFIED_SETUP'
            else:log['entries'][-1]['data_quality']['valid']=False
            log['sha256']=digest({k:v for k,v in log.items() if k!='sha256'})
            with self.subTest(defect=defect),self.assertRaises(ValueError):validate_strategy_replay_log(log)

    def test_future_tail_does_not_apply_visible_history_limit_retroactively(self):
        a,b,at=replay_fixture()
        before=replay_strategies('SYNTHETIC_XAUUSD',a,b,as_of=at,config=CONFIG,intelligence_config=P7)
        start=datetime.fromisoformat(a[-1]['timestamp'])+timedelta(minutes=1)
        a.extend(dict(timestamp=(start+timedelta(minutes=i)).isoformat(),open=100,high=101,low=99,close=100) for i in range(5000))
        self.assertEqual(before,replay_strategies('SYNTHETIC_XAUUSD',a,b,as_of=at,config=CONFIG,intelligence_config=P7))

    def test_missing_bar_is_blocked_not_a_fabricated_timestamp(self):
        a,b,_=replay_fixture();missing=a.pop(10)['timestamp']
        log=replay_strategies('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7)
        self.assertEqual(log['summary']['timestamps'],len(a))
        self.assertGreater(log['summary']['blocked_timestamps'],2)
        self.assertNotIn((datetime.fromisoformat(missing)+timedelta(minutes=1)).isoformat(),[e['timestamp_utc'] for e in log['entries']])
    def test_unordered_duplicate_and_backward_replay_clocks_are_rejected(self):
        a,b,_=replay_fixture()
        for rows in (a+[a[-1]],a[:5]+[a[3]]+a[5:]):
            with self.assertRaises(ValueError):replay_strategies('SYNTHETIC_XAUUSD',rows,b,config=CONFIG,intelligence_config=P7)
    def test_published_synthetic_audit_matches_actual_logs_and_counts(self):
        audit=json.loads(Path('docs/source_reviews/strategy-replay-synthetic-v1.json').read_text())
        for (rev,mirror),log in self.logs.items():
            direction=('BULLISH' if mirror else 'BEARISH') if rev else ('BEARISH' if mirror else 'BULLISH')
            name=('sweep_' if rev else 'continuation_')+direction.lower()
            c=next(c for c in audit['cases'] if c['case']==name)
            self.assertEqual(c['repeatability']['hashes'],[log['sha256']]*2)
            self.assertEqual(c['configuration_hashes'],log['configuration_hashes'])
            self.assertEqual(c['timestamps'],log['summary']['timestamps'])
            self.assertEqual(c['groups'],[{k:v for k,v in g.items() if k!='reason_counts'} for g in log['summary']['groups']])
            self.assertEqual(c['prefix_equivalence']['status'],'PASS')
            self.assertEqual(c['future_append_invariance']['status'],'PASS')
        self.assertEqual(audit['historical_validation'],'PENDING')
        self.assertEqual(audit['historical_comparisons'],'NOT_RUN')

    def test_serialized_log_roundtrip_safety_and_version_checks(self):
        log=json.loads(json.dumps(self.logs[False,False]));self.assertTrue(validate_strategy_replay_log(log))
        for key,value in (('log_version',True),('execution_allowed',True),('historical_validation','PASSED')):
            changed=deepcopy(log);changed[key]=value;changed['sha256']=digest({k:v for k,v in changed.items() if k!='sha256'})
            with self.assertRaises(ValueError):validate_strategy_replay_log(changed)
        log['entries'][0]['timestamp_utc']='2099-01-01T00:00:00Z'
        with self.assertRaises(ValueError):validate_strategy_replay_log(log)
    def test_private_log_writer_roundtrip_and_overwrite_protection(self):
        log=self.logs[False,False]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'strategy replay.json'
            write_strategy_replay_log(path,log)
            restored=json.loads(path.read_text());self.assertEqual(restored,json.loads(json.dumps(log)))
            validate_strategy_replay_log(restored)
            before=path.read_bytes()
            with self.assertRaises(FileExistsError):write_strategy_replay_log(path,log)
            self.assertEqual(before,path.read_bytes())
    def test_publication_failure_leaves_explicit_incomplete_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'strategy replay.json'
            with patch('os.replace',side_effect=OSError('SYNTHETIC_FAILURE')):
                with self.assertRaises(OSError):write_strategy_replay_log(path,self.logs[False,False])
            self.assertEqual(json.loads(path.read_text()),{'publication_status':'INCOMPLETE'})
            self.assertFalse(list(Path(folder).glob('.iat-strategy-*')))

    def test_unverified_exness_calendar_is_fingerprinted_and_blocks_replay(self):
        from iat.session_config import load_session_config
        calendar=load_session_config('config/profiles/exness-xauusd-v2.candidate.json')
        a,b,_=replay_fixture()
        log=replay_strategies('XAUUSD',a,b,config=CONFIG,intelligence_config=P7,calendar=calendar)
        self.assertEqual(log['configuration_hashes']['session'],calendar.configuration_sha256)
        self.assertEqual(log['summary']['blocked_timestamps'],len(a))
        self.assertTrue(all(g['unique_qualified_setups']==0 for g in log['summary']['groups']))
        validate_strategy_replay_log(log)

    def test_inherited_rules_and_decision_log_contract_remain_unchanged(self):
        from iat.intelligence.context_models import ContextConfig
        from iat.intelligence.models import IntelligenceConfig
        from iat.intelligence.decision_log import DecisionLog
        self.assertEqual(ContextConfig().digest,'d8bda7da1af47cc1f1f349682b71ca75f39bef89b7fb5d5873bc0bba5510d424')
        self.assertEqual(IntelligenceConfig().digest,'0b1db8f78abc3801b23a2aec62ee6057a1b0b711a8244405bc5f77ff582653ff')
        self.assertEqual(DecisionLog(1,{},()).to_dict(),{'log_version':1,'configuration_hashes':{},'entries':()})
        for log in self.logs.values():
            self.assertEqual(log['historical_comparisons'],'NOT_RUN');self.assertEqual(log['historical_validation'],'PENDING')
            self.assertFalse(log['execution_allowed']);self.assertEqual(log['signal'],'WAIT');self.assertEqual(log['exness'],'BLOCKED')
