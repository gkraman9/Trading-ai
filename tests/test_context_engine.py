"""Causal context, requested regressions, explainable competing scenarios and safety."""
from dataclasses import replace
from datetime import timedelta,datetime
import copy,json
import unittest
from iat.intelligence import IntelligenceConfig
from iat.intelligence.context import analyze_context,context_at,replay_context
from iat.intelligence.context_models import ContextConfig,Evidence
from iat.intelligence.context_evidence import ReplayLedger,candle_id,identity
from iat.intelligence import confluence,hypotheses
from iat.intelligence.engine import analyze_intelligence
from iat.session_config import compile_session_config,load_session_config
from test_context_components import CONFIG
from test_intelligence_patterns import START,rows
from test_intelligence_engine import WAVE
from test_session_v2 import synthetic_v2,bounded_day

P7=IntelligenceConfig(left_strength=1,right_strength=1,range_window=3)


def two_frames(mirror=False,choch=False):
    a=WAVE+([118,94] if choch else [])
    b=WAVE
    if mirror:a=[200-v for v in a];b=[200-v for v in b]
    m1=rows(a);m5=rows(b,'M5')
    for row in m5:
        row['timestamp']=(datetime.fromisoformat(row['timestamp'])-timedelta(minutes=85)).isoformat()
    return m1,m5,START+timedelta(minutes=len(m1))


def evidence(id_,category,direction='BULLISH',tf='M1',details=None):
    return Evidence(id_,category,tf,direction,START.isoformat(),(START+timedelta(minutes=1)).isoformat(),(),(),details or {})


def ctx():
    return {'classification':'BULLISH_ALIGNMENT','phase7_alignment':'BULLISH_ALIGNMENT',
            'm1_structure':'BULLISH','m5_structure':'BULLISH','m1_as_of':'t','m5_as_of':'t','limitations':[]}


