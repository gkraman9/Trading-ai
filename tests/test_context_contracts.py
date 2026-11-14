"""Versioned schema contracts, absolute evidence references and replay revisions."""
import copy,json,re,unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from jsonschema import Draft202012Validator,FormatChecker,ValidationError
from iat.intelligence.context import analyze_context,ContextStream
from iat.intelligence.context_models import ContextConfig
from iat.intelligence.context_evidence import ReplayLedger
from test_context_components import CONFIG,price_candles,frame
from test_context_engine import two_frames,P7
from test_intelligence_patterns import START,rows


class ContextContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema=json.loads(Path('config/market-context-report-v1.schema.json').read_text())
        cls.validator=Draft202012Validator(cls.schema,format_checker=FormatChecker())
        cls.config_schema=json.loads(Path('config/market-context-config-v1.schema.json').read_text())
    def report(self):
        a,b,at=two_frames(choch=True)
        return analyze_context('X',a,b,at,config=CONFIG,intelligence_config=P7)
    def test_schema_success_and_blocked(self):
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(json.loads(json.dumps(self.report().to_dict(),allow_nan=False)))
        r=analyze_context('X',rows([100]*3),None,START+timedelta(minutes=100))
        self.validator.validate(json.loads(json.dumps(r.to_dict(),allow_nan=False)))
    def test_schema_does_not_allow_execution_or_unversioned_fields(self):
        report=json.loads(json.dumps(self.report().to_dict()))
        for changes in ({'signal':'BUY'},{'execution_allowed':True},{'report_version':2},{'unknown':'data'}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):self.validator.validate(dict(report,**changes))
    def test_unsafe_report_cannot_be_constructed(self):
        r=self.report()
        for options in ({'signal':'SELL'},{'mode':'LIVE'},{'execution_allowed':True}):
            with self.assertRaises(ValueError):replace(r,**options)
    def test_synthetic_configuration_and_strictness(self):
        Draft202012Validator.check_schema(self.config_schema)
        data=json.loads(Path('config/examples/market-context-v1.synthetic.json').read_text())
        Draft202012Validator(self.config_schema).validate(data)
        self.assertEqual(ContextConfig.from_dict(data).digest,ContextConfig().digest)
        for data in ({},{'version':2},{'version':True},{'version':1,'unknown':1}):
            with self.assertRaises(ValidationError):Draft202012Validator(self.config_schema).validate(data)
    def test_no_phase7_window_relative_refs_in_context_payload(self):
        raw=json.dumps(self.report().to_dict())
        self.assertIsNone(re.search(r'M[15]:(?:C|P):(?:HIGH:|LOW:)?\d+',raw))
    def test_hypothesis_evidence_and_zones_resolve(self):
        r=self.report();ids={e.id for e in r.evidence};sources=r.interpretations['source_registry']
        for h in r.hypotheses:
            self.assertTrue(set(h.supporting_evidence)<=ids)
            self.assertTrue(set(h.contradictory_evidence)<=ids)
            self.assertTrue(set(h.relevant_zones)<=set(sources))
    def test_duplicate_records_same_snapshot_not_counted_twice_by_replay(self):
        r=self.report();e=r.evidence[0];ledger=ReplayLedger()
        line=ledger.record(replace(r,evidence=(e,e)))
        self.assertEqual(line['unique_evidence_count'],1);self.assertEqual(line['new_evidence'],[e.id])
    def test_revisions_and_withdrawal_are_chronological(self):
        r=self.report();ledger=ReplayLedger();first=ledger.record(r)
        self.assertEqual(len(first['hypothesis_revisions']),6)
        second=ledger.record(replace(r,analysis_at=(two_frames(choch=True)[2]+timedelta(minutes=1)).isoformat(),hypotheses=()))
        self.assertEqual(len(second['withdrawn_hypotheses']),6)
    def test_context_stream_keeps_inherited_late_and_backward_guards(self):
        stream=ContextStream('X');data=rows([100]*4)
        stream.append('M1',data[0]);stream.snapshot(START+timedelta(minutes=3))
        with self.assertRaises(ValueError):stream.append('M1',data[1])
        with self.assertRaises(ValueError):stream.snapshot(START)
    def test_liquidity_sweep_proxy_has_no_directional_reversal_vote(self):
        from test_intelligence_engine import WAVE
        a,b,at=two_frames()
        a=rows(WAVE+[114]);a[-1].update(high=118,low=113)
        at=START+timedelta(minutes=len(a))
        r=analyze_context('X',a,b,at,config=CONFIG,intelligence_config=P7)
        sweeps=[e for e in r.evidence if e.category=='LIQUIDITY' and e.details['event_type']=='CONFIRMED_SWEEP']
        self.assertTrue(sweeps)
        self.assertTrue(all(e.direction=='NEUTRAL' for e in sweeps))
