"""Labeled SYNTHETIC observation contracts and synthetic OHLC integration only.

Positive rule fixtures compose existing typed IAT outputs; they do not assert
that a broker produced these observations or that the rules have an edge.
"""
import copy
from dataclasses import replace
from datetime import datetime,timedelta
import json
import unittest
from iat.intelligence.context import analyze_context
from iat.intelligence.context_models import Evidence,LiquidityPool,LiquidityEvent
from iat.intelligence.models import IntelligenceConfig
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.strategy_registry import registry,Strategy
from iat.intelligence.strategies import evaluate_strategies,strategies_at
from test_context_engine import two_frames,P7
from test_context_components import CONFIG
from test_intelligence_patterns import rows


def observation_fixture(direction='BULLISH', opposing=False):
    """Explicit SYNTHETIC mock of the observation contract, not recognized prices."""
    a,b,at=two_frames()
    base=analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
    now=at.isoformat();previous=(at-timedelta(minutes=1)).isoformat()
    def evidence(id_,kind,tf='M1',details=None,d=direction,opened=previous):
        return Evidence('SYNTHETIC:'+id_,kind,tf,d,opened,now,(),('SYNTHETIC_CONTRACT',),details or {})
    es=[evidence('M1structure','STRUCTURE'),evidence('M5structure','STRUCTURE','M5'),
        evidence('candle','CANDLE',details={'name':'BULLISH_ENGULFING' if direction=='BULLISH' else 'BEARISH_ENGULFING'}),
        evidence('zone','SUPPORT_RESISTANCE',details={'status':'TESTED','kind':'SUPPORT' if direction=='BULLISH' else 'RESISTANCE'}),
        evidence('choch','TRANSITION',details={'fresh':True,'event_type':direction+'_CHOCH','confirmation_policy':'CLOSE'})]
    if opposing:
        opposite='BEARISH' if direction=='BULLISH' else 'BULLISH'
        es.append(evidence('opposing','TRANSITION',d=opposite,details={'fresh':True,'event_type':opposite+'_CHOCH','confirmation_policy':'CLOSE'}))
    pool=LiquidityPool('SYNTHETIC:pool','SWING_LOWS' if direction=='BULLISH' else 'SWING_HIGHS','M1',90 if direction=='BULLISH' else 120,
                       (at-timedelta(minutes=4)).isoformat(),(),1,('SYNTHETIC_CONTRACT',))
    sweep=LiquidityEvent('SYNTHETIC:sweep',pool.id,'CONFIRMED_SWEEP','M1',
                         (at-timedelta(minutes=3)).isoformat(),(at-timedelta(minutes=2)).isoformat(),pool.level,
                         'SYNTHETIC:sweep-candle',(),('SYNTHETIC_CONTRACT',))
    frames={'M1':{'liquidity_pools':(pool,),'liquidity_events':(sweep,)},'M5':{'liquidity_pools':(),'liquidity_events':()}}
    # Last close is between the synthetic bullish/bearish swept boundaries.
    sources={'SYNTHETIC:last':{'kind':'CANDLE','timeframe':'M1','available_at':now,'observed_at':previous,
                               'ohlc':{'open':100,'high':101,'low':99,'close':100}}}
    return replace(base,observed_facts={tf:{'data_as_of':now,'candle_count':100} for tf in ('M1','M5')},
                   interpretations={'frames':frames,'source_registry':sources},evidence=tuple(es),
                   context={'m1_structure':direction,'m5_structure':direction,'phase7_alignment':direction+'_ALIGNMENT','limitations':[]})



def synthetic_ohlc_fixture(reversal=False, mirror=False):
    """Procedural SYNTHETIC wave; all observations are computed by IAT itself."""
    a,b,at=two_frames(choch=reversal)
    if reversal:
        # Wick rejection above a confirmed high, then a later close through lows.
        a[-2].update(open=112,high=118.5,low=111.5,close=112)
        a[-1].update(open=112,high=112.1,low=93.9,close=94)
    for tf,cs in (('M1',a),('M5',b)):
        for c in cs:
            # Reflection gives mirrored cases; small synthetic units exercise the
            # existing fixed zone/proximity choices without changing thresholds.
            if mirror != (reversal and tf=='M5'):
                o,h,l,cl=(c[k] for k in ('open','high','low','close'))
                c.update(open=200-o,high=200-l,low=200-h,close=200-cl)
            for k in ('open','high','low','close'):c[k]=100+(c[k]-100)/100
    if not reversal:
        c=a[-1];close=c['close']
        if mirror:c.update(open=close+.03,high=close+.031,low=close-.001)
        else:c.update(open=close-.03,high=close+.001,low=close-.031)
    return a,b,at

