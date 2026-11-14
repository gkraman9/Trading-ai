"""SYNTHETIC OHLC and explicitly labeled contract checks, never historical validation."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta
from pathlib import Path
import json,tempfile,unittest
from unittest.mock import patch
from iat.intelligence.adaptive import adaptive_at,replay_adaptive
from iat.intelligence.journal_policy import ReviewPolicy
from iat.intelligence.reasoning_journal import (MarketReasoningJournal,replay_reasoning_journal,
    journal_prefix,validate_reasoning_journal,write_reasoning_journal)
from iat.intelligence.strategy_replay import digest
from test_adaptive_intelligence import synthetic_cases,CONFIG,P7,actual_range
from test_context_engine import two_frames
from test_research_strategies import synthetic_ohlc_fixture


def journal_fixture(case='persistent_trend'):
    """Closed procedural synthetic OHLC with independently computed IAT observations."""
    if case=='tie':
        a,b,at=two_frames()
        for c in b:
            o,h,l,cl=(c[k] for k in ('open','high','low','close'));c.update(open=200-o,high=200-l,low=200-h,close=200-cl)
    elif case=='neutral_range':a,b,at=actual_range()
    else:a,b,at=two_frames()
    origin=at
    if case=='opposing_choch':
        a.append(dict(timestamp=at.isoformat(),open=112,high=116.4,low=111.5,close=112))
        a.append(dict(timestamp=(at+timedelta(minutes=1)).isoformat(),open=112,high=112.1,low=93.9,close=94))
    elif case=='ambiguous':a.append(dict(timestamp=at.isoformat(),open=112,high=130,low=90,close=112))
    elif case=='neutral_range':
        for i in range(5):a.append(dict(timestamp=(at+timedelta(minutes=i)).isoformat(),open=100,high=103,low=97,close=100))
    else:
        for i in range(8):
            v=118+i
            a.append(dict(timestamp=(at+timedelta(minutes=i)).isoformat(),open=v-.5,high=v+.5,low=v-1,close=v))
    # Complete five-minute review horizon even after a reversal/ambiguous event.
    while datetime.fromisoformat(a[-1]['timestamp'])+timedelta(minutes=1)<origin+timedelta(minutes=8):
        at=datetime.fromisoformat(a[-1]['timestamp'])+timedelta(minutes=1);v=a[-1]['close']
        a.append(dict(timestamp=at.isoformat(),open=v,high=v+.5,low=v-.5,close=v))
    if case=='blocked_interval':a.pop(-6)
    if case=='incomplete':a=a[:len(a)-6]
    # Extend M5 with causal, labeled synthetic bars for freshness; not an independent feed claim.
    end=datetime.fromisoformat(a[-1]['timestamp'])+timedelta(minutes=1)
    while datetime.fromisoformat(b[-1]['timestamp'])+timedelta(minutes=5)<end:
        opened=datetime.fromisoformat(b[-1]['timestamp'])+timedelta(minutes=5)
        b.append(dict(timestamp=opened.isoformat(),open=112,high=116,low=108,close=112))
    return a,b,origin


def run_case(case,*,policy=None,cutoff=None):
    a,b,origin=journal_fixture(case)
    return replay_reasoning_journal('SYNTHETIC_XAUUSD',a,b,as_of=cutoff,review_policy=policy,config=CONFIG,intelligence_config=P7),origin


def latest_review(journal,origin,horizon=5):
    original=next(a for a in journal['assessments'] if a['timestamp_utc']==origin.isoformat())
    return [r for r in journal['outcome_reviews'] if r['assessment_id']==original['assessment_id'] and r['horizon_minutes']==horizon][-1]


class JournalPolicyTests(unittest.TestCase):
    def test_versioned_explicit_horizons_and_criteria(self):
        self.assertEqual(ReviewPolicy().horizons_minutes,(5,15))
        self.assertEqual(ReviewPolicy.from_dict(json.loads(json.dumps({'version':1,'horizons_minutes':[1,3],'criteria_version':1}))).horizons_minutes,(1,3))
        for kwargs in ({'version':True},{'criteria_version':2},{'horizons_minutes':(0,)},{'horizons_minutes':(True,)},
                       {'horizons_minutes':(5,5)},{'horizons_minutes':(15,5)},{'horizons_minutes':[]}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):ReviewPolicy(**kwargs)
        self.assertNotEqual(ReviewPolicy().sha256,ReviewPolicy(horizons_minutes=(1,3)).sha256)


class JournalOHLCReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases={name:run_case(name) for name in ('persistent_trend','opposing_choch','tie','blocked_interval','incomplete','ambiguous','neutral_range')}
    def test_original_assessment_records_preserve_adaptive_reports_verbatim(self):
        j,origin=self.cases['persistent_trend'];a,b,_=journal_fixture()
        expected=list(replay_adaptive('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7))
        self.assertEqual([r['adaptive_report'] for r in j['assessments']],expected)
        frozen=next(r for r in j['assessments'] if r['timestamp_utc']==origin.isoformat())
        self.assertEqual(frozen['adaptive_report']['regime']['directional'],'TREND_UP')
        self.assertTrue(frozen['reference_envelope']['evidence_ids'])
    def test_persisting_trend_supported_at_completed_horizon_without_trade_metrics(self):
        j,origin=self.cases['persistent_trend'];review=latest_review(j,origin)
        self.assertEqual(review['status'],'SUPPORTED');self.assertTrue(review['horizon_complete'])
        self.assertEqual(review['first_observed_boundary_event']['kind'],'UPPER')
        self.assertEqual({o['scenario']:o['status'] for o in review['scenario_outcomes']},
                         {'BULLISH':'SUPPORTED','BEARISH':'CONTRADICTED','NEUTRAL':'CONTRADICTED'})
        self.assertNotIn('profit',json.dumps(review));self.assertFalse(review['execution_allowed'])
    def test_opposing_choch_changes_assessment_and_contradicts_frozen_bullish_scenario(self):
        j,origin=self.cases['opposing_choch'];changes=[r for r in j['assessment_revisions'] if r['timestamp_utc']>origin.isoformat()]
        change=next(r for r in changes if 'FRESH_OPPOSING_M1_CHOCH' in r['reason_codes'])
        self.assertEqual(change['changes']['regime'],{'before':'TREND_UP','after':'TRANSITION'})
        self.assertTrue(change['new_evidence_ids']);self.assertTrue(change['scenario_evidence_deltas'])
        self.assertEqual(latest_review(j,origin)['status'],'CONTRADICTED')
        self.assertEqual(latest_review(j,origin)['first_observed_boundary_event']['kind'],'LOWER')
    def test_tie_preserves_both_leaders_and_has_no_retrospective_winner(self):
        j,origin=self.cases['tie'];r=latest_review(j,origin)
        self.assertEqual(r['status'],'UNRESOLVED');self.assertIn('ORIGINAL_SCENARIO_TIE',r['reason_codes'])
        members={o['scenario']:o['status'] for o in r['scenario_outcomes'] if o['was_original_leader']}
        self.assertEqual(members,{'BULLISH':'SUPPORTED','BEARISH':'CONTRADICTED'})
        self.assertGreater(j['summary']['tied_assessments'],0)
    def test_blocked_interval_unresolved_even_if_a_boundary_breach_was_seen(self):
        j,origin=self.cases['blocked_interval'];r=latest_review(j,origin)
        self.assertEqual(r['status'],'UNRESOLVED');self.assertIn('REVIEW_INTERVAL_BLOCKED',r['reason_codes'])
        self.assertIn('REVIEW_M1_COVERAGE_INCOMPLETE',r['reason_codes'])
    def test_incomplete_horizon_unresolved_never_extrapolated(self):
        j,origin=self.cases['incomplete'];r=latest_review(j,origin)
        self.assertFalse(r['horizon_complete']);self.assertEqual(r['status'],'UNRESOLVED')
        self.assertIn('HORIZON_INCOMPLETE',r['reason_codes'])
    def test_both_boundaries_in_first_breach_bar_are_ohlc_order_ambiguous(self):
        j,origin=self.cases['ambiguous'];r=latest_review(j,origin)
        self.assertEqual(r['status'],'UNRESOLVED');self.assertIn('OHLC_EVENT_ORDER_AMBIGUOUS',r['reason_codes'])
        self.assertTrue(all(o['status']=='UNRESOLVED' for o in r['scenario_outcomes']))
    def test_neutral_scenario_supported_only_when_original_envelope_holds(self):
        j,origin=self.cases['neutral_range'];r=latest_review(j,origin)
        self.assertEqual(r['status'],'SUPPORTED');self.assertIsNone(r['first_observed_boundary_event'])
        self.assertEqual(next(o['status'] for o in r['scenario_outcomes'] if o['scenario']=='NEUTRAL'),'SUPPORTED')
    def test_completed_reviews_are_immutable_and_later_prices_outside_horizon_excluded(self):
        j,origin=self.cases['persistent_trend'];at=origin+timedelta(minutes=5)
        prefix=journal_prefix(j,at);first=latest_review(prefix,origin)
        self.assertEqual(first,latest_review(j,origin))
        observations={o['observation_id']:o for o in j['observations']}
        self.assertTrue(all(datetime.fromisoformat(observations[oid]['closed_at_utc'])<=at for oid in first['observation_ids']))
    def test_first_strict_breach_is_not_changed_by_later_reversal_or_equal_touches(self):
        a,b,origin=journal_fixture('opposing_choch');a[21]['high']=118.5
        known_first=replay_reasoning_journal('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7)
        self.assertEqual(latest_review(known_first,origin)['status'],'SUPPORTED')
        self.assertEqual(latest_review(known_first,origin)['first_observed_boundary_event']['kind'],'UPPER')
        a,b,origin=journal_fixture('persistent_trend')
        for c in a[21:]:c.update(open=112,high=116.5,low=104.5,close=112)
        touches=replay_reasoning_journal('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7)
        r=latest_review(touches,origin);self.assertIsNone(r['first_observed_boundary_event'])
        self.assertEqual(r['status'],'UNRESOLVED');self.assertIn('NO_DIRECTIONAL_BREACH',r['reason_codes'])

    def test_summary_has_explicit_denominators_without_counting_review_versions_twice(self):
        for j,origin in self.cases.values():
            n=len(j['assessments']);self.assertEqual(j['summary']['transitions_denominator'],n-1)
            self.assertEqual(j['summary']['latest_assessment_horizon_pairs'],2*n)
            self.assertGreater(j['summary']['outcome_record_versions'],2*n)
            for h in j['summary']['horizons']:
                self.assertEqual(h['assessment_review_denominator'],n)
                self.assertEqual(sum(h['assessment_outcomes'].values()),n)
                self.assertEqual(h['complete_horizons']+h['incomplete_horizons'],n)
                self.assertEqual(sum(h['original_status_denominators'].values()),n)
                self.assertEqual(h['unique_leader_denominator']+h['tied_leader_denominator']+h['no_leader_denominator'],n)
                for s in h['scenario_reviews']:
                    self.assertEqual(s['all_assessment_denominator'],n)
                    self.assertEqual(sum(s['all_assessment_outcomes'].values()),n)
                    self.assertEqual(sum(s['leader_membership_outcomes'].values()),s['leader_membership_denominator'])
    def test_repeatability_common_cutoff_prefix_equivalence_and_future_append(self):
        for name in ('persistent_trend','opposing_choch','tie','blocked_interval'):
            j,origin=self.cases[name];a,b,_=journal_fixture(name)
            repeated,_=run_case(name);self.assertEqual(j,repeated)
            cutoff=origin+timedelta(minutes=2)
            pa=[r for r in a if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=1)<=cutoff]
            pb=[r for r in b if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=5)<=cutoff]
            prefix=replay_reasoning_journal('SYNTHETIC_XAUUSD',pa,pb,config=CONFIG,intelligence_config=P7)
            self.assertEqual(prefix,journal_prefix(j,cutoff))
            before=deepcopy(prefix['assessments'])
            self.assertEqual(before,j['assessments'][:len(before)])
            self.assertGreater(len(j['outcome_reviews']),len(prefix['outcome_reviews']))
            self.assertEqual(prefix,replay_reasoning_journal('SYNTHETIC_XAUUSD',a,b,as_of=cutoff,config=CONFIG,intelligence_config=P7))
    def test_unknown_and_blocked_original_assessments_never_get_graded_as_supported(self):
        j,_=self.cases['persistent_trend'];originals={a['assessment_id']:a['adaptive_report'] for a in j['assessments']}
        for r in j['outcome_reviews']:
            status=originals[r['assessment_id']]['status']
            if status in ('UNKNOWN','BLOCKED'):
                self.assertEqual(r['status'],'UNRESOLVED')
                self.assertIn('ORIGINAL_ASSESSMENT_'+status,r['reason_codes'])
                self.assertTrue(all(o['status']=='UNRESOLVED' for o in r['scenario_outcomes']))
    def test_appended_future_candles_add_reviews_without_changing_any_old_record(self):
        j,origin=self.cases['persistent_trend'];a,b,_=journal_fixture()
        cutoff=datetime.fromisoformat(a[-1]['timestamp'])+timedelta(minutes=1)
        a.append(dict(timestamp=cutoff.isoformat(),open=125,high=999,low=1,close=998))
        extended=replay_reasoning_journal('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7)
        self.assertEqual(j,journal_prefix(extended,cutoff))
        self.assertEqual(j['assessments'],extended['assessments'][:len(j['assessments'])])
        self.assertEqual(j['outcome_reviews'],extended['outcome_reviews'][:len(j['outcome_reviews'])])
        self.assertGreater(len(extended['outcome_reviews']),len(j['outcome_reviews']))

    def test_published_synthetic_audit_matches_actual_journals_and_worked_reviews(self):
        audit=json.loads(Path('docs/research_audits/market-reasoning-journal-synthetic-v1.json').read_text())
        for name,(journal,origin) in self.cases.items():
            case=next(c for c in audit['cases'] if c['case']==name)
            self.assertEqual(case['journal_sha256'],journal['sha256'])
            self.assertEqual(case['summary'],journal['summary'])
            self.assertEqual(case['worked_example']['review_status'],latest_review(journal,origin)['status'])
            self.assertEqual(case['software_comparisons']['full_hashes'],[journal['sha256']]*2)
            self.assertEqual(case['software_comparisons']['prefix_equivalence'],'PASS')
        self.assertEqual(audit['historical_validation'],'PENDING');self.assertIsNone(audit['historical_metrics'])
        self.assertEqual(audit['historical_comparisons'],'NOT_RUN')

    def test_serialized_journal_rebuild_validation_rejects_tampering(self):
        j,_=self.cases['persistent_trend'];raw=json.loads(json.dumps(j));self.assertTrue(validate_reasoning_journal(raw))
        for defect in ('assessment','review','summary','policy','safety'):
            bad=deepcopy(raw)
            if defect=='assessment':bad['assessments'][-1]['adaptive_report']['assessment']['top_scenarios']=['NEUTRAL']
            elif defect=='review':bad['outcome_reviews'][-1]['status']='SUPPORTED'
            elif defect=='summary':bad['summary']['material_assessment_changes']+=1
            elif defect=='policy':bad['review_policy']['version']=True
            else:bad['execution_allowed']=True
            bad['sha256']=digest({k:v for k,v in bad.items() if k!='sha256'})
            with self.subTest(defect=defect),self.assertRaises(ValueError):validate_reasoning_journal(bad)


class JournalLedgerAndPersistenceTests(unittest.TestCase):
    def reports(self):
        a,b,origin=journal_fixture()
        return [adaptive_at('SYNTHETIC_XAUUSD',a,b,origin+timedelta(minutes=i),config=CONFIG,intelligence_config=P7) for i in range(3)]
    def test_recorded_assessments_are_detached_and_clock_or_config_changes_rejected(self):
        first,second,_=self.reports();ledger=MarketReasoningJournal('SYNTHETIC_XAUUSD')
        returned=ledger.record(first);before=ledger.to_dict();returned['adaptive_report']['assessment'].clear()
        self.assertEqual(before,ledger.to_dict())
        with self.assertRaises(ValueError):ledger.record(first)
        bad=deepcopy(second);bad['configuration_hashes']['context']='0'*64
        bad['sha256']=digest({k:v for k,v in bad.items() if k!='sha256'})
        with self.assertRaises(ValueError):ledger.record(bad)
        self.assertEqual(before,ledger.to_dict())
    def test_changed_previously_observed_prices_are_rejected_transactionally(self):
        first,second,_=self.reports();ledger=MarketReasoningJournal('SYNTHETIC_XAUUSD');ledger.record(first);before=ledger.to_dict()
        key=next(k for k,c in first['observed_facts']['candles'].items() if c['timeframe']=='M1')
        second['observed_facts']['candles'][key]['ohlc']['close']+=.1
        second['interpretations']['sources'][key]['ohlc']['close']+=.1
        second['sha256']=digest({k:v for k,v in second.items() if k!='sha256'})
        with self.assertRaises(ValueError):ledger.record(second)
        self.assertEqual(before,ledger.to_dict())
    def test_future_or_inconsistent_observed_facts_cannot_be_recorded(self):
        first,second,_=self.reports();ledger=MarketReasoningJournal('SYNTHETIC_XAUUSD');ledger.record(first);before=ledger.to_dict()
        key=next(iter(second['observed_facts']['candles']))
        second['observed_facts']['candles'][key]['available_at']='2099-01-01T00:00:00Z'
        second['sha256']=digest({k:v for k,v in second.items() if k!='sha256'})
        with self.assertRaises(ValueError):ledger.record(second)
        self.assertEqual(before,ledger.to_dict())

    def test_later_observations_first_seen_and_review_times_are_causal(self):
        j,origin=run_case('persistent_trend');observed={o['observation_id']:o for o in j['observations']}
        assessments={a['assessment_id']:a for a in j['assessments']}
        for r in j['outcome_reviews']:
            self.assertEqual(r['assessment_sha256'],assessments[r['assessment_id']]['adaptive_report']['sha256'])
            self.assertEqual(r['original_configuration_hashes'],assessments[r['assessment_id']]['adaptive_report']['configuration_hashes'])
            for oid in r['observation_ids']:
                self.assertLessEqual(observed[oid]['first_seen_at_utc'],r['reviewed_at_utc'])
                self.assertLessEqual(observed[oid]['closed_at_utc'],r['due_at_utc'])
                self.assertGreater(observed[oid]['closed_at_utc'],r['window_start_utc'])
    def test_late_backfill_does_not_rewrite_completed_review_or_claim_earlier_availability(self):
        a,b,origin=journal_fixture('blocked_interval');ledger=MarketReasoningJournal('SYNTHETIC_XAUUSD')
        for r in replay_adaptive('SYNTHETIC_XAUUSD',a,b,config=CONFIG,intelligence_config=P7):ledger.record(r)
        before=ledger.to_dict();finished=latest_review(before,origin,5)
        fixed_a,fixed_b,_=journal_fixture('persistent_trend')
        now=datetime.fromisoformat(fixed_a[-1]['timestamp'])+timedelta(minutes=2)
        fixed_a.append(dict(timestamp=(now-timedelta(minutes=1)).isoformat(),open=126,high=127,low=125,close=126))
        ledger.record(adaptive_at('SYNTHETIC_XAUUSD',fixed_a,fixed_b,now,config=CONFIG,intelligence_config=P7))
        after=ledger.to_dict();self.assertEqual(finished,latest_review(after,origin,5))
        pending=latest_review(after,origin,15)
        self.assertIn('REVIEW_OBSERVATIONS_ARRIVED_LATE',pending['reason_codes'])
        self.assertTrue(pending['late_observation_ids']);self.assertEqual(pending['status'],'UNRESOLVED')

    def test_atomic_private_writer_roundtrip_and_overwrite_rejection(self):
        journal,_=run_case('incomplete',policy=ReviewPolicy(horizons_minutes=(1,3)))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'private journal.json';write_reasoning_journal(path,journal)
            raw=json.loads(path.read_text());validate_reasoning_journal(raw)
            self.assertEqual(digest(raw),digest(journal));before=path.read_bytes()
            with self.assertRaises(FileExistsError):write_reasoning_journal(path,journal)
            self.assertEqual(before,path.read_bytes())
    def test_atomic_publication_failure_cannot_leave_misleading_success(self):
        journal,_=run_case('incomplete',policy=ReviewPolicy(horizons_minutes=(1,)))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.json'
            with patch('os.replace',side_effect=OSError('SYNTHETIC_FAILURE')):
                with self.assertRaises(OSError):write_reasoning_journal(path,journal)
            self.assertEqual(json.loads(path.read_text()),{'publication_status':'INCOMPLETE'})
            self.assertFalse(list(Path(folder).glob('.iat-journal-*')))
    def test_existing_logs_and_manifest_accounting_remain_unchanged(self):
        from test_strategy_dataset_replay import scoped_fixture
        from iat.strategy_dataset_replay import run_strategy_manifest
        from iat.replay_dataset import load_dataset
        from iat.intelligence.decision_log import DecisionLog
        with tempfile.TemporaryDirectory() as folder:
            path=scoped_fixture(Path(folder),total_minutes=35)
            before=run_strategy_manifest(path,config=CONFIG,intelligence_config=P7);data=load_dataset(path)
            journal=replay_reasoning_journal('XAUUSD',data.rows['M1'],data.rows['M5'],config=CONFIG,intelligence_config=P7)
            self.assertEqual(before,run_strategy_manifest(path,config=CONFIG,intelligence_config=P7))
            self.assertEqual(before['strategy_replay_log']['log_version'],1)
            self.assertEqual(DecisionLog(1,{},()).to_dict()['log_version'],1)
            self.assertEqual(journal['historical_validation'],'PENDING');self.assertEqual(journal['historical_comparisons'],'NOT_RUN')
