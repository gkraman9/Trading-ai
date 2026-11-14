"""Synthetic-only evaluation scope and coverage claims; no network or real-data fixtures."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import csv,json,copy,tempfile,unittest
from pathlib import Path
from hashlib import sha256
from jsonschema import Draft202012Validator,FormatChecker
from iat.replay_dataset import load_dataset,DatasetError
from iat.historical_replay import run_dataset,alignment_check,validate_replay_report
from iat.tick_sample import aggregate_bid_ticks
from test_historical_replay import write_fixture,rewrite,recalc
from test_intelligence_patterns import START
from test_context_components import CONFIG
from test_context_engine import P7


def v2_fixture(root,*,count=120,evaluation_minutes=60,historical=False,calendar=False,origin='AGGREGATED_FROM_M1'):
    path=write_fixture(root,count=count,historical=historical,calendar=calendar)
    data=json.loads(path.read_text())
    start=START+timedelta(minutes=count-evaluation_minutes)
    data.update(version=2,evaluation={'start':start.isoformat(),'end':(START+timedelta(minutes=count)).isoformat()},
        warmup={tf:{'start':START.isoformat(),'end':start.isoformat()} for tf in ('M1','M5')},
        lineage={'feed_id':'SYNTHETIC_UNIT_FIXTURE','price_basis':'BID','timestamp_convention':'INTERVAL_OPEN_UTC',
                 'm5_origin':origin,'raw_sha256':data['frames']['M1']['sha256']},
        evidence_review={key:{'status':'VERIFIED','reference':'https://example.org/synthetic-mock-evidence',
                             'reason_code':'SYNTHETIC_MOCK_REVIEW'} for key in ('usage','instrument','timestamp','price_basis','calendar','finality')})
    path.write_text(json.dumps(data));return path


def trim_csv(path,tf,first_minute):
    p=path.parent/(tf.lower()+'.csv')
    with p.open(newline='') as f:rows=list(csv.DictReader(f))
    rows=[r for r in rows if datetime.fromisoformat(r['timestamp'])>=START+timedelta(minutes=first_minute)]
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['timestamp','open','high','low','close'],lineterminator='\n');w.writeheader();w.writerows(rows)
    recalc(path,tf)
    rewrite(path,lambda m:m['warmup'][tf].update(start=(START+timedelta(minutes=first_minute)).isoformat()))


class EvaluationWindowTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_one_comparable_m5_bar_cannot_establish_validation_claim(self):
        path=v2_fixture(self.root,count=15,evaluation_minutes=5,historical=True,calendar=True,origin='NATIVE_SAME_FEED')
        # Two preceding M5 bars are warm-up, not extra evaluation evidence.
        result=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
        coverage=result['preflight']['alignment']['evaluation']
        self.assertEqual(coverage['expected_m5_bars'],1);self.assertEqual(coverage['comparable_m5_bars'],1)
        self.assertEqual(coverage['comparable_coverage_percent'],100)
        self.assertFalse(coverage['coverage_sufficient']);self.assertEqual(coverage['cross_frame_claim'],'NOT_ESTABLISHED')
        self.assertEqual(result['historical_validation'],'PENDING')
        self.assertEqual(result['summary']['snapshots'],5);self.assertEqual(result['summary']['warmup_snapshots'],10)
    def test_legitimate_m5_warmup_before_m1_does_not_reduce_evaluation_coverage(self):
        path=v2_fixture(self.root,historical=True,calendar=True,origin='NATIVE_SAME_FEED')
        trim_csv(path,'M1',30)
        d=load_dataset(path);result=run_dataset(d,config=CONFIG,intelligence_config=P7)
        global_check=result['preflight']['alignment'];scope=global_check['evaluation']
        self.assertEqual(global_check['uncovered_m5_bars'],6)
        self.assertEqual(scope['warmup_uncovered_m5_bars'],6)
        self.assertEqual(scope['uncovered_m5_bars'],0);self.assertEqual(scope['comparable_m5_bars'],12)
        self.assertEqual(scope['comparable_coverage_percent'],100)
        self.assertEqual(scope['cross_frame_claim'],'SCOPED_SAME_FEED_CONSISTENCY')
    def test_internal_aggregation_is_never_independent_cross_frame_validation(self):
        path=v2_fixture(self.root,historical=True,calendar=True)
        scope=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)['preflight']['alignment']['evaluation']
        self.assertTrue(scope['coverage_sufficient'])
        self.assertEqual(scope['consistency_evidence'],'INTERNAL_AGGREGATION_ONLY')
        self.assertEqual(scope['cross_frame_claim'],'NOT_ESTABLISHED')
    def test_declared_warmup_is_not_counted_as_evaluation_snapshots(self):
        path=v2_fixture(self.root)
        r=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
        self.assertEqual(r['summary']['snapshots'],60);self.assertEqual(r['summary']['warmup_snapshots'],60)
        rows=r['decision_log']['entries'];self.assertEqual(len(rows),120)
        self.assertTrue(all(d['phase']=='WARMUP' for d in rows[:60]))
        self.assertTrue(all(d['phase']=='EVALUATION' for d in rows[60:]))
        events={e['event_id'] for row in rows[60:] for e in row['context_evidence'] if e['event_id']}
        self.assertEqual(r['summary']['unique_choch_events'],len(events))
    def test_unreviewed_evidence_blocks_before_decisions_but_keeps_coverage(self):
        path=v2_fixture(self.root,historical=True)
        rewrite(path,lambda m:m['evidence_review']['finality'].update(status='PENDING',reason_code='CAPTURE_CONTRACT_UNKNOWN'))
        result=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
        self.assertEqual(result['status'],'BLOCKED');self.assertIsNone(result['decision_log'])
        self.assertIn('EVIDENCE_FINALITY_PENDING',result['reason_codes'])
        self.assertEqual(result['summary']['execution_status'],'NOT_RUN')
        self.assertEqual(result['summary']['snapshots'],0)
        self.assertEqual(result['preflight']['alignment']['evaluation']['comparable_m5_bars'],12)
    def test_pending_independent_review_cannot_claim_native_comparison(self):
        path=v2_fixture(self.root,historical=True,calendar=True,origin='NATIVE_SAME_FEED')
        rewrite(path,lambda m:m['source'].update(independent_review='PENDING'))
        r=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
        self.assertEqual(r['preflight']['alignment']['evaluation']['cross_frame_claim'],'NOT_ESTABLISHED')
    def test_missing_evaluation_m5_bar_reduces_coverage(self):
        path=v2_fixture(self.root);d=load_dataset(path)
        d.rows['M5'][:]=[r for r in d.rows['M5'] if datetime.fromisoformat(r['timestamp'])!=START+timedelta(minutes=90)]
        scope=alignment_check(d,1e-8)['evaluation']
        self.assertEqual(scope['missing_m5_bars'],1);self.assertAlmostEqual(scope['comparable_coverage_percent'],100*11/12)
        self.assertFalse(scope['coverage_sufficient'])
    def test_uncovered_evaluation_m5_bar_does_not_inflate_comparability(self):
        path=v2_fixture(self.root);d=load_dataset(path)
        del d.rows['M1'][90]
        scope=alignment_check(d,1e-8)['evaluation']
        self.assertEqual(scope['uncovered_m5_bars'],1);self.assertEqual(scope['comparable_m5_bars'],11)
    def test_misaligned_scope_and_false_warmup_rejected(self):
        for defect in ('alignment','warmup','coverage'):
            path=v2_fixture(self.root)
            if defect=='alignment':rewrite(path,lambda m:m['evaluation'].update(start=(START+timedelta(minutes=61)).isoformat()))
            elif defect=='warmup':rewrite(path,lambda m:m['warmup']['M5'].update(end=(START+timedelta(minutes=55)).isoformat()))
            else:rewrite(path,lambda m:m['warmup']['M1'].update(start=(START+timedelta(minutes=5)).isoformat()))
            with self.subTest(defect=defect),self.assertRaises(DatasetError):load_dataset(path)
    def test_invalid_review_cannot_be_verified_without_reference(self):
        path=v2_fixture(self.root);rewrite(path,lambda m:m['evidence_review']['usage'].update(reference=None))
        with self.assertRaisesRegex(DatasetError,'EVIDENCE_REFERENCE_REQUIRED'):load_dataset(path)
    def test_repeat_and_prefix_preserve_decision_entries_with_scope(self):
        path=v2_fixture(self.root,count=90,evaluation_minutes=30)
        data=load_dataset(path);a=run_dataset(data,config=CONFIG,intelligence_config=P7)
        b=run_dataset(data,config=CONFIG,intelligence_config=P7)
        self.assertEqual(a['decision_log_sha256'],b['decision_log_sha256'])
        prefix=copy.deepcopy(data);cutoff=START+timedelta(minutes=80)
        prefix.rows['M1'][:]=prefix.rows['M1'][:80];prefix.rows['M5'][:]=prefix.rows['M5'][:16]
        prefix.metadata['utc_range']['end']=cutoff.isoformat();prefix.metadata['evaluation']['end']=cutoff.isoformat()
        c=run_dataset(prefix,config=CONFIG,intelligence_config=P7)
        self.assertEqual(a['decision_log']['entries'][:80],c['decision_log']['entries'])
    def test_updated_schemas_accept_v2_and_do_not_weaken_safety(self):
        path=v2_fixture(self.root);d=load_dataset(path)
        schema=json.loads(Path('config/historical-dataset-v2.schema.json').read_text())
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(json.loads(path.read_text()))
        result=run_dataset(d,config=CONFIG,intelligence_config=P7)
        schema=json.loads(Path('config/historical-replay-report-v1.schema.json').read_text())
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(json.loads(json.dumps(result)))
        self.assertEqual(result['safety']['signal'],'WAIT');self.assertFalse(result['safety']['execution_allowed'])
    def test_synthetic_review_flags_cannot_grant_real_source_claim(self):
        path=v2_fixture(self.root,calendar=True,origin='NATIVE_SAME_FEED')
        r=run_dataset(load_dataset(path),config=CONFIG,intelligence_config=P7)
        self.assertEqual(r['historical_validation'],'PENDING')
        self.assertEqual(r['preflight']['alignment']['evaluation']['cross_frame_claim'],'NOT_ESTABLISHED')


class BidAggregationTests(unittest.TestCase):
    def ticks(self):
        values=[]
        for i in range(10):
            at=START+timedelta(minutes=i)
            values.extend([{'timestamp':at,'bid_price':100+i},{'timestamp':at+timedelta(seconds=30),'bid_price':101+i}])
        values.append({'timestamp':START+timedelta(minutes=10),'bid_price':999})
        return values
    def test_actual_tick_order_forms_open_high_low_close(self):
        one,five,audit=aggregate_bid_ticks(self.ticks(),START,START+timedelta(minutes=10))
        self.assertEqual(len(one),10);self.assertEqual(len(five),2)
        self.assertEqual((five[0]['open'],five[0]['high'],five[0]['low'],five[0]['close']),(100,105,100,105))
        self.assertEqual(audit['finality_claim'],'INTERVAL_ELAPSED_ONLY_CAPTURE_COMPLETENESS_PENDING')
    def test_missing_minute_is_not_filled(self):
        ticks=[t for t in self.ticks() if t['timestamp'].minute!=2]
        with self.assertRaises(ValueError):aggregate_bid_ticks(ticks,START,START+timedelta(minutes=10))
    def test_backward_ticks_and_bad_prices_fail(self):
        for defect in ('order','price'):
            ticks=self.ticks()
            if defect=='order':ticks[2],ticks[3]=ticks[3],ticks[2]
            else:ticks[2]['bid_price']=float('nan')
            with self.assertRaises(ValueError):aggregate_bid_ticks(ticks,START,START+timedelta(minutes=10))
    def test_no_boundary_tick_cannot_establish_elapsed_sample(self):
        with self.assertRaises(ValueError):aggregate_bid_ticks(self.ticks()[:-1],START,START+timedelta(minutes=10))
    def test_later_tick_cannot_change_completed_bars(self):
        a=aggregate_bid_ticks(self.ticks(),START,START+timedelta(minutes=10))[0:2]
        ticks=self.ticks();ticks[-1]['bid_price']=1
        b=aggregate_bid_ticks(ticks,START,START+timedelta(minutes=10))[0:2]
        self.assertEqual(a,b)

class ReplayComparisonTests(unittest.TestCase):
    def test_missing_logs_never_count_as_matching_replay_hashes(self):
        from iat.historical_replay import empty_report
        from iat.replay_comparison import compare_reports
        r=empty_report('a'*64);r.update(status='BLOCKED',reason_codes=['INDEPENDENT_DATASET_UNAVAILABLE'])
        result=compare_reports(r,r,r)
        self.assertTrue(result['repeated_report_identical'])
        self.assertEqual(result['repeatability']['status'],'NOT_RUN')
        self.assertIsNone(result['repeatability']['equal']);self.assertIsNone(result['prefix_equivalence']['differences'])
    def test_actual_synthetic_logs_have_repeatability_and_prefix_comparison(self):
        from iat.replay_comparison import compare_reports
        with tempfile.TemporaryDirectory() as folder:
            path=write_fixture(Path(folder),count=30);data=load_dataset(path)
            a=run_dataset(data,config=CONFIG,intelligence_config=P7)
            b=run_dataset(data,config=CONFIG,intelligence_config=P7)
            prefix=copy.deepcopy(data);prefix.rows['M1'][:]=prefix.rows['M1'][:25];prefix.rows['M5'][:]=prefix.rows['M5'][:5]
            prefix.metadata['utc_range']['end']=(START+timedelta(minutes=25)).isoformat()
            p=run_dataset(prefix,config=CONFIG,intelligence_config=P7)
            compared=compare_reports(a,b,p)
            self.assertEqual(compared['repeatability']['status'],'PASS')
            self.assertEqual(compared['prefix_equivalence']['compared_decisions'],25)
            self.assertEqual(compared['prefix_equivalence']['differences'],0)
    def test_default_analytical_threshold_hashes_unchanged(self):
        from iat.intelligence.context_models import ContextConfig
        from iat.intelligence.models import IntelligenceConfig
        self.assertEqual(ContextConfig().digest,'d8bda7da1af47cc1f1f349682b71ca75f39bef89b7fb5d5873bc0bba5510d424')
        self.assertEqual(IntelligenceConfig().digest,'0b1db8f78abc3801b23a2aec62ee6057a1b0b711a8244405bc5f77ff582653ff')

class PublishedSourceReviewTests(unittest.TestCase):
    def test_published_pending_audit_is_schema_valid_without_raw_prices(self):
        audit=json.loads(Path('docs/source_reviews/xauusd-pilot-review.json').read_text())
        schema=json.loads(Path('config/historical-replay-report-v1.schema.json').read_text())
        for name in ('first_attempt','prefix_attempt'):
            r=audit[name];Draft202012Validator(schema,format_checker=FormatChecker()).validate(r)
            validate_replay_report(r)
            self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['decision_log'])
            self.assertEqual(r['summary']['snapshots'],0)
        self.assertFalse(audit['raw_data_published'])
    def test_candidate_manifest_exact_hash_and_coverage(self):
        raw=Path('docs/source_reviews/xauusd-pilot.manifest.json').read_bytes()
        manifest=json.loads(raw)
        schema=json.loads(Path('config/historical-dataset-v2.schema.json').read_text())
        Draft202012Validator(schema,format_checker=FormatChecker()).validate(manifest)
        audit=json.loads(Path('docs/source_reviews/xauusd-pilot-review.json').read_text())
        self.assertEqual(sha256(raw).hexdigest(),audit['first_attempt']['dataset']['manifest_sha256'])
        scope=audit['first_attempt']['preflight']['alignment']['evaluation']
        self.assertEqual(scope['comparable_m5_bars'],12);self.assertEqual(scope['uncovered_m5_bars'],0)
        self.assertEqual(scope['cross_frame_claim'],'NOT_ESTABLISHED')
    def test_unexecuted_comparisons_are_explicitly_not_passed(self):
        audit=json.loads(Path('docs/source_reviews/xauusd-pilot-review.json').read_text())
        result=audit['decision_log_comparison']
        self.assertTrue(result['repeated_report_identical'])
        self.assertEqual(result['repeatability']['status'],'NOT_RUN')
        self.assertEqual(result['prefix_equivalence']['status'],'NOT_RUN')
        self.assertIsNone(result['prefix_equivalence']['differences'])