def outcome(report,strategy='M5_TREND_M1_CONFIRMATION',direction='BULLISH'):
    return next(e for e in evaluate_strategies(report)['evaluations'] if e['strategy_id']==strategy and e['direction']==direction)


class RegistryTests(unittest.TestCase):
    def test_version_metadata_rules_and_experimental_status(self):
        r=registry();self.assertEqual(r['registry_version'],1);self.assertEqual(len(r['strategies']),2)
        for s in r['strategies']:
            self.assertEqual(s['validation_status'],'EXPERIMENTAL_SYNTHETIC_ONLY')
            self.assertEqual(s['source'],'ORIGINAL_IAT_RULE_COMPOSITION')
            self.assertEqual(s['rule_version'],'1.0.0')
            for k in ('author','summary','required_evidence','eligibility','invalidation','iat_choices'):self.assertTrue(s[k])
        for version in (True,0,2,'1'):
            with self.subTest(version=version),self.assertRaises(ValueError):registry(version)
    def test_registry_returns_detached_metadata_and_stable_hash(self):
        before=registry();changed=registry();changed['strategies'][0]['author']='changed'
        self.assertEqual(before,registry())
        self.assertEqual(len(before['sha256']),64)
    def test_registry_rejects_validation_claim_and_missing_rules(self):
        spec=registry()['strategies'][0]
        for update in ({'validation_status':'VALIDATED'},{'eligibility':()},{'author':''},{'rule_version':'2.0.0'}):
            with self.subTest(update=update),self.assertRaises(ValueError):Strategy(**dict(spec,**update))
    def test_confluence_threshold_defaults_remain_fixed(self):
        self.assertEqual(ContextConfig().digest,'d8bda7da1af47cc1f1f349682b71ca75f39bef89b7fb5d5873bc0bba5510d424')
        self.assertEqual(IntelligenceConfig().digest,'0b1db8f78abc3801b23a2aec62ee6057a1b0b711a8244405bc5f77ff582653ff')


