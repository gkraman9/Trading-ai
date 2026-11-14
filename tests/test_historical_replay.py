"""Synthetic files only. Historical declarations below are mocked, not real validation."""
from contextlib import redirect_stdout
from dataclasses import replace,asdict
from datetime import timedelta,datetime
from hashlib import sha256
from io import StringIO
import copy,csv,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from diagnostics.historical_replay import main
from iat.replay_dataset import load_dataset,DatasetError
from iat.historical_replay import run_dataset,validate_replay_report,summarize
from iat.intelligence.context import analyze_context,derive
from iat.intelligence.context_evidence import ReplayLedger
from iat.intelligence.decision_log import DecisionLog,Decision,from_replay
from iat.intelligence.engine import analyze_intelligence
from iat.intelligence.context_models import ContextConfig
from test_context_engine import two_frames,P7
from test_context_components import CONFIG
from test_intelligence_patterns import START,rows
from test_session_v2 import synthetic_v2,bounded_day
from iat.analysis import validate_candles


def write_fixture(root,count=30,*,historical=False,calendar=False):
    """No market data: deterministic synthetic prices and a mock provenance declaration."""
    prices=([100,104,100,96,100,107,103,99,103,110]*((count+9)//10))[:count]
    one=rows(prices)
    five=[]
    for j in range(0,count-4,5):
        cs=one[j:j+5]
        five.append({'timestamp':cs[0]['timestamp'],'open':cs[0]['open'],'high':max(c['high'] for c in cs),
                     'low':min(c['low'] for c in cs),'close':cs[-1]['close']})
    frames={}
    for tf,data in (('M1',one),('M5',five)):
        path=root/(tf.lower()+'.csv')
        with path.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=['timestamp','open','high','low','close'],lineterminator='\n')
            writer.writeheader();writer.writerows(data)
        frames[tf]={'file':path.name,'sha256':sha256(path.read_bytes()).hexdigest()}
    cal=None
    if calendar:
        path=root/'sessions.json';path.write_text(json.dumps(synthetic_v2()),encoding='utf-8')
        cal={'file':path.name,'sha256':sha256(path.read_bytes()).hexdigest()}
    manifest={'version':1,'symbol':'XAUUSD','dataset_kind':'INDEPENDENT_HISTORICAL' if historical else 'SYNTHETIC_FIXTURE',
        'source':{'name':'SYNTHETIC MOCK SOURCE','reference':'https://example.org/mock-data' if historical else 'synthetic:unit-fixture',
                  'retrieved_at_utc':'2026-11-13T00:00:00Z','curation_id':'synthetic-mock-only',
                  'independent_review':'ATTESTED' if historical else 'PENDING'},
        'utc_range':{'start':START.isoformat(),'end':(START+timedelta(minutes=count)).isoformat()},
        'frames':frames,'calendar':cal,'finality_attested':True}
    path=root/'manifest.json';path.write_text(json.dumps(manifest),encoding='utf-8')
    return path


def rewrite(path,change):
    data=json.loads(path.read_text());change(data);path.write_text(json.dumps(data),encoding='utf-8')


def recalc(path,tf):
    rewrite(path,lambda m:m['frames'][tf].update(sha256=sha256((path.parent/m['frames'][tf]['file']).read_bytes()).hexdigest()))


class EventIdentityTests(unittest.TestCase):
    def reports(self):
        a,b,at=two_frames(choch=True)
        phase7=analyze_intelligence('XAUUSD',a,b,at,config=P7)
        cs={'M1':tuple(validate_candles(a)),'M5':tuple(validate_candles(b))}
        report=analyze_context('XAUUSD',a,b,at,config=CONFIG,intelligence_config=P7)
        changed=replace(phase7,alignment=replace(phase7.alignment,classification='COUNTERTREND_TRANSITION'))
        evidence=derive(changed,cs,CONFIG)[0]
        return report,replace(report,analysis_at=(at+timedelta(minutes=1)).isoformat(),evidence=evidence)

    def test_alignment_revision_keeps_underlying_event_count(self):
        a,b=self.reports()
        first={e.event_id:e for e in a.evidence if e.event_id}
        second={e.event_id:e for e in b.evidence if e.event_id}
        self.assertTrue(first);self.assertEqual(set(first),set(second))
        self.assertTrue(all(first[k].id!=second[k].id for k in first))
        ledger=ReplayLedger();before=ledger.record(a);after=ledger.record(b)
        self.assertEqual(before['unique_event_count'],after['unique_event_count'])
        self.assertFalse(after['new_events'])
        self.assertTrue(after['event_revisions'])
        for revision in after['event_revisions']:
            self.assertIsNotNone(revision['previous_evidence_id'])
            self.assertEqual(revision['revision_index'],2)

    def test_unchanged_event_context_is_not_an_extra_revision(self):
        a,_=self.reports();ledger=ReplayLedger();ledger.record(a)
        at=datetime.fromisoformat(a.analysis_at)+timedelta(minutes=1)
        second=ledger.record(replace(a,analysis_at=at.isoformat()))
        self.assertFalse(second['event_revisions']);self.assertFalse(second['new_events'])

    def test_event_fact_is_separate_from_prior_structure_refs(self):
        a,_=self.reports();sources=a.interpretations['source_registry']
        for e in a.evidence:
            if e.event_id:
                self.assertIn(e.event_id,e.references)
                self.assertEqual(sources[e.event_id]['kind'],'CHOCH_EVENT')
                self.assertEqual(len(sources[e.event_id]['references']),2)


class DatasetLoaderTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_valid_manifest_checksums_coverage_and_source(self):
        path=write_fixture(self.root);d=load_dataset(path)
        self.assertEqual(d.metadata['symbol'],'XAUUSD');self.assertEqual(d.metadata['coverage']['M1']['candle_count'],30)
        self.assertEqual(d.metadata['coverage']['M5']['candle_count'],6)
        self.assertEqual(d.metadata['manifest_sha256'],sha256(path.read_bytes()).hexdigest())
        self.assertEqual(d.provenance,'SYNTHETIC_RESEARCH')
    def test_checksum_mismatch(self):
        path=write_fixture(self.root);(self.root/'m1.csv').write_text('invalid',encoding='utf-8')
        with self.assertRaisesRegex(DatasetError,'DATASET_CHECKSUM_MISMATCH'):load_dataset(path)
    def test_unknown_version_bool_and_symbol(self):
        for changes,code in (({'version':True},'DATASET_VERSION_UNSUPPORTED'),({'version':2},'DATASET_VERSION_UNSUPPORTED'),
                             ({'symbol':'OTHER'},'DATASET_SYMBOL_UNSUPPORTED'),({'unknown':1},'DATASET_SCHEMA_INVALID')):
            path=write_fixture(self.root);rewrite(path,lambda m:m.update(changes))
            with self.subTest(changes=changes),self.assertRaisesRegex(DatasetError,code):load_dataset(path)
    def test_duplicate_json_key(self):
        path=write_fixture(self.root);raw=path.read_text();path.write_text(raw.replace('"version": 1','"version": 1, "version": 1'))
        with self.assertRaisesRegex(DatasetError,'DATASET_DUPLICATE_KEY'):load_dataset(path)
    def test_no_path_traversal_or_absolute_files(self):
        for name in ('../other.csv','/tmp/other.csv','C:/private.csv','folder\\data.csv'):
            path=write_fixture(self.root);rewrite(path,lambda m:m['frames']['M1'].update(file=name))
            with self.subTest(name=name),self.assertRaisesRegex(DatasetError,'DATASET_PATH_INVALID'):load_dataset(path)
    def test_symlink_escape_rejected_where_supported(self):
        path=write_fixture(self.root)
        with tempfile.TemporaryDirectory() as other:
            target=Path(other)/'other.csv';target.write_bytes((self.root/'m1.csv').read_bytes())
            try:(self.root/'link.csv').symlink_to(target)
            except (OSError,NotImplementedError):return  # Windows without symlink privilege still exercises traversal cases.
            rewrite(path,lambda m:m['frames']['M1'].update(file='link.csv'))
            with self.assertRaisesRegex(DatasetError,'DATASET_PATH_INVALID'):load_dataset(path)
    def test_source_reference_cannot_include_credentials_or_query(self):
        for url in ('https://user:password@example.org/data','https://example.org/data?token=private','https://example.org/data#private'):
            path=write_fixture(self.root,historical=True);rewrite(path,lambda m:m['source'].update(reference=url))
            with self.assertRaisesRegex(DatasetError,'SOURCE_REFERENCE_UNSAFE'):load_dataset(path)
    def test_non_utc_and_naive_timestamps_rejected(self):
        for stamp in ('2026-11-12T08:00:00','2026-11-12T13:30:00+05:30'):
            path=write_fixture(self.root);file=self.root/'m1.csv';file.write_text(file.read_text().replace(START.isoformat(),stamp))
            recalc(path,'M1')
            with self.assertRaisesRegex(DatasetError,'DATASET_TIMESTAMP_INVALID'):load_dataset(path)
    def test_malformed_columns_and_price(self):
        path=write_fixture(self.root);file=self.root/'m1.csv';file.write_text(file.read_text().replace('timestamp,open,high,low,close','timestamp,open,high,low,close,private'))
        recalc(path,'M1')
        with self.assertRaises(DatasetError):load_dataset(path)
    def test_declared_range_does_not_hide_unclosed_tail(self):
        path=write_fixture(self.root);rewrite(path,lambda m:m['utc_range'].update(end=(START+timedelta(minutes=29)).isoformat()))
        with self.assertRaisesRegex(DatasetError,'BAR_OUTSIDE_DATASET_RANGE'):load_dataset(path)


class HistoricalRunnerTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def run_fixture(self,**options):
        path=write_fixture(self.root,**options)
        return run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7,window=25)
    def test_synthetic_is_pending_with_honest_coverage_and_blocked_warmup(self):
        r=self.run_fixture()
        self.assertEqual(r['historical_validation'],'PENDING');self.assertEqual(r['status'],'WARN')
        self.assertEqual(r['summary']['snapshots'],30)
        self.assertGreater(r['summary']['blocked_snapshots'],0);self.assertGreater(r['summary']['valid_snapshots'],0)
        self.assertIn('SYNTHETIC_EVIDENCE_HISTORICAL_VALIDATION_PENDING',r['reason_codes'])
        self.assertEqual(r['summary']['snapshots'],r['summary']['blocked_snapshots']+r['summary']['valid_snapshots'])
        self.assertEqual(r['preflight']['alignment']['comparable_m5_bars'],6)
    def test_independent_manifest_without_calendar_is_blocked(self):
        r=self.run_fixture(historical=True)
        self.assertEqual(r['status'],'BLOCKED');self.assertIn('SESSION_CALENDAR_REQUIRED',r['reason_codes'])
        self.assertIsNone(r['decision_log'])
    def test_mock_historical_with_verified_synthetic_calendar_scopes_checks_only(self):
        r=self.run_fixture(historical=True,calendar=True)
        self.assertEqual(r['historical_validation'],'DATASET_PIPELINE_CHECKS_PASSED')
        self.assertEqual(r['dataset']['source_authenticity'],'OPERATOR_DECLARATION_NOT_AUTHENTICATED')
    def test_pending_independent_review_and_finality_block(self):
        path=write_fixture(self.root,historical=True,calendar=True)
        rewrite(path,lambda m:(m['source'].update(independent_review='PENDING'),m.update(finality_attested=False)))
        r=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
        self.assertIn('INDEPENDENT_REVIEW_PENDING',r['reason_codes']);self.assertIn('CANDLE_FINALITY_UNCERTAIN',r['reason_codes'])
    def test_dataset_chronology_duplicates_gaps_and_ohlc_rejected(self):
        for defect in ('duplicate','order','gap','ohlc'):
            path=write_fixture(self.root);file=self.root/'m1.csv';lines=file.read_text().splitlines()
            if defect=='duplicate':lines[2]=lines[1]
            elif defect=='order':lines[2],lines[3]=lines[3],lines[2]
            elif defect=='gap':del lines[4]
            else:lines[2]=lines[2].rsplit(',',1)[0]+',nan'
            file.write_text('\n'.join(lines)+'\n');recalc(path,'M1')
            r=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
            with self.subTest(defect=defect):self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['decision_log'])
    def test_m1_m5_aggregate_mismatch_rejected(self):
        path=write_fixture(self.root);file=self.root/'m5.csv';lines=file.read_text().splitlines();parts=lines[1].split(',');parts[2]='999';lines[1]=','.join(parts)
        file.write_text('\n'.join(lines)+'\n');recalc(path,'M5')
        r=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
        self.assertEqual(r['status'],'FAIL');self.assertEqual(r['reason_codes'],['M1_M5_OHLC_MISMATCH'])
    def test_expired_or_partial_calendar_blocks(self):
        for defect in ('expiry','partial'):
            path=write_fixture(self.root,calendar=True);config=synthetic_v2()
            if defect=='expiry':config['verification']['expires_at']='2026-11-12T07:00:00Z'
            else:config['weekdays']['thu']=bounded_day('08:00:30','23:00:00')
            cal=self.root/'sessions.json';cal.write_text(json.dumps(config))
            rewrite(path,lambda m:m['calendar'].update(sha256=sha256(cal.read_bytes()).hexdigest()))
            r=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
            self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['decision_log'])
    def test_repeatability_and_prefix_log_equivalence(self):
        path=write_fixture(self.root,count=35);d=load_dataset(path)
        a=run_dataset(d,config=CONFIG,intelligence_config=P7,window=20)
        b=run_dataset(d,config=CONFIG,intelligence_config=P7,window=20)
        self.assertEqual(a,b);self.assertEqual(a['decision_log_sha256'],b['decision_log_sha256'])
        prefix=copy.deepcopy(d)
        cutoff=START+timedelta(minutes=25)
        prefix.rows['M1'][:]=[r for r in prefix.rows['M1'] if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=1)<=cutoff]
        prefix.rows['M5'][:]=[r for r in prefix.rows['M5'] if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=5)<=cutoff]
        prefix.metadata['utc_range']['end']=cutoff.isoformat()
        earlier=run_dataset(prefix,config=CONFIG,intelligence_config=P7,window=20)
        self.assertEqual(a['decision_log']['entries'][:25],earlier['decision_log']['entries'])
    def test_decisions_are_safe_causal_and_have_explanations(self):
        r=self.run_fixture()
        for row in r['decision_log']['entries']:
            self.assertFalse(row['execution_allowed']);self.assertEqual(row['signal'],'WAIT')
            self.assertEqual(row['decision_version'],1)
            for e in row['context_evidence']:self.assertLessEqual(e['available_at'],row['timestamp_utc'])
            if row['abstained']:self.assertTrue(row['reason_codes'])
    def test_decision_log_hash_detects_tampering(self):
        r=self.run_fixture();r['decision_log']['entries'][0]['selected_hypothesis']='changed'
        with self.assertRaises(ValueError):validate_replay_report(r)
    def test_no_profitability_or_broker_access(self):
        r=self.run_fixture()
        self.assertFalse(r['safety']['profitability_tested']);self.assertFalse(r['safety']['broker_access'])
        self.assertEqual(r['safety']['orders_requested'],0)


