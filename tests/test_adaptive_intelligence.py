"""Labeled SYNTHETIC OHLC and observation contracts; no broker/source validation."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from iat.intelligence.adaptive import adaptive_at,assess_adaptive,replay_adaptive,validate_adaptive_report
from iat.intelligence.adaptive_models import AdaptiveConfig,COMPATIBILITY
from iat.intelligence.context import analyze_context
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.strategy_replay import digest
from test_context_components import CONFIG
from test_context_engine import P7,two_frames
from test_intelligence_patterns import rows,START
from test_research_strategies import synthetic_ohlc_fixture,observation_fixture


def adaptive_contract(direction='BULLISH',opposing=False):
    """Explicit SYNTHETIC composed strategy observations, with real computed pivots."""
    a,b,at=synthetic_ohlc_fixture(mirror=direction=='BEARISH')
    base=analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
    mock=observation_fixture(direction,opposing)
    structures={e.timeframe:e for e in base.evidence if e.category=='STRUCTURE'}
    es=[]
    for e in mock.evidence:
        if e.category=='STRUCTURE':e=structures[e.timeframe]
        es.append(e)
    interpretations=deepcopy(base.interpretations)
    for name in ('liquidity_pools','liquidity_events'):
        interpretations['frames']['M1'][name]=mock.interpretations['frames']['M1'][name]
    for e in interpretations['frames']['M1']['liquidity_events']:
        interpretations['source_registry'][e.id]={'kind':'LIQUIDITY_EVENT','timeframe':'M1',
            'observed_at':e.occurred_at,'available_at':e.available_at,'references':list(e.evidence)}
    return replace(base,evidence=tuple(es),interpretations=interpretations)


def actual_range():
    a=rows([100,104,100,96]*6);b=rows([100,104,100,96]*6,'M5')
    for c in b:c['timestamp']=(datetime.fromisoformat(c['timestamp'])-timedelta(minutes=100)).isoformat()
    return a,b,START+timedelta(minutes=24)



def synthetic_cases():
    """SYNTHETIC only; shared deterministic audit/integration fixture recipes."""
    cases={}
    for mirror,name in ((False,'trend_up'),(True,'trend_down')):
        cases[name]=(*synthetic_ohlc_fixture(mirror=mirror),'CAUSAL_QUERY')
    cases['range']=(*actual_range(),'CAUSAL_QUERY')
    a,b,at=two_frames();cases['normal_trend_missing_confirmation']=(a,b,at,'CAUSAL_QUERY')
    a,b,at=synthetic_ohlc_fixture();a[-1].update(open=100.02,high=100.13,low=100.019,close=100.12)
    cases['high_volatility_trend']=(a,b,at,'CAUSAL_QUERY')
    cases['fresh_opposing_choch']=(*two_frames(choch=True),'CAUSAL_QUERY')
    for mirror,name in ((False,'sweep_bearish'),(True,'sweep_bullish')):
        cases[name]=(*synthetic_ohlc_fixture(reversal=True,mirror=mirror),'CAUSAL_QUERY')
    a,b,at=two_frames()
    for c in b:
        o,h,l,cl=(c[k] for k in ('open','high','low','close'));c.update(open=200-o,high=200-l,low=200-h,close=200-cl)
    cases['opposing_frame_scenario_tie']=(a,b,at,'CAUSAL_QUERY')
    a,b,at=synthetic_ohlc_fixture();cases['insufficient_history']=(a[-3:],b[-3:],at,'CAUSAL_QUERY')
    cases['blocked_gap']=(a[:5]+a[6:],b,at,'CAUSAL_QUERY')
    a,b,at=synthetic_ohlc_fixture()
    b.append(dict(timestamp=(datetime.fromisoformat(b[-1]['timestamp'])+timedelta(minutes=5)).isoformat(),open=100,high=999,low=1,close=998))
    cases['direct_unfinished_m5']=(a,b,at,'DIRECT_CONTEXT_REJECTS_UNCLOSED')
    return cases

def candidate(report,strategy,direction):
    return next(c for c in report['assessment']['candidate_assessments'] if c['strategy_id']==strategy and c['direction']==direction)


class AdaptivePolicyTests(unittest.TestCase):
    def test_versioned_policy_and_fixed_inherited_thresholds(self):
        self.assertEqual(AdaptiveConfig().digest,AdaptiveConfig().digest)
        for values in ({'version':True},{'version':2},{'ranking_version':0},{'compatibility_version':'1'}):
            with self.subTest(values=values),self.assertRaises(ValueError):AdaptiveConfig(**values)
        self.assertEqual(ContextConfig().digest,'d8bda7da1af47cc1f1f349682b71ca75f39bef89b7fb5d5873bc0bba5510d424')
        self.assertEqual(IntelligenceConfig().digest,'0b1db8f78abc3801b23a2aec62ee6057a1b0b711a8244405bc5f77ff582653ff')
    def test_multiple_qualifying_candidates_tie_without_arbitrary_strategy_priority(self):
        for direction in ('BULLISH','BEARISH'):
            r=assess_adaptive(adaptive_contract(direction))
            self.assertEqual(r['status'],'READY')
            self.assertEqual(len(r['assessment']['top_candidates']),2)
            for c in r['assessment']['candidate_assessments']:
                if c['direction']==direction:
                    self.assertEqual(c['rule_status'],'QUALIFIES');self.assertEqual(c['rank'],1)
                    self.assertEqual(c['assessment_status'],'CANDIDATE')
            self.assertIn('MULTIPLE_TOP_CANDIDATES',r['uncertainty'])
    def test_fresh_opposing_choch_overrides_matching_alignment_and_invalidates_rules(self):
        r=assess_adaptive(adaptive_contract(opposing=True))
        self.assertEqual(r['regime']['directional'],'TRANSITION')
        self.assertEqual(r['interpretations']['existing_context']['phase7_alignment'],'BULLISH_ALIGNMENT')
        self.assertTrue(any(c['reason_code']=='FRESH_OPPOSING_M1_CHOCH' for c in r['conflicts']))
        for strategy in ('M5_TREND_M1_CONFIRMATION','SWEEP_M1_STRUCTURE_CHANGE'):
            self.assertEqual(candidate(r,strategy,'BULLISH')['rule_status'],'INVALIDATED')
    def test_compatibility_never_rescues_failed_predicates(self):
        a,b,at=actual_range();r=adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(r['regime']['directional'],'RANGE')
        self.assertFalse(r['assessment']['top_candidates'])
        for d in ('BULLISH','BEARISH'):
            self.assertEqual(candidate(r,'SWEEP_M1_STRUCTURE_CHANGE',d)['compatibility'],'SUPPORTED')
            self.assertEqual(candidate(r,'SWEEP_M1_STRUCTURE_CHANGE',d)['assessment_status'],'RULES_FAILED')
    def test_unknown_structure_labels_without_confirmed_pivot_evidence_cannot_rank(self):
        r=adaptive_contract();es=tuple(replace(e,references=()) if e.category=='STRUCTURE' else e for e in r.evidence)
        result=assess_adaptive(replace(r,evidence=es))
        self.assertEqual(result['status'],'UNKNOWN');self.assertEqual(result['regime']['directional'],'UNKNOWN')
        self.assertTrue(all(s['heuristic_score'] is None for s in result['assessment']['scenarios']))
    def test_scenario_tie_keeps_all_leaders_and_explains_support_and_opposition(self):
        r=adaptive_contract()
        # Only equal-weight, opposing confirmed structures: exact, transparent vote tie.
        es=[e for e in r.evidence if e.category=='STRUCTURE']
        es=[replace(e,direction='BEARISH',details={'classification':'BEARISH'}) if e.timeframe=='M1' else e for e in es]
        r=replace(r,evidence=tuple(es),context=dict(r.context,m1_structure='BEARISH'))
        result=assess_adaptive(r)
        self.assertEqual(result['assessment']['top_scenarios'],['BULLISH','BEARISH'])
        self.assertIn('SCENARIO_SCORE_TIE',result['uncertainty'])
        for s in result['assessment']['scenarios']:
            self.assertEqual(s['heuristic_score'],s['support_score']-s['opposition_score'])
            self.assertTrue(s['assumptions']);self.assertTrue(s['invalidation_conditions']);self.assertTrue(s['assessment_would_change_with'])
    def test_rule_qualification_and_regime_unsuitability_are_separate(self):
        r=adaptive_contract();es=[]
        for e in r.evidence:
            if e.category=='STRUCTURE':e=replace(e,direction='RANGING',details={'classification':'RANGING'})
            # A same-direction CHoCH with M5 RANGING intentionally establishes TRANSITION.
            if e.category!='TRANSITION':es.append(e)
        r=replace(r,evidence=tuple(es),context=dict(r.context,m1_structure='RANGING',m5_structure='RANGING'))
        result=assess_adaptive(r)
        self.assertEqual(result['regime']['directional'],'RANGE')
        self.assertEqual(candidate(result,'M5_TREND_M1_CONFIRMATION','BULLISH')['compatibility'],'INCOMPATIBLE')
    def test_volatility_is_orthogonal_and_missing_frame_is_explicit(self):
        r=adaptive_contract();frames=deepcopy(r.interpretations)
        frames['frames']['M1']['volatility'].update(regime='HIGH_VOLATILITY',status='AVAILABLE',relative_volatility=3)
        frames['frames']['M5'].pop('volatility')
        result=assess_adaptive(replace(r,interpretations=frames))
        self.assertEqual(result['regime']['directional'],'TREND_UP')
        self.assertEqual(result['volatility']['overall'],'HIGH')
        self.assertIn('M5_VOLATILITY_EVIDENCE_INCOMPLETE',result['uncertainty'])
        self.assertEqual(len(result['assessment']['top_candidates']),2)
    def test_future_or_conflicting_evidence_is_blocked_and_quarantined(self):
        r=adaptive_contract();e=r.evidence[0]
        for es in ((replace(e,available_at='2099-01-01T00:00:00Z'),)+r.evidence[1:],r.evidence+(replace(e,direction='NEUTRAL'),)):
            result=assess_adaptive(replace(r,evidence=es))
            self.assertEqual(result['status'],'BLOCKED');self.assertFalse(result['observed_facts'])
            self.assertFalse(result['assessment']['top_candidates'])
    def test_config_hash_mismatch_or_live_provenance_cannot_certify_inputs(self):
        r=adaptive_contract()
        for changed in (replace(r,configuration_sha256='0'*64),replace(r,provenance='VALIDATED_LIVE')):
            result=assess_adaptive(changed);self.assertEqual(result['status'],'BLOCKED')
            self.assertEqual(result['historical_validation'],'PENDING')
            self.assertEqual(result['historical_decision_log_comparisons'],'NOT_RUN')
    def test_no_input_mutation_and_order_independent_votes(self):
        r=adaptive_contract();before=deepcopy(r)
        a=assess_adaptive(r);b=assess_adaptive(replace(r,evidence=tuple(reversed(r.evidence))))
        self.assertEqual(a,b);self.assertEqual(r,before)
    def test_serialized_report_validation_rejects_unsafe_and_future_records(self):
        r=json.loads(json.dumps(assess_adaptive(adaptive_contract())))
        self.assertTrue(validate_adaptive_report(r))
        for key,value in (('report_version',True),('execution_allowed',True),('historical_validation','VALIDATED')):
            changed=deepcopy(r);changed[key]=value;changed['sha256']=digest({k:v for k,v in changed.items() if k!='sha256'})
            with self.assertRaises(ValueError):validate_adaptive_report(changed)
        for version in (True,2):
            bad=deepcopy(r);bad['policy_versions']['compatibility_version']=version
            bad['sha256']=digest({k:v for k,v in bad.items() if k!='sha256'})
            with self.assertRaises(ValueError):validate_adaptive_report(bad)
        r['interpretations']['evidence'][0]['available_at']='2099-01-01T00:00:00Z'
        r['sha256']=digest({k:v for k,v in r.items() if k!='sha256'})
        with self.assertRaises(ValueError):validate_adaptive_report(r)


class AdaptiveOHLCIntegrationTests(unittest.TestCase):
    def test_actual_causal_up_and_down_trends_and_candidates(self):
        for mirror in (False,True):
            a,b,at=synthetic_ohlc_fixture(mirror=mirror)
            r=adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
            self.assertEqual(r['regime']['directional'],'TREND_DOWN' if mirror else 'TREND_UP')
            self.assertEqual(len(r['assessment']['top_candidates']),1)
            self.assertEqual(r['assessment']['top_candidates'][0]['strategy_id'],'M5_TREND_M1_CONFIRMATION')
    def test_actual_range_is_directionally_separate_from_neutral_scenario_and_abstention(self):
        a,b,at=actual_range();r=adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(r['regime']['directional'],'RANGE')
        self.assertEqual(r['assessment']['top_scenarios'],['NEUTRAL']);self.assertFalse(r['assessment']['top_candidates'])
    def test_actual_high_volatility_trend_coexists(self):
        a,b,at=synthetic_ohlc_fixture()
        a[-1].update(open=100.02,high=100.13,low=100.019,close=100.12)
        r=adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(r['regime']['directional'],'TREND_UP')
        self.assertEqual(r['volatility']['overall'],'HIGH')
        self.assertIn('HIGH_VOLATILITY_RESEARCH_CAUTION',r['uncertainty'])
    def test_actual_regime_change_is_not_hidden_by_phase7_alignment(self):
        a,b,at=two_frames(choch=True)
        before=adaptive_at('SYNTHETIC_XAUUSD',a,b,at-timedelta(minutes=2),config=CONFIG,intelligence_config=P7)
        after=adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(before['regime']['directional'],'TREND_UP')
        self.assertEqual(after['regime']['directional'],'TRANSITION')
    def test_actual_sweep_reversal_candidates_in_transition_both_directions(self):
        for mirror in (False,True):
            a,b,at=synthetic_ohlc_fixture(reversal=True,mirror=mirror)
            r=adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
            self.assertEqual(r['regime']['directional'],'TRANSITION')
            direction='BULLISH' if mirror else 'BEARISH'
            self.assertEqual(candidate(r,'SWEEP_M1_STRUCTURE_CHANGE',direction)['assessment_status'],'CANDIDATE')
    def test_unfinished_future_m5_is_excluded_and_direct_unclosed_inputs_block(self):
        a,b,at=synthetic_ohlc_fixture();original=adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        b.append(dict(timestamp=(datetime.fromisoformat(b[-1]['timestamp'])+timedelta(minutes=5)).isoformat(),open=100,high=999,low=1,close=998))
        self.assertEqual(original,adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7))
        direct=analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(assess_adaptive(direct)['status'],'BLOCKED')
    def test_blocked_gap_insufficient_history_and_exness_calendar(self):
        a,b,at=synthetic_ohlc_fixture()
        gap=adaptive_at('SYNTHETIC_XAUUSD',a[:5]+a[6:],b,at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(gap['status'],'BLOCKED')
        short=adaptive_at('SYNTHETIC_XAUUSD',a[-3:],b[-3:],at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(short['status'],'UNKNOWN')
        from iat.session_config import load_session_config
        calendar=load_session_config('config/profiles/exness-xauusd-v2.candidate.json')
        blocked=adaptive_at('XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7,calendar=calendar)
        self.assertEqual(blocked['status'],'BLOCKED');self.assertEqual(blocked['exness'],'BLOCKED')
    def test_repeatability_prefix_equivalence_and_future_append_invariance(self):
        for reversal in (False,True):
            a,b,at=synthetic_ohlc_fixture(reversal=reversal)
            kwargs={'config':CONFIG,'intelligence_config':P7}
            full=list(replay_adaptive('SYNTHETIC_XAUUSD',a,b,**kwargs))
            self.assertEqual(full,list(replay_adaptive('SYNTHETIC_XAUUSD',a,b,**kwargs)))
            cutoff=at-timedelta(minutes=1)
            pa=[r for r in a if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=1)<=cutoff]
            pb=[r for r in b if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=5)<=cutoff]
            prefix=list(replay_adaptive('SYNTHETIC_XAUUSD',pa,pb,**kwargs))
            self.assertEqual(prefix,full[:len(prefix)])
            a.append(dict(timestamp=at.isoformat(),open=100,high=999,low=1,close=998))
            b.append(dict(timestamp=(datetime.fromisoformat(b[-1]['timestamp'])+timedelta(minutes=5)).isoformat(),open=100,high=999,low=1,close=998))
            self.assertEqual(prefix,list(replay_adaptive('SYNTHETIC_XAUUSD',a,b,as_of=cutoff,**kwargs)))
    def test_actual_opposing_frames_produce_scenario_tie_and_no_candidates(self):
        a,b,at=two_frames()
        for c in b:
            o,h,l,cl=(c[k] for k in ('open','high','low','close'))
            c.update(open=200-o,high=200-l,low=200-h,close=200-cl)
        r=adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(r['regime']['directional'],'TRANSITION')
        self.assertEqual(r['assessment']['top_scenarios'],['BULLISH','BEARISH'])
        self.assertFalse(r['assessment']['top_candidates'])
    def test_manifest_replay_and_window_accounting_are_unchanged(self):
        from test_strategy_dataset_replay import scoped_fixture
        from iat.strategy_dataset_replay import run_strategy_manifest
        from iat.replay_dataset import load_dataset
        from iat.intelligence.decision_log import DecisionLog
        with tempfile.TemporaryDirectory() as folder:
            path=scoped_fixture(Path(folder),total_minutes=35)
            before=run_strategy_manifest(path,config=CONFIG,intelligence_config=P7)
            data=load_dataset(path)
            adaptive_at('XAUUSD',data.rows['M1'],data.rows['M5'],datetime.fromisoformat(data.metadata['utc_range']['end']),
                        config=CONFIG,intelligence_config=P7,provenance=data.provenance)
            after=run_strategy_manifest(path,config=CONFIG,intelligence_config=P7)
            self.assertEqual(before,after)
            self.assertEqual(after['strategy_replay_log']['log_version'],1)
            self.assertEqual(DecisionLog(1,{},()).to_dict(),{'log_version':1,'configuration_hashes':{},'entries':()})
    def test_unknown_m1_m5_structure_and_blocked_reports_have_no_ranked_scenarios(self):
        a,b,at=synthetic_ohlc_fixture()
        for one,five in ((a[-3:],b[-3:]),(a[:5]+a[6:],b)):
            r=adaptive_at('SYNTHETIC_XAUUSD',one,five,at,config=CONFIG,intelligence_config=P7)
            self.assertIn(r['status'],('UNKNOWN','BLOCKED'))
            self.assertEqual(len(r['assessment']['scenarios']),3)
            self.assertTrue(all(s['rank'] is None for s in r['assessment']['scenarios']))

    def test_malformed_history_selection_returns_explicit_blocked(self):
        a,b,at=synthetic_ohlc_fixture()
        for broken in ([dict(a[0],timestamp='not-a-timestamp')]+a[1:],[{}]+a[1:]):
            r=adaptive_at('SYNTHETIC_XAUUSD',broken,b,at,config=CONFIG,intelligence_config=P7)
            self.assertEqual(r['status'],'BLOCKED')
            self.assertIn('ADAPTIVE_HISTORY_SELECTION_FAILED',r['reason_codes'])
            self.assertFalse(r['observed_facts'])
    def test_invalid_request_configuration_is_not_silently_replaced(self):
        a,b,at=synthetic_ohlc_fixture()
        with self.assertRaises(ValueError):adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config={})
        with self.assertRaises(ValueError):adaptive_at('SYNTHETIC_XAUUSD',a,b,at,adaptive_config={})
        with self.assertRaises(ValueError):adaptive_at('SYNTHETIC_XAUUSD',a,b,at.replace(tzinfo=None))

    def test_published_synthetic_audit_matches_actual_reports(self):
        audit=json.loads(Path('docs/research_audits/adaptive-intelligence-synthetic-v1.json').read_text())
        for name,(a,b,at,mode) in synthetic_cases().items():
            if mode=='CAUSAL_QUERY':r=adaptive_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
            else:r=assess_adaptive(analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7))
            expected=next(c for c in audit['snapshot_cases'] if c['case']==name)
            self.assertEqual(expected['report_sha256'],r['sha256'])
            self.assertEqual(expected['regime'],r['regime']['directional'])
            self.assertEqual(expected['top_candidates'],r['assessment']['top_candidates'])
        self.assertEqual(audit['historical_validation'],'PENDING')
        self.assertEqual(audit['historical_decision_log_comparisons'],'NOT_RUN')
        self.assertIsNone(audit['historical_metrics'])

    def test_replay_backwards_or_duplicate_timestamps_rejected(self):
        a,b,at=synthetic_ohlc_fixture()
        with self.assertRaises(ValueError):list(replay_adaptive('SYNTHETIC_XAUUSD',a+[a[-1]],b,config=CONFIG,intelligence_config=P7))
