"""Quality gating, causal replay and report contracts using synthetic observations."""
import copy
import json
import unittest
from dataclasses import asdict, replace
from datetime import timedelta
from unittest.mock import patch
from iat.intelligence import (analyze_intelligence, analyze_at, replay, IntelligenceStream,
                              IntelligenceConfig)
from iat.intelligence.multi_timeframe import align
from iat.intelligence.models import FrameReport, Structure
from iat.session_config import compile_session_config, load_session_config
from test_intelligence_patterns import START, rows
from test_session_v2 import synthetic_v2, bounded_day

CONFIG=IntelligenceConfig(left_strength=1,right_strength=1,range_window=3)
WAVE=[100,104,100,96,100,107,103,99,103,110,106,102,106,113,109,105,109,116,112,108,112]


def frame(state,tf='M1',events=()):
    at=(START+timedelta(minutes=20)).isoformat()
    return FrameReport(tf,at,at,10,(),{},(),(),(),Structure(state,at,(),(),(),state=='UNKNOWN'),events,(),())


class AlignmentTests(unittest.TestCase):
    def test_bullish(self):self.assertEqual(align({'M1':frame('BULLISH'),'M5':frame('BULLISH','M5')},'t').classification,'BULLISH_ALIGNMENT')
    def test_bearish(self):self.assertEqual(align({'M1':frame('BEARISH'),'M5':frame('BEARISH','M5')},'t').classification,'BEARISH_ALIGNMENT')
    def test_conflict(self):self.assertEqual(align({'M1':frame('BULLISH'),'M5':frame('BEARISH','M5')},'t').classification,'STRUCTURAL_CONFLICT')
    def test_mixed(self):self.assertEqual(align({'M1':frame('RANGING'),'M5':frame('BULLISH','M5')},'t').classification,'RANGING_OR_MIXED')
    def test_unknown(self):self.assertEqual(align({'M1':frame('UNKNOWN'),'M5':frame('BULLISH','M5')},'t').classification,'INSUFFICIENT_EVIDENCE')
    def test_missing(self):self.assertEqual(align({'M1':frame('BULLISH')},'t').classification,'INSUFFICIENT_EVIDENCE')
    def test_blocked(self):self.assertEqual(align({},'t',blocked=True).classification,'BLOCKED_DATA_QUALITY')
    def test_countertrend_choch_requires_current_confirmation(self):
        from iat.intelligence.models import StructuralEvent
        m1=frame('TRANSITIONAL');m5=frame('BEARISH','M5')
        event=StructuralEvent('x','BULLISH_CHOCH',100,'p','BEARISH','c',m1.data_as_of,1,0,'CLOSE',(),())
        self.assertEqual(align({'M1':replace(m1,events=(event,)),'M5':m5},'t').classification,'COUNTERTREND_TRANSITION')
        self.assertEqual(align({'M1':replace(m1,events=(replace(event,confirmed_at='old'),)),'M5':m5},'t').classification,'RANGING_OR_MIXED')