class HistoricalCLITests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def run_cli(self,args):
        with redirect_stdout(StringIO()) as output:code=main(args)
        return code,output.getvalue()
    def test_missing_independent_dataset_produces_pending_report(self):
        path=self.root/'pending.json';code,_=self.run_cli(['--report-path',str(path)])
        r=json.loads(path.read_text());self.assertEqual(code,3)
        self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['historical_validation'],'PENDING')
    def test_synthetic_cli_and_repeatable_runs(self):
        manifest=write_fixture(self.root)
        outputs=[]
        for name in ('first.json','second.json'):
            path=self.root/name;code,_=self.run_cli(['--manifest',str(manifest),'--report-path',str(path),'--window','25'])
            self.assertEqual(code,2);outputs.append(json.loads(path.read_text()))
        self.assertEqual(outputs[0],outputs[1])
    def test_existing_report_is_never_overwritten(self):
        report=self.root/'existing.json';report.write_text('existing')
        code,_=self.run_cli(['--report-path',str(report)])
        self.assertEqual(code,1);self.assertEqual(report.read_text(),'existing')
    def test_invalid_dataset_leaves_fixed_failure_not_success(self):
        manifest=self.root/'manifest.json';manifest.write_text('private-not-json')
        report=self.root/'failure.json';code,out=self.run_cli(['--manifest',str(manifest),'--report-path',str(report)])
        self.assertEqual(code,1);r=json.loads(report.read_text());self.assertEqual(r['status'],'FAIL')
        self.assertNotIn('private-not-json',out+report.read_text())
    def test_interrupted_run_publishes_fail_closed(self):
        manifest=write_fixture(self.root);report=self.root/'interrupted.json'
        with patch('diagnostics.historical_replay.run_dataset',side_effect=KeyboardInterrupt):
            code,_=self.run_cli(['--manifest',str(manifest),'--report-path',str(report)])
        self.assertEqual(code,1);self.assertEqual(json.loads(report.read_text())['reason_codes'],['REPLAY_INTERRUPTED'])
    def test_failed_atomic_publication_leaves_reserved_fail(self):
        report=self.root/'reserved.json'
        with patch('iat.evidence.os.replace',side_effect=OSError):code,_=self.run_cli(['--report-path',str(report)])
        self.assertEqual(code,1);self.assertEqual(json.loads(report.read_text())['reason_codes'],['RUN_INCOMPLETE'])

class ReplayContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from jsonschema import Draft202012Validator,FormatChecker
        cls.schemas={name:json.loads(Path('config/'+name).read_text()) for name in (
            'historical-dataset-v1.schema.json','decision-log-v1.schema.json','historical-replay-report-v1.schema.json')}
        cls.validators={name:Draft202012Validator(s,format_checker=FormatChecker()) for name,s in cls.schemas.items()}
        for s in cls.schemas.values():Draft202012Validator.check_schema(s)
    def test_bundled_fixture_and_report_contracts(self):
        path=Path('config/examples/replay.synthetic/manifest.json')
        self.validators['historical-dataset-v1.schema.json'].validate(json.loads(path.read_text()))
        result=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7,window=25)
        result=json.loads(json.dumps(result,allow_nan=False))
        self.validators['historical-replay-report-v1.schema.json'].validate(result)
        self.validators['decision-log-v1.schema.json'].validate(result['decision_log'])
    def test_pending_report_schema_and_fixed_safety(self):
        from iat.historical_replay import empty_report
        from jsonschema import ValidationError
        result=empty_report('a'*64);result.update(status='BLOCKED',reason_codes=['INDEPENDENT_DATASET_UNAVAILABLE'])
        self.validators['historical-replay-report-v1.schema.json'].validate(result)
        result['safety']['execution_allowed']=True
        with self.assertRaises(ValidationError):self.validators['historical-replay-report-v1.schema.json'].validate(result)
    def test_synthetic_report_cannot_claim_historical_certification(self):
        result=run_dataset(load_dataset('config/examples/replay.synthetic/manifest.json'),config=CONFIG,intelligence_config=P7)
        result['historical_validation']='DATASET_PIPELINE_CHECKS_PASSED'
        with self.assertRaises(ValueError):validate_replay_report(result)
    def test_future_evidence_and_unknown_versions_rejected(self):
        path=Path('config/examples/replay.synthetic/manifest.json')
        r=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
        decision=next(e for e in r['decision_log']['entries'] if e['context_evidence'])
        raw=copy.deepcopy(decision)
        raw['context_evidence'][0]['available_at']='2099-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError):Decision(**raw)
        for version in (True,2):
            with self.assertRaises(ValueError):Decision(**dict(decision,decision_version=version))
    def test_log_detects_backward_decisions(self):
        r=run_dataset(load_dataset('config/examples/replay.synthetic/manifest.json'),config=CONFIG,intelligence_config=P7)
        decision=Decision(**r['decision_log']['entries'][0])
        with self.assertRaises(ValueError):DecisionLog(1,r['decision_log']['configuration_hashes'],(decision,decision))
    def test_v1_or_unknown_calendar_cannot_authorize_historical_run(self):
        with tempfile.TemporaryDirectory() as folder:
            path=write_fixture(Path(folder),historical=True,calendar=True)
            data=load_dataset(path)
            class Coarse:
                version=1
                def validate_history(self,*args,**kwargs):return None
                def expected_opens(self,*args,**kwargs):return iter(())
            result=run_dataset(replace(data,calendar=Coarse()),config=CONFIG,intelligence_config=P7)
            self.assertEqual(result['status'],'BLOCKED');self.assertIn('SESSION_V2_REQUIRED',result['reason_codes'])
    def test_exness_stays_blocked_with_dataset_finality_attestation(self):
        from iat.session_config import load_session_config
        data=load_dataset('config/examples/replay.synthetic/manifest.json')
        calendar=load_session_config('config/profiles/exness-xauusd-v2.candidate.json')
        result=run_dataset(replace(data,calendar=calendar),config=CONFIG,intelligence_config=P7)
        self.assertEqual(result['status'],'BLOCKED');self.assertIsNone(result['decision_log'])
    def test_invalid_window_cli_is_fixed_failure(self):
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(StringIO()):
            report=Path(folder)/'window.json'
            code=main(['--report-path',str(report),'--window','2'])
            self.assertEqual(code,1);self.assertEqual(json.loads(report.read_text())['reason_codes'],['REPLAY_WINDOW_INVALID'])