class ConfluenceTests(unittest.TestCase):
    def test_weights_and_correlated_category_caps(self):
        es=[evidence('a','STRUCTURE'),evidence('b','STRUCTURE'),evidence('c','STRUCTURE',tf='M5'),
            evidence('d','SUPPORT_RESISTANCE'),evidence('e','SUPPLY_DEMAND')]
        r=confluence.evaluate(es,CONFIG,ctx())
        self.assertEqual(r['scores']['BULLISH'],5)
        self.assertEqual(sum(c['weight'] for c in r['weighted_evidence']),5)
        self.assertEqual(r['score_kind'],'HEURISTIC_EVIDENCE_NOT_PROBABILITY')

    def test_duplicate_same_evidence_not_double_counted(self):
        e=evidence('a','STRUCTURE')
        self.assertEqual(len(confluence.evaluate([e,e],CONFIG,ctx())['weighted_evidence']),1)
        with self.assertRaises(ValueError):confluence.evaluate([e,replace(e,direction='BEARISH')],CONFIG,ctx())

    def test_conflict_margin_and_opposition_abstain(self):
        es=[evidence('a','STRUCTURE'),evidence('b','STRUCTURE','BEARISH','M5')]
        r=confluence.evaluate(es,CONFIG,ctx())
        self.assertIn('HEURISTIC_MARGIN_TOO_SMALL',r['abstention_reasons'])

    def test_fresh_choch_against_m5_is_not_hidden_when_scores_change_leader(self):
        es=[evidence('a','STRUCTURE'),evidence('b','STRUCTURE',tf='M5'),
            evidence('c','TRANSITION','BEARISH',details={'fresh':True}),
            evidence('d','MOMENTUM','BEARISH'),evidence('e','MOMENTUM','BEARISH','M5'),
            evidence('f','LIQUIDITY','BEARISH')]
        r=confluence.evaluate(es,replace(CONFIG,contradiction_limit=100,minimum_score=1),ctx())
        self.assertEqual(r['leader'],'BEARISH')
        self.assertEqual(r['fresh_opposing_m1_choch'],['c'])
        self.assertIn('FRESH_OPPOSING_M1_CHOCH',r['abstention_reasons'])

    def test_low_support_abstains(self):
        r=confluence.evaluate([evidence('a','CANDLE')],CONFIG,ctx())
        self.assertIn('INSUFFICIENT_HEURISTIC_SUPPORT',r['abstention_reasons'])

    def test_high_score_never_changes_report_execution(self):
        m1,m5,at=two_frames()
        report=analyze_context('X',m1,m5,at,config=CONFIG,intelligence_config=P7)
        self.assertFalse(report.execution_allowed);self.assertEqual(report.signal,'WAIT')
        with self.assertRaises(ValueError):replace(report,execution_allowed=True)

    def test_material_opposition_and_high_volatility_are_explicit(self):
        es=[evidence('a','STRUCTURE'),evidence('b','STRUCTURE',tf='M5'),
            evidence('c','TRANSITION','BEARISH'),evidence('d','MOMENTUM','BEARISH'),
            evidence('e','VOLATILITY','NEUTRAL',details={'regime':'HIGH_VOLATILITY'})]
        r=confluence.evaluate(es,CONFIG,ctx())
        self.assertIn('MATERIAL_OPPOSING_EVIDENCE',r['abstention_reasons'])
        self.assertIn('HIGH_VOLATILITY_REQUIRES_FURTHER_RESEARCH',r['abstention_reasons'])

    def test_hypotheses_have_support_opposition_and_invalidation(self):
        m1,m5,at=two_frames(choch=True)
        r=analyze_context('X',m1,m5,at,config=CONFIG,intelligence_config=P7)
        self.assertEqual(len(r.hypotheses),6)
        for h in r.hypotheses:
            self.assertTrue(h.assumptions);self.assertTrue(h.invalidation_conditions)
            self.assertEqual(h.generated_at,at.isoformat());self.assertTrue(h.timeframe_context)
        bull=next(h for h in r.hypotheses if h.hypothesis_type=='BULLISH_CONTINUATION_POSSIBILITY')
        self.assertTrue(bull.supporting_evidence);self.assertTrue(bull.contradictory_evidence)

    def test_fresh_opposing_m1_choch_survives_bullish_phase7_alignment(self):
        self.check_opposing(False,'BULLISH_ALIGNMENT','BEARISH','BULLISH_CONTINUATION_POSSIBILITY')

    def test_fresh_opposing_m1_choch_survives_bearish_phase7_alignment(self):
        self.check_opposing(True,'BEARISH_ALIGNMENT','BULLISH','BEARISH_CONTINUATION_POSSIBILITY')

    def check_opposing(self,mirror,alignment,opponent,hypothesis):
        m1,m5,at=two_frames(mirror,True)
        p7=analyze_intelligence('X',m1,m5,at,config=P7)
        self.assertEqual(p7.alignment.classification,alignment)
        report=analyze_context('X',m1,m5,at,config=CONFIG,intelligence_config=P7)
        self.assertTrue(report.data_quality['valid'])
        events=[e for e in report.evidence if e.category=='TRANSITION' and e.direction==opponent and e.timeframe=='M1']
        self.assertTrue(events)
        h=next(h for h in report.hypotheses if h.hypothesis_type==hypothesis)
        self.assertTrue(set(e.id for e in events)<=set(h.contradictory_evidence))
        self.assertIn('FRESH_OPPOSING_M1_CHOCH',report.abstention_reasons)
        self.assertEqual(report.confluence['selected_hypothesis'],'NO_CLEAR_DIRECTIONAL_HYPOTHESIS')