class StrategyRulesTests(unittest.TestCase):
    def test_synthetic_qualifying_bullish_and_bearish_cases_are_independent(self):
        for direction in ('BULLISH','BEARISH'):
            report=observation_fixture(direction)
            for strategy in ('M5_TREND_M1_CONFIRMATION','SWEEP_M1_STRUCTURE_CHANGE'):
                with self.subTest(direction=direction,strategy=strategy):
                    result=outcome(report,strategy,direction)
                    self.assertEqual(result['status'],'QUALIFIES')
                    self.assertTrue(result['supporting_evidence']);self.assertFalse(result['contradictory_evidence'])
                    opposite='BEARISH' if direction=='BULLISH' else 'BULLISH'
                    self.assertEqual(outcome(report,strategy,opposite)['status'],'ABSTAINS')
    def test_qualifies_does_not_select_signal_or_certify_history(self):
        r=evaluate_strategies(observation_fixture())
        self.assertEqual(r['signal'],'WAIT');self.assertIs(r['execution_allowed'],False)
        self.assertEqual(r['historical_validation'],'PENDING')
        self.assertEqual(r['historical_decision_log_comparisons'],'NOT_RUN')
        self.assertEqual(r['exness'],'BLOCKED');json.dumps(r,allow_nan=False)
    def test_missing_current_candle_or_zone_abstains(self):
        r=observation_fixture()
        for category in ('CANDLE','SUPPORT_RESISTANCE'):
            changed=replace(r,evidence=tuple(e for e in r.evidence if e.category!=category))
            for result in evaluate_strategies(changed)['evaluations']:
                self.assertEqual(result['status'],'ABSTAINS')
    def test_m1_structure_agreement_required_for_continuation_only(self):
        r=observation_fixture();r=replace(r,context=dict(r.context,m1_structure='BEARISH'))
        self.assertIn('M1_STRUCTURE_NOT_CONFIRMED',outcome(r)['reason_codes'])
        self.assertEqual(outcome(r,'SWEEP_M1_STRUCTURE_CHANGE')['status'],'QUALIFIES')
    def test_reversal_does_not_require_m5_trend_agreement(self):
        r=observation_fixture();r=replace(r,context=dict(r.context,m5_structure='BEARISH'))
        self.assertEqual(outcome(r)['status'],'ABSTAINS')
        self.assertEqual(outcome(r,'SWEEP_M1_STRUCTURE_CHANGE')['status'],'QUALIFIES')
    def test_opposing_fresh_m1_choch_invalidates_despite_alignment_label(self):
        for direction in ('BULLISH','BEARISH'):
            r=observation_fixture(direction,opposing=True)
            self.assertEqual(r.context['phase7_alignment'],direction+'_ALIGNMENT')
            for strategy in ('M5_TREND_M1_CONFIRMATION','SWEEP_M1_STRUCTURE_CHANGE'):
                result=outcome(r,strategy,direction)
                self.assertEqual(result['status'],'INVALIDATED')
                self.assertIn('FRESH_OPPOSING_M1_CHOCH',result['reason_codes'])
                self.assertIn('SYNTHETIC:opposing',result['contradictory_evidence'])
    def test_sweep_requires_subsequent_close_confirmed_choch(self):
        for defect in ('missing','wick','same_candle'):
            r=observation_fixture();es=[]
            for e in r.evidence:
                if e.category=='TRANSITION':
                    if defect=='missing':continue
                    if defect=='wick':e=replace(e,details=dict(e.details,confirmation_policy='WICK'))
                    else:e=replace(e,observed_at=(datetime.fromisoformat(r.analysis_at)-timedelta(minutes=3)).isoformat())
                es.append(e)
            result=outcome(replace(r,evidence=tuple(es)),'SWEEP_M1_STRUCTURE_CHANGE')
            self.assertEqual(result['status'],'ABSTAINS')
            self.assertIn('POST_SWEEP_CLOSE_CONFIRMED_M1_CHOCH_REQUIRED',result['reason_codes'])
    def test_sweep_expiry_missing_pool_and_ambiguous_event_abstain(self):
        for defect in ('expired','pool','ambiguous'):
            r=copy.deepcopy(observation_fixture());frame=r.interpretations['frames']['M1'];s=frame['liquidity_events'][0]
            if defect=='expired':s=replace(s,available_at=(datetime.fromisoformat(r.analysis_at)-timedelta(minutes=6)).isoformat())
            elif defect=='pool':frame['liquidity_pools']=()
            else:s=replace(s,event_type='AMBIGUOUS_EVENT')
            frame['liquidity_events']=(s,)
            self.assertIn('RECENT_CONFIRMED_M1_SWEEP_REQUIRED',outcome(r,'SWEEP_M1_STRUCTURE_CHANGE')['reason_codes'])
    def test_later_loss_of_swept_level_invalidates_reversal_only(self):
        for direction in ('BULLISH','BEARISH'):
            r=copy.deepcopy(observation_fixture(direction))
            r.interpretations['source_registry']['SYNTHETIC:last']['ohlc']['close']=80 if direction=='BULLISH' else 130
            result=outcome(r,'SWEEP_M1_STRUCTURE_CHANGE',direction)
            self.assertEqual(result['status'],'INVALIDATED')
            self.assertIn('SWEPT_LEVEL_RECLAIM_LOST',result['reason_codes'])
            self.assertEqual(result['contradictory_evidence'],['SYNTHETIC:last'])
            self.assertEqual(outcome(r,direction=direction)['status'],'QUALIFIES')
    def test_blocked_data_and_insufficient_structure_abstain_before_rule_evaluation(self):
        r=observation_fixture(opposing=True)
        variants=(replace(r,data_quality={'valid':False}),replace(r,context=dict(r.context,limitations=['INSUFFICIENT_STRUCTURAL_CONTEXT'])))
        for changed in variants:
            for e in evaluate_strategies(changed)['evaluations']:self.assertEqual(e['status'],'ABSTAINS')
    def test_future_or_unresolved_evidence_cannot_qualify(self):
        r=observation_fixture();e=r.evidence[0]
        for changed in (replace(e,available_at='2099-01-01T00:00:00Z'),replace(e,references=('missing',))):
            report=replace(r,evidence=(changed,)+r.evidence[1:])
            self.assertIn('EVIDENCE_UNAVAILABLE_AT_TIMESTAMP',outcome(report)['reason_codes'])
    def test_live_provenance_is_rejected_and_input_is_not_mutated(self):
        r=observation_fixture();before=copy.deepcopy(r)
        self.assertEqual(evaluate_strategies(r),evaluate_strategies(r));self.assertEqual(r,before)
        with self.assertRaises(ValueError):evaluate_strategies(replace(r,provenance='VALIDATED_LIVE'))