class IntelligenceEngineTests(unittest.TestCase):
    def analyze(self,r=None,**options):
        return analyze_intelligence('SYNTHETIC',rows(WAVE) if r is None else r,None,
                     START+timedelta(minutes=len(WAVE)),config=CONFIG,**options)

    def test_real_candle_swings_establish_bullish_structure(self):
        r=self.analyze()
        self.assertTrue(r.data_quality['valid'])
        self.assertEqual(r.frames['M1'].structure.classification,'BULLISH')
        self.assertTrue(any(e.event_type=='BULLISH_BOS' for e in r.frames['M1'].events))
        self.assertEqual(r.provenance,'SYNTHETIC_RESEARCH')

    def test_bearish_structure_is_not_candle_color(self):
        r=self.analyze(rows([200-c for c in WAVE]))
        self.assertEqual(r.frames['M1'].structure.classification,'BEARISH')
        self.assertTrue(all(c['open']==c['close'] for c in rows(WAVE)))

    def test_report_schema_and_finite_json(self):
        r=self.analyze().to_dict()
        self.assertEqual(r['report_version'],1)
        self.assertEqual(r['configuration_version'],1)
        self.assertEqual(len(r['configuration_sha256']),64)
        self.assertEqual(r['signal'],'WAIT');self.assertFalse(r['execution_allowed'])
        self.assertEqual(r['mode'],'READ_ONLY_SHADOW')
        self.assertTrue(r['observed_facts']);self.assertTrue(r['derived_structure'])
        self.assertTrue(r['research_hypotheses']);self.assertTrue(r['explanation'])
        json.dumps(r,allow_nan=False)

    def test_duplicate(self):
        r=rows(WAVE);r[2]['timestamp']=r[1]['timestamp']
        self.assert_blocked(r,'TIMESTAMP_DUPLICATE')
    def test_out_of_order(self):self.assert_blocked(rows(WAVE)[::-1],'TIMESTAMP_OUT_OF_ORDER')
    def test_malformed(self):
        r=rows(WAVE);r[0]['high']=1
        self.assert_blocked(r,'OHLC_MALFORMED')
    def test_nonfinite(self):
        r=rows(WAVE);r[0]['close']=float('nan')
        self.assert_blocked(r,'OHLC_MALFORMED')
    def test_boolean_price(self):
        r=rows(WAVE);r[0]['close']=True
        self.assert_blocked(r,'OHLC_MALFORMED')
    def test_naive_timestamp(self):
        r=rows(WAVE);r[0]['timestamp']='2026-11-12T08:00:00'
        self.assert_blocked(r,'TIMESTAMP_MALFORMED')
    def test_unexpected_gap(self):
        r=rows(WAVE);del r[5]
        self.assert_blocked(r,'GAP_UNVERIFIED')
    def test_unclosed_future_bar_rejected_by_direct_engine(self):
        self.assert_blocked(rows(WAVE+[120]),'BAR_UNCLOSED')
    def test_misaligned_timestamp(self):
        r=rows(WAVE);r[0]['timestamp']=(START+timedelta(seconds=1)).isoformat()
        self.assert_blocked(r,'TIMEFRAME_MISALIGNED')
    def test_stale(self):self.assert_blocked(rows(WAVE[:-5]),'DATA_STALE')
    def test_insufficient_history(self):self.assert_blocked(rows(WAVE[:2]),'HISTORY_INCOMPLETE')
    def test_invalid_provenance(self):
        self.assertFalse(self.analyze(provenance='VERIFIED_BROKER').data_quality['valid'])
    def test_live_without_calendar(self):
        self.assertFalse(self.analyze(provenance='VALIDATED_LIVE').data_quality['valid'])

    def assert_blocked(self,rows_,code):
        r=self.analyze(rows_)
        self.assertFalse(r.data_quality['valid'])
        self.assertEqual(r.alignment.classification,'BLOCKED_DATA_QUALITY')
        self.assertFalse(r.frames);self.assertFalse(r.research_hypotheses)
        self.assertIn(code,r.reason_codes)
        self.assertEqual(r.signal,'WAIT');self.assertFalse(r.execution_allowed)

    def test_no_data_blocked(self):
        r=analyze_intelligence('X',None,None,START)
        self.assertFalse(r.data_quality['valid'])

    def test_no_broker_import_or_access(self):
        import sys
        with patch.dict(sys.modules,{'MetaTrader5':None}):
            self.assertTrue(self.analyze().data_quality['valid'])

    def test_extreme_prices_fail_closed_without_nan(self):
        r=rows([1e-300]*3)
        for c in r: c.update(open=1e-300,high=1e308,low=1e-300,close=1e308)
        report=analyze_intelligence('X',r,None,START+timedelta(minutes=3))
        self.assertFalse(report.data_quality['valid']);json.dumps(report.to_dict(),allow_nan=False)

    def test_unknown_configuration_and_symbol(self):
        with self.assertRaises(ValueError):analyze_intelligence('X',rows(WAVE),None,START,config={})

    def test_partial_session_candle_excluded_even_offline(self):
        cfg=synthetic_v2();cfg['symbol']='SYNTHETIC';cfg['weekdays']['thu']=bounded_day('08:00:30','23:00:00')
        r=self.analyze(calendar=compile_session_config(cfg),observed_finality=True)
        self.assertFalse(r.data_quality['valid']);self.assertIn('PARTIAL_SESSION_CANDLE',r.reason_codes)

    def test_unknown_phase_and_expired_calendar(self):
        for mode in ('unknown','expired'):
            cfg=synthetic_v2();cfg['symbol']='SYNTHETIC'
            if mode=='unknown':cfg['verification']['trade_schedule_verified']=False
            else:cfg['verification']['expires_at']='2026-11-12T08:00:00Z'
            r=self.analyze(calendar=compile_session_config(cfg),observed_finality=True)
            self.assertFalse(r.data_quality['valid']);self.assertFalse(r.frames)

    def test_wrong_calendar_symbol(self):
        r=self.analyze(calendar=compile_session_config(synthetic_v2()),observed_finality=True)
        self.assertFalse(r.data_quality['valid']);self.assertIn('SYMBOL_MISMATCH',r.reason_codes)

    def test_exness_blocked_with_both_provenances(self):
        calendar=load_session_config('config/profiles/exness-xauusd-v2.candidate.json')
        for provenance in ('SYNTHETIC_RESEARCH','VALIDATED_LIVE'):
            r=analyze_intelligence('XAUUSD',rows(WAVE),None,START+timedelta(minutes=len(WAVE)),
                   calendar=calendar,provenance=provenance,observed_finality=True)
            self.assertFalse(r.data_quality['valid']);self.assertFalse(r.research_hypotheses)

    def test_supplied_verified_session_does_not_infer_finality(self):
        cfg=synthetic_v2();cfg['symbol']='SYNTHETIC'
        self.assertFalse(self.analyze(calendar=compile_session_config(cfg)).data_quality['valid'])


