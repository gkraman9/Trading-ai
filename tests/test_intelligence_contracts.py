"""Published JSON schemas, complete evidence references, boundary regressions."""
import copy
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from iat.intelligence import IntelligenceConfig, analyze_intelligence, analyze_at
from test_intelligence_patterns import START, rows
from test_intelligence_engine import CONFIG, WAVE


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema=json.loads(Path('config/intelligence-report-v1.schema.json').read_text())
        cls.validator=Draft202012Validator(cls.schema,format_checker=FormatChecker())
        cls.config_schema=json.loads(Path('config/intelligence-config-v1.schema.json').read_text())

    def report(self,**options):
        return json.loads(json.dumps(analyze_intelligence('SYNTHETIC',rows(WAVE),None,
            START+timedelta(minutes=len(WAVE)),config=CONFIG,**options).to_dict(),allow_nan=False))

    def test_schema_itself_and_success_report(self):
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.report())

    def test_blocked_full_report_matches_schema(self):
        report=analyze_intelligence('SYNTHETIC',rows([100]*3),None,START+timedelta(minutes=100)).to_dict()
        self.validator.validate(json.loads(json.dumps(report)))

    def test_invalid_provenance_is_redacted_and_schema_valid(self):
        report=self.report(provenance='private-provenance-data')
        self.validator.validate(report)
        self.assertEqual(report['provenance'],'UNVERIFIED')
        self.assertNotIn('private-provenance',json.dumps(report))

    def test_execution_flags_cannot_be_constructed_or_replaced(self):
        r=analyze_intelligence('SYNTHETIC',rows(WAVE),None,START+timedelta(minutes=len(WAVE)))
        for changes in ({'execution_allowed':True},{'signal':'BUY'},{'mode':'LIVE'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(r,**changes)

    def test_schema_rejects_modified_safety_and_unknown_fields(self):
        for changes in ({'execution_allowed':True},{'signal':'BUY'},{'unexpected':'value'},{'report_version':2}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):
                self.validator.validate(dict(self.report(),**changes))

    def test_schema_versioned_configuration_example_loads(self):
        schema=self.config_schema
        Draft202012Validator.check_schema(schema)
        example=json.loads(Path('config/examples/intelligence-v1.synthetic.json').read_text())
        Draft202012Validator(schema).validate(example)
        config=IntelligenceConfig.from_dict(example)
        self.assertEqual(config.left_strength,1)
        for raw in ({},{'version':2},{'version':True},{'version':1,'unknown':1}):
            with self.assertRaises(ValidationError):Draft202012Validator(schema).validate(raw)

    def test_evidence_graph_resolves_and_is_causal(self):
        report=self.report()
        for f in report['frames'].values():
            by_id={r['id']:r for r in f['evidence']}
            for p in f['confirmed_pivots']+f['candidate_pivots']:
                by_id[p['id']]={'available_at':p['confirmed_at']}
                self.assertTrue(all(ref in by_id for ref in p['evidence']))
            for p in f['patterns']:
                self.assertTrue(all(ref in by_id for ref in p['evidence']))
                self.assertTrue(all(by_id[ref]['available_at']<=p['detected_at'] for ref in p['evidence']))
            for event in f['events']:
                for ref in event['evidence']:
                    self.assertIn(ref,by_id)
                    self.assertLessEqual(by_id[ref]['available_at'],event['confirmed_at'])
                break_open=by_id[event['break_candle']]['opened_at']
                self.assertLessEqual(by_id[event['pivot_id']]['available_at'],break_open)
            self.assertTrue(all(ref in by_id for ref in f['structure']['evidence']))

    def test_future_malformed_prices_and_later_invalid_timestamps_not_inspected(self):
        history=rows(WAVE*2);at=START+timedelta(minutes=21)
        expected=analyze_at('X',history,None,at).to_dict()
        # The first future row defines the causal cutoff; later rows are not available yet.
        changed=copy.deepcopy(history)
        changed[-1]={'timestamp':'not-an-available-timestamp','close':'private-data'}
        self.assertEqual(expected,analyze_at('X',changed,None,at).to_dict())

    def test_history_cap_blocks_oversized_direct_input(self):
        report=analyze_intelligence('X',rows([100]*5001),None,START+timedelta(minutes=5001))
        self.assertFalse(report.data_quality['valid']);self.assertIn('HISTORY_LIMIT',report.reason_codes)

    def test_m5_misalignment_and_gap_are_not_repaired(self):
        for defect in ('alignment','gap'):
            m5=rows([100]*5,'M5')
            if defect=='alignment':m5[0]['timestamp']=(START+timedelta(minutes=1)).isoformat()
            else:del m5[2]
            report=analyze_intelligence('X',rows([100]*25),m5,START+timedelta(minutes=25))
            self.assertFalse(report.data_quality['valid']);self.assertFalse(report.frames)

    def test_break_failure_is_not_backfilled(self):
        history=rows(WAVE+[120,108,121])
        at=START+timedelta(minutes=len(WAVE)+1)
        earlier=analyze_at('X',history,None,at,config=CONFIG).to_dict()
        self.assertEqual(earlier,analyze_at('X',history[:len(WAVE)+1],None,at,config=CONFIG).to_dict())
        for event in earlier['frames']['M1']['events']:
            self.assertLessEqual(event['confirmed_at'],at.isoformat())