class ContextQualityTests(unittest.TestCase):
    def report(self,m1=None,**options):
        a,b,at=two_frames()
        return analyze_context('X',m1 or a,b,at,config=CONFIG,intelligence_config=P7,**options)

    def test_observations_interpretations_hypotheses_separated(self):
        r=self.report()
        self.assertTrue(r.observed_facts);self.assertTrue(r.interpretations);self.assertTrue(r.hypotheses)
        json.dumps(r.to_dict(),allow_nan=False)

    def test_critical_failures_clear_all_directions(self):
        a,b,at=two_frames()
        for defect in ('malformed','duplicate','gap','unclosed','stale','out_of_order'):
            bad=copy.deepcopy(a)
            if defect=='malformed':bad[0]['high']=1
            elif defect=='duplicate':bad[1]['timestamp']=bad[0]['timestamp']
            elif defect=='gap':del bad[5]
            elif defect=='unclosed':bad.append(rows([100]*22)[-1])
            elif defect=='stale':bad=bad[:-5]
            else:bad.reverse()
            r=analyze_context('X',bad,b,at,config=CONFIG,intelligence_config=P7)
            with self.subTest(defect=defect):
                self.assertFalse(r.data_quality['valid']);self.assertFalse(r.evidence);self.assertFalse(r.hypotheses)
                self.assertEqual(r.context['classification'],'BLOCKED_DATA_QUALITY')

    def test_partial_session_rejected(self):
        a,b,at=two_frames()
        cfg=synthetic_v2();cfg['symbol']='X';cfg['weekdays']['thu']=bounded_day('08:00:30','23:00:00')
        r=analyze_context('X',a,None,at,calendar=compile_session_config(cfg),observed_finality=True)
        self.assertFalse(r.data_quality['valid']);self.assertFalse(r.hypotheses)

    def test_exness_remains_blocked_in_both_live_and_research(self):
        a,b,at=two_frames()
        calendar=load_session_config('config/profiles/exness-xauusd-v2.candidate.json')
        for provenance in ('VALIDATED_LIVE','SYNTHETIC_RESEARCH'):
            r=analyze_context('XAUUSD',a,b,at,calendar=calendar,provenance=provenance,observed_finality=True)
            self.assertFalse(r.data_quality['valid']);self.assertFalse(r.evidence)

    def test_insufficient_history_and_warmup_are_explicit(self):
        r=analyze_context('X',rows([100]*3),None,START+timedelta(minutes=3))
        self.assertEqual(r.context['classification'],'INSUFFICIENT_DATA')
        self.assertTrue(r.abstention_reasons)
        self.assertEqual(r.confluence['selected_hypothesis'],'NO_CLEAR_DIRECTIONAL_HYPOTHESIS')

    def test_zero_price_rejected(self):
        a,b,at=two_frames();a[0]['low']=0
        self.assertFalse(analyze_context('X',a,b,at).data_quality['valid'])

    def test_extreme_arithmetic_cannot_emit_nonfinite_scores(self):
        a,b,at=two_frames();a[-1].update(open=1e308,high=1e308,low=1e-300,close=1e308)
        r=analyze_context('X',a,b,at)
        self.assertFalse(r.data_quality['valid']);json.dumps(r.to_dict(),allow_nan=False)

    def test_complete_canonical_evidence_graph(self):
        r=self.report();sources=r.interpretations['source_registry']
        for e in r.evidence:
            self.assertLessEqual(e.available_at,r.analysis_at)
            for ref in e.references:self.assertIn(ref,sources)
        for value in sources.values():
            self.assertLessEqual(value['available_at'],r.analysis_at)
            for ref in value.get('references',[]):self.assertIn(ref,sources)