class StrategyOHLCIntegrationTests(unittest.TestCase):
    def test_real_observation_pipeline_qualifies_both_strategies_in_both_directions(self):
        for reversal in (False,True):
            for mirror in (False,True):
                a,b,at=synthetic_ohlc_fixture(reversal,mirror)
                r=analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
                strategy='SWEEP_M1_STRUCTURE_CHANGE' if reversal else 'M5_TREND_M1_CONFIRMATION'
                direction=('BULLISH' if mirror else 'BEARISH') if reversal else ('BEARISH' if mirror else 'BULLISH')
                with self.subTest(reversal=reversal,mirror=mirror):
                    self.assertEqual(outcome(r,strategy,direction)['status'],'QUALIFIES')
                    self.assertTrue(any(e.category=='CANDLE' and e.direction==direction for e in r.evidence))
                    self.assertTrue(any(e.category in ('SUPPORT_RESISTANCE','SUPPLY_DEMAND') and e.direction==direction for e in r.evidence))

    def test_qualifying_outcome_is_prefix_equivalent_after_future_append(self):
        for reversal in (False,True):
            a,b,at=synthetic_ohlc_fixture(reversal)
            before=strategies_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
            self.assertTrue(any(e['status']=='QUALIFIES' for e in before['evaluations']))
            a.append(dict(timestamp=at.isoformat(),open=100,high=999,low=1,close=998))
            end=datetime.fromisoformat(b[-1]['timestamp'])+timedelta(minutes=5)
            b.append(dict(timestamp=end.isoformat(),open=100,high=999,low=1,close=998))
            self.assertEqual(before,strategies_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7))

    def test_real_opposing_choch_invalidates_continuation_without_alignment_change(self):
        a,b,at=two_frames(choch=True)
        r=analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(r.context['phase7_alignment'],'BULLISH_ALIGNMENT')
        self.assertEqual(outcome(r)['status'],'INVALIDATED')
        self.assertIn('FRESH_OPPOSING_M1_CHOCH',outcome(r)['reason_codes'])

    def test_research_quality_warnings_remain_visible(self):
        a,b,at=synthetic_ohlc_fixture()
        r=strategies_at('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        self.assertTrue(any(d['code']=='SESSION_NOT_CHECKED' for d in r['data_quality']['diagnostics']))
        self.assertEqual(r['validation_status'],'EXPERIMENTAL_SYNTHETIC_ONLY')

    def test_appending_future_and_unfinished_m5_does_not_change_earlier_outcome(self):
        a,b,at=two_frames(choch=True)
        options={'config':CONFIG,'intelligence_config':P7}
        before=strategies_at('SYNTHETIC_XAUUSD',a,b,at,**options)
        future_a=copy.deepcopy(a);future_b=copy.deepcopy(b)
        future_a.append(dict(timestamp=at.isoformat(),open=100,high=999,low=1,close=998))
        # Existing last M5 ends at 08:20; this next bar is unfinished at 08:23.
        last=datetime.fromisoformat(b[-1]['timestamp'])+timedelta(minutes=5)
        future_b.append(dict(timestamp=last.isoformat(),open=100,high=999,low=1,close=998))
        self.assertEqual(before,strategies_at('SYNTHETIC_XAUUSD',future_a,future_b,at,**options))
        self.assertEqual(before,strategies_at('SYNTHETIC_XAUUSD',future_a[:-1],future_b[:-1],at,**options))
    def test_direct_unfinished_m5_is_blocked_by_inherited_gate(self):
        a,b,at=two_frames();last=datetime.fromisoformat(b[-1]['timestamp'])+timedelta(minutes=5)
        b.append(dict(timestamp=last.isoformat(),open=100,high=101,low=99,close=100))
        r=analyze_context('SYNTHETIC_XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        self.assertFalse(r.data_quality['valid'])
        self.assertTrue(all(e['reason_codes']==['BLOCKED_DATA_QUALITY'] for e in evaluate_strategies(r)['evaluations']))
    def test_insufficient_history_and_gap_remain_abstentions(self):
        a,b,at=two_frames()
        for one,five in ((a[-3:],b[-3:]),(a[:5]+a[6:],b),(a,None)):
            result=strategies_at('SYNTHETIC_XAUUSD',one,five,at,config=CONFIG,intelligence_config=P7)
            self.assertTrue(all(e['status']=='ABSTAINS' for e in result['evaluations']))
    def test_repeated_causal_queries_are_identical_with_default_thresholds(self):
        a,b,at=two_frames(choch=True)
        self.assertEqual(strategies_at('SYNTHETIC_XAUUSD',a,b,at),strategies_at('SYNTHETIC_XAUUSD',a,b,at))