class CausalityTests(unittest.TestCase):
    def test_m5_unfinished_excluded(self):
        m1=rows([100]*19);m5=rows([100]*4,'M5')
        r=analyze_at('SYNTHETIC',m1,m5,START+timedelta(minutes=19))
        self.assertEqual(r.frames['M5'].candle_count,3)
        self.assertEqual(r.frames['M5'].data_as_of,(START+timedelta(minutes=15)).isoformat())

    def test_m5_exact_boundary_available(self):
        r=analyze_at('SYNTHETIC',rows([100]*20),rows([100]*5,'M5'),START+timedelta(minutes=20))
        self.assertEqual(r.frames['M5'].candle_count,4)

    def test_future_candles_cannot_change_past_report(self):
        m1=rows(WAVE*3);m5=rows(WAVE,'M5');at=START+timedelta(minutes=30)
        a=analyze_at('X',m1,m5,at,config=CONFIG).to_dict()
        altered=copy.deepcopy(m1)
        for c in altered[30:]:c.update(open=1000,high=1001,low=999,close=1000)
        altered5=copy.deepcopy(m5)
        for c in altered5[6:]:c.update(open=1,high=2,low=.5,close=1)
        self.assertEqual(a,analyze_at('X',altered,altered5,at,config=CONFIG).to_dict())

    def test_stream_prefix_replay_equivalence(self):
        m1=rows(WAVE*3);m5=rows([100+v/100 for v in WAVE],'M5')
        stream=IntelligenceStream('X',config=CONFIG)
        replayed=list(replay('X',m1,m5,config=CONFIG))
        cursor=0
        for i,row in enumerate(m1):
            at=START+timedelta(minutes=i+1)
            stream.append('M1',row)
            while cursor<len(m5) and START+timedelta(minutes=5*(cursor+1))<=at:
                stream.append('M5',m5[cursor]);cursor+=1
            actual=stream.snapshot(at).to_dict()
            expected=analyze_at('X',m1[:i+1],m5[:cursor],at,config=CONFIG).to_dict()
            self.assertEqual(actual,expected)
            self.assertEqual(actual,replayed[i].to_dict())
            for f in actual['frames'].values():
                for p in f['confirmed_pivots']:
                    self.assertLessEqual(p['confirmed_at'],at.isoformat())
                    self.assertGreater(p['confirmed_at'],p['occurred_at'])
                for event in f['events']:
                    self.assertLessEqual(event['confirmed_at'],at.isoformat())

    def test_candidate_does_not_leak_future_confirmation(self):
        m1=rows([100,101,106,103,102])
        before=analyze_at('X',m1,None,START+timedelta(minutes=4))
        after=analyze_at('X',m1,None,START+timedelta(minutes=5))
        self.assertFalse(before.frames['M1'].confirmed_pivots)
        self.assertTrue(before.frames['M1'].candidate_pivots)
        self.assertEqual(after.frames['M1'].confirmed_pivots[0].confirmation_index,4)

    def test_stream_rejects_duplicate_late_and_backward_clock(self):
        stream=IntelligenceStream('X');r=rows([100]*4)
        stream.append('M1',r[0])
        with self.assertRaises(ValueError):stream.append('M1',r[0])
        stream.snapshot(START+timedelta(minutes=4))
        with self.assertRaises(ValueError):stream.append('M1',r[1])
        with self.assertRaises(ValueError):stream.snapshot(START)

    def test_stale_m5_blocks_even_when_m1_valid(self):
        r=analyze_at('X',rows([100]*60),rows([100]*3,'M5'),START+timedelta(minutes=60))
        self.assertFalse(r.data_quality['valid']);self.assertFalse(r.frames)

    def test_reports_do_not_mutate_inputs(self):
        r=rows(WAVE);saved=copy.deepcopy(r)
        analyze_intelligence('X',r,None,START+timedelta(minutes=len(r)))
        self.assertEqual(r,saved)