class ContextReplayTests(unittest.TestCase):
    def test_future_prices_do_not_change_past_context(self):
        m1=rows(WAVE*3);m5=rows(WAVE,'M5');at=START+timedelta(minutes=30)
        expected=context_at('X',m1,m5,at,config=CONFIG,intelligence_config=P7).to_dict()
        changed=copy.deepcopy(m1)
        for c in changed[30:]:c.update(open=500,high=501,low=499,close=500)
        changed5=copy.deepcopy(m5)
        for c in changed5[6:]:c.update(open=5,high=6,low=4,close=5)
        self.assertEqual(expected,context_at('X',changed,changed5,at,config=CONFIG,intelligence_config=P7).to_dict())

    def test_unfinished_m5_not_used(self):
        r=context_at('X',rows([100]*19),rows([100]*4,'M5'),START+timedelta(minutes=19),config=CONFIG)
        self.assertEqual(r.context['m5_as_of'],(START+timedelta(minutes=15)).isoformat())

    def test_prefix_replay_equivalence(self):
        m1=rows(WAVE*2);m5=rows(WAVE,'M5')
        log=list(replay_context('X',m1,m5,config=CONFIG,intelligence_config=P7))
        for i,entry in enumerate(log):
            at=START+timedelta(minutes=i+1)
            self.assertEqual(entry['report'],context_at('X',m1[:i+1],m5,at,config=CONFIG,intelligence_config=P7).to_dict())

    def test_rolling_ids_do_not_collapse_new_or_double_count_same_observations(self):
        m1=rows(WAVE*3);m5=rows(WAVE,'M5')
        log=list(replay_context('X',m1,m5,window=18,config=CONFIG,intelligence_config=P7))
        seen=set()
        saw_reuse=False
        for entry in log:
            ids={e['id'] for e in entry['report']['evidence']}
            expected_new=ids-seen
            self.assertEqual(set(entry['new_evidence']),expected_new)
            self.assertTrue(len(entry['report']['evidence'])==len(ids))
            if ids & seen:saw_reuse=True
            seen|=ids
            self.assertEqual(entry['unique_evidence_count'],len(seen))
            # Votes are current snapshot category budgets, never accumulated ledger counts.
            for direction,score in entry['report']['confluence']['scores'].items():
                self.assertLessEqual(score,2*(2*CONFIG.structure_weight+CONFIG.zone_weight+CONFIG.liquidity_weight+CONFIG.momentum_weight+CONFIG.candle_weight))
        self.assertTrue(saw_reuse)
        self.assertGreater(len(seen),18)

    def test_same_pivot_across_shifted_local_indexes_has_same_canonical_id(self):
        from iat.intelligence.context_evidence import pivot_id
        from test_intelligence_structure import pivot
        p=pivot('HIGH',4,105)
        shifted=replace(p,index=3,confirmation_index=4,id='M1:P:HIGH:3')
        self.assertEqual(pivot_id('X','M1',p),pivot_id('X','M1',shifted))
        other=replace(p,occurred_at=(START+timedelta(hours=1)).isoformat())
        self.assertNotEqual(pivot_id('X','M1',p),pivot_id('X','M1',other))

    def test_same_legacy_local_id_different_absolute_event_not_deduplicated(self):
        from iat.analysis import validate_candles
        a=validate_candles(rows([100]*3))[0]
        b=replace(a,timestamp=a.timestamp+timedelta(minutes=1))
        self.assertNotEqual(candle_id('X','M1',a),candle_id('X','M1',b))
        m1,m5,at=two_frames();r=analyze_context('X',m1,m5,at,config=CONFIG,intelligence_config=P7)
        e=r.evidence[0];e2=replace(e,id=identity('X','M1','OTHER',e.observed_at))
        ledger=ReplayLedger();first=ledger.record(replace(r,evidence=(e,)))
        second=ledger.record(replace(r,analysis_at=(at+timedelta(minutes=1)).isoformat(),evidence=(e,e2)))
        self.assertEqual(first['unique_evidence_count'],1);self.assertEqual(second['new_evidence'],[e2.id])
        self.assertEqual(second['unique_evidence_count'],2)

    def test_replay_rejects_invalid_window_and_backward_time(self):
        with self.assertRaises(ValueError):list(replay_context('X',rows([100]*3),None,window=2))
        m1,m5,at=two_frames();r=analyze_context('X',m1,m5,at,config=CONFIG,intelligence_config=P7)
        ledger=ReplayLedger();ledger.record(r)
        with self.assertRaises(ValueError):ledger.record(r)

class ContextStreamTests(unittest.TestCase):
    def test_stream_matches_prefix_and_rolling_replay(self):
        from iat.intelligence.context import ContextStream
        m1=rows(WAVE*2);m5=rows(WAVE,'M5')
        for window in (None,18):
            stream=ContextStream('X',config=CONFIG,intelligence_config=P7)
            expected=list(replay_context('X',m1,m5,window=window,config=CONFIG,intelligence_config=P7))
            cursor=0
            for i,row in enumerate(m1):
                at=START+timedelta(minutes=i+1)
                stream.append('M1',row)
                while cursor<len(m5) and datetime.fromisoformat(m5[cursor]['timestamp'])+timedelta(minutes=5)<=at:
                    stream.append('M5',m5[cursor]);cursor+=1
                self.assertEqual(stream.snapshot(at,window=window).to_dict(),expected[i]['report'])
