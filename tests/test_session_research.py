"""Research fixtures are explicitly synthetic; no local terminal was tested."""
import contextlib
import copy
from datetime import datetime,timedelta,timezone
import io,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from diagnostics import session_v2_research,mt5_readonly_check
from iat.session_config import compile_session_config
from iat.session_research import research_report,new_research_report,validate_research_report
from iat.session_capture import capture_demo_research
from iat.evidence import AtomicEvidence
from test_session_v2 import synthetic_v2,bounded_day,window
from test_api import NOW
from test_diagnostic import DemoAdapter,SECRET
from test_exness_profile import ForbiddenMT5

ROOT=Path(__file__).resolve().parents[1]


def observations():
    return {tf:[{'timestamp':datetime(2026,11,12,10,minute,tzinfo=timezone.utc).isoformat(),'finalized':True}
                for minute in values] for tf,values in (('M1',(27,28,29)),('M5',(15,20,25)))}


class ResearchTests(unittest.TestCase):
    def report(self,data=None,config=None,**kw):
        return research_report(compile_session_config(synthetic_v2() if config is None else config),NOW,
                               observations() if data is None else data,origin='SYNTHETIC_TEST',**kw)

    def test_synthetic_full_observations_are_labelled_not_broker_pass(self):
        report=self.report()
        self.assertEqual(report['status'],'WARN')
        self.assertEqual(report['frames']['M1']['full_count'],3)
        self.assertEqual(report['frames']['M5']['missing_full_count'],0)
        self.assertEqual(report['provenance']['origin'],'SYNTHETIC_TEST')
        self.assertFalse(report['safety']['ordinary_strategy_inputs_emitted'])
        self.assertFalse(report['safety']['execution_allowed'])

    def test_partial_geometry_and_finality_are_separate(self):
        config=synthetic_v2();config['weekdays']['thu']=bounded_day()
        data={'M5':[{'timestamp':'2026-11-12T09:00:00Z','finalized':True}]}
        report=research_report(compile_session_config(config),datetime(2026,11,12,10,tzinfo=timezone.utc),data,origin='FILE_UNVERIFIED')
        self.assertEqual(report['frames']['M5']['partial_count'],1)
        self.assertEqual(report['frames']['M5']['finality_uncertain_count'],1)
        self.assertEqual(report['status'],'FAIL')

    def test_missing_full_and_partial_intervals_distinguished(self):
        config=synthetic_v2()
        config['maintenance']=[{'start':'2026-11-12T10:05:30','end':'2026-11-12T10:06:00'}]
        data={'M1':[{'timestamp':'2026-11-12T10:04:00Z','finalized':True},
                    {'timestamp':'2026-11-12T10:07:00Z','finalized':True}]}
        report=self.report(data,config)
        self.assertEqual(report['frames']['M1']['missing_partial_count'],1)
        self.assertEqual(report['frames']['M1']['missing_full_count'],1)

    def test_unverified_profile_stays_blocked_even_with_matching_timestamps(self):
        calendar=compile_session_config(json.loads((ROOT/'config/profiles/exness-xauusd-v2.candidate.json').read_text()))
        report=research_report(calendar,NOW,observations(),origin='FILE_UNVERIFIED')
        self.assertEqual(report['status'],'BLOCKED')
        self.assertGreater(report['frames']['M1']['unknown_count'],0)
        self.assertIn('HOLIDAY_COVERAGE_UNKNOWN',report['requirements'])
        self.assertFalse(report['provenance']['terminal_capture_attempted'])

    def test_blocked_capture_never_accesses_provider_or_credentials(self):
        report=capture_demo_research(ROOT/'config/profiles/exness-xauusd-v2.candidate.json',mt5=ForbiddenMT5(),clock=lambda:NOW)
        self.assertEqual(report['status'],'BLOCKED')
        self.assertFalse(report['provenance']['terminal_capture_attempted'])

    def test_duplicate_out_of_order_and_malformed_observations_fail(self):
        for defect in ('duplicate','order','malformed','unaligned'):
            data=observations()
            if defect=='duplicate':data['M1'][1]=copy.deepcopy(data['M1'][0])
            if defect=='order':data['M1'].reverse()
            if defect=='malformed':data['M1'][0]['timestamp']=SECRET
            if defect=='unaligned':data['M1'][0]['timestamp']='2026-11-12T10:27:01Z'
            report=self.report(data)
            self.assertEqual(report['status'],'FAIL')
            self.assertNotIn(SECRET,json.dumps(report))

    def test_unknown_finality_fails_without_inferring_ohlc_completion(self):
        data=observations()
        for row in data['M1']:row['finalized']=None
        report=self.report(data)
        self.assertIn('CANDLE_FINALITY_UNCERTAIN',report['frames']['M1']['codes'])
        self.assertEqual(report['status'],'FAIL')

    def test_missing_and_stale_data_fail(self):
        data=observations();del data['M1'][1]
        report=self.report(data)
        self.assertIn('UNEXPECTED_MISSING_BARS',report['frames']['M1']['codes'])
        data=observations()
        for rows in data.values():
            for row in rows:row['timestamp']=(datetime.fromisoformat(row['timestamp'])-timedelta(hours=1)).isoformat()
        report=self.report(data)
        self.assertIn('DATA_STALE',report['frames']['M5']['codes'])

    def test_report_redaction_rejects_raw_refs_and_unsafe_permissions(self):
        report=self.report()
        for key in ('server','account','source_reference'):
            altered=copy.deepcopy(report);altered['provenance'][key]=SECRET
            with self.assertRaises(ValueError):validate_research_report(altered)
        altered=copy.deepcopy(report);altered['safety']['execution_allowed']=True
        with self.assertRaises(ValueError):validate_research_report(altered)

    def test_sparse_large_comparison_is_bounded_with_unknown_counts(self):
        config=synthetic_v2();config['coverage']['end']='2026-12-01';config['verification']['expires_at']='2026-12-01T00:00:00Z'
        rows={'M1':[{'timestamp':'2026-11-06T00:00:00Z','finalized':True},
                     {'timestamp':'2026-11-30T23:58:00Z','finalized':True}]}
        report=research_report(compile_session_config(config),datetime(2026,11,30,23,59,59,tzinfo=timezone.utc),rows,origin='SYNTHETIC_TEST')
        self.assertIn('RESEARCH_LIMIT_EXCEEDED',report['frames']['M1']['codes'])
        self.assertIsNone(report['frames']['M1']['missing_full_count'])
        self.assertEqual(report['status'],'FAIL')

    def test_synthetic_configuration_cannot_become_live_research_pass(self):
        calendar=compile_session_config(synthetic_v2())
        comparison={'scope':'PHASES_V2','comparison':'MATCH','mismatch_intervals':0,'codes':['BROKER_SESSIONS_MATCH']}
        report=research_report(calendar,NOW,observations(),origin='LOCAL_DEMO_OBSERVATION',
                               broker_comparison=comparison,terminal_capture_attempted=True)
        self.assertEqual(report['status'],'WARN')
        self.assertIn('SYNTHETIC_EVIDENCE',[d['code'] for d in report['diagnostics']])

    def test_atomic_research_failure_leaves_incomplete_not_pass(self):
        calendar=compile_session_config(synthetic_v2())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json';initial=new_research_report(calendar,NOW)
            writer=AtomicEvidence(path,initial,validator=validate_research_report)
            report=self.report();report['run_id']=initial['run_id']
            with patch('iat.evidence.os.replace',side_effect=OSError(SECRET)),self.assertRaises(OSError):writer.publish(report)
            self.assertEqual(json.loads(path.read_text())['status'],'FAIL')
            self.assertNotIn(SECRET,path.read_text())

    def test_research_cli_writes_blocked_redacted_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'new.json';output=io.StringIO()
            with contextlib.redirect_stdout(output):
                result=session_v2_research.main(['--config',str(ROOT/'config/profiles/exness-xauusd-v2.candidate.json'),'--report-path',str(path)])
            self.assertEqual(result,3)
            self.assertEqual(json.loads(path.read_text())['status'],'BLOCKED')
            self.assertFalse(json.loads(path.read_text())['safety']['execution_allowed'])

    def test_conflicting_config_cli_has_typed_failure_report(self):
        config=synthetic_v2();config['weekdays']['thu']['phases']*=2
        with tempfile.TemporaryDirectory() as directory:
            config_path=Path(directory)/'config.json';config_path.write_text(json.dumps(config));report_path=Path(directory)/'report.json'
            with contextlib.redirect_stdout(io.StringIO()):
                code=session_v2_research.main(['--config',str(config_path),'--report-path',str(report_path)])
            self.assertEqual(code,1)
            report=json.loads(report_path.read_text())
            self.assertEqual(report['diagnostics'][0]['code'],'PHASE_CONFLICT')
            self.assertEqual(report['status'],'FAIL')

    def test_v2_demo_diagnostic_additive_fields_and_safety(self):
        config=synthetic_v2();adapter=DemoAdapter()
        adapter.iat_session_metadata=lambda symbol,start,end:{'version':2,'kind':'PHASES_V2','symbol':symbol,
                    'collected_at_utc':NOW.isoformat(),'calendar':config}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_text(json.dumps(config))
            with patch.object(mt5_readonly_check,'package_version',return_value='5.0.5370'):
                report=mt5_readonly_check.validate_demo(path,mt5=adapter,clock=lambda:NOW)
            self.assertEqual(report['status'],'PASS')
            self.assertEqual(report['session_v2']['version'],2)
            self.assertFalse(report['safety']['execution_allowed'])
            mt5_readonly_check.validate_report(report)
            self.assertNotIn(SECRET,json.dumps(report))

    def test_capture_uses_demo_gate_and_never_treats_mock_as_real(self):
        config=synthetic_v2();adapter=DemoAdapter()
        adapter.iat_session_metadata=lambda symbol,start,end:{'version':2,'kind':'PHASES_V2','symbol':symbol,
                    'collected_at_utc':NOW.isoformat(),'calendar':config}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_text(json.dumps(config))
            with patch.object(mt5_readonly_check,'package_version',return_value='5.0.5370'):
                report=capture_demo_research(path,mt5=adapter,clock=lambda:NOW)
            self.assertEqual(report['status'],'WARN')
            self.assertEqual(report['frames']['M1']['observed_count'],100)
            self.assertEqual(report['provenance']['origin'],'SYNTHETIC_TEST')
            self.assertTrue(adapter.stopped)
            self.assertNotIn(SECRET,json.dumps(report))

    def test_capture_non_demo_account_gets_no_quotes(self):
        config=synthetic_v2();adapter=DemoAdapter(mode=2)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_text(json.dumps(config))
            report=capture_demo_research(path,mt5=adapter,clock=lambda:NOW)
        self.assertEqual(adapter.requests,[])
        self.assertEqual(report['status'],'FAIL')
        self.assertTrue(adapter.stopped)
