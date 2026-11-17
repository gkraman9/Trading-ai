"""SYNTHETIC Exness-shaped files only; no real broker exports or authentication."""
import ast
import csv
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from hashlib import sha256
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator

from iat.exness_intake import HEADERS,intake_exports
from iat.chart_benchmark import read_json,check_hash
from iat.pilot_preparation import file_fingerprint
from iat.provenance_assessment import assess_historical_provenance,validate_provenance_assessment
from iat.replay_dataset import load_dataset
from diagnostics.intake_exness_exports import main
import iat.exness_intake as module


def fixture(root, *, start='2026-11-12T08:00:00Z', count=150, partial=False, newline='\n'):
    at=datetime.fromisoformat(start.replace('Z','+00:00'));paths={};expected={}
    for tf,minutes in (('M1',1),('M5',5)):
        rows=[]
        for i in range(count//minutes):
            opened=at+timedelta(minutes=i*minutes)
            if partial and minutes==1 and (opened.hour,opened.minute)>=(21,58):continue
            ticks=3 if partial and minutes==5 and opened.hour==21 and opened.minute==55 else minutes
            rows.append(dict(timestamp_utc=opened.isoformat(),open=100,high=101,low=99,close=100,tick_volume=ticks,spread=2,real_volume=0))
        p=root/(tf+' original synthetic.csv');paths[tf]=p
        with p.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=HEADERS,lineterminator=newline);w.writeheader();w.writerows(rows)
        expected[tf]=dict(**file_fingerprint(p),row_count=len(rows))
    return paths,expected,dict(start=at.isoformat(),end=(at+timedelta(minutes=count)).isoformat(),
        evaluation_start=(at+timedelta(minutes=5 if partial else 90)).isoformat())


def full_shape_fixture(root):
    """SYNTHETIC hypothetical Friday closure; never an authenticated broker calendar."""
    paths,expected,_=fixture(root)
    start=datetime(2026,11,11,tzinfo=timezone.utc)
    for tf,minutes in (('M1',1),('M5',5)):
        p=paths[tf];rows=[]
        for i in range(3*1440//minutes):
            opened=start+timedelta(minutes=i*minutes);minute=opened.hour*60+opened.minute
            if minute>=1318 and minute<1380 or opened.day==13 and minute>=1380:continue
            ticks=3 if minutes==5 and minute==1315 else minutes
            rows.append(dict(timestamp_utc=opened.isoformat(),open=100,high=101,low=99,close=100,tick_volume=ticks,spread=2,real_volume=0))
        with p.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=HEADERS,lineterminator='\n');w.writeheader();w.writerows(rows)
        expected[tf]=dict(**file_fingerprint(p),row_count=len(rows))
    window=dict(start='2026-11-11T00:00:00Z',end='2026-11-14T00:00:00Z',evaluation_start='2026-11-11T12:00:00Z')
    return paths,expected,window


def synthetic_summary(report,audit):
    return dict(kind='SYNTHETIC_INTAKE_AUDIT_NOT_REAL_MARKET_VALIDATION',
        assumptions=['CONSTANT_SYNTHETIC_PRICES','HYPOTHETICAL_FRIDAY_NO_REOPEN_NOT_VERIFIED_REAL_SCHEDULE'],
        sources={tf:dict(**source['observed'],row_count=source['row_count']) for tf,source in report['sources'].items()},
        dataset_id=report['dataset_id'],provenance_sha256=report['provenance_sha256'],
        comparable_m5_bars=audit['comparable_m5_bars'],ohlc_mismatches=audit['mismatch_count'],
        tick_volume_mismatches=audit['tick_volume_mismatch_count'],
        complete_ohlc_and_tick_matches=audit['observed_complete_ohlc_and_tick_matches'],
        partial_or_session_uncertain_m5=audit['relayed_partial_m5_count'],
        uncovered_m5_bars=audit['uncovered_m5_bars'],missing_session_candles=audit['missing_session_candle_count'],
        qualification=report['qualification'],historical_validation=report['historical_validation'],
        historical_comparisons=report['historical_comparisons'],exness=report['exness'],safety=report['safety'])


class ExnessIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='iat intake synthetic with spaces ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.paths,self.expected,self.window=fixture(self.root)
        self.output=self.root/'private output'

    def run_intake(self,**overrides):
        args=dict(expected=self.expected,retrieved_at='2026-11-15T00:00:00Z',reference='synthetic:exness-shaped-intake',
            authorized_local_use=True,dataset_kind='SYNTHETIC_FIXTURE',**self.window)
        args.update(overrides)
        return intake_exports(self.paths['M1'],self.paths['M5'],self.output,**args)

    def mutate(self,tf,fn,*,update_expected=True):
        p=self.paths[tf]
        with p.open(newline='') as f:rows=list(csv.DictReader(f))
        fn(rows)
        with p.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=HEADERS,lineterminator='\n');w.writeheader();w.writerows(rows)
        if update_expected:self.expected[tf]=dict(**file_fingerprint(p),row_count=len(rows))

    def safe(self,r):
        check_hash(r)
        self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED');self.assertEqual(r['exness'],'BLOCKED')
        self.assertEqual(r['historical_validation'],'PENDING');self.assertEqual(r['historical_comparisons'],'NOT_RUN')
        self.assertEqual(r['signal'],'WAIT');self.assertFalse(r['execution_allowed'])
        self.assertEqual(r['safety'],dict(mode='READ_ONLY_SHADOW',signal='WAIT',execution_allowed=False,broker_access=False,orders_requested=0,profitability_tested=False))

    def test_prepares_existing_schema_and_binds_exact_originals_without_approval(self):
        before={tf:p.read_bytes() for tf,p in self.paths.items()}
        r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'EVIDENCE_PREPARED')
        manifest=self.output/r['dataset_manifest'];ds=load_dataset(manifest)
        schema=read_json('config/historical-dataset-v2.schema.json');Draft202012Validator(schema).validate(read_json(manifest))
        from iat.qualification_assistant import _spec
        _spec(self.output/'import-spec.json')  # Existing strict import-v1 runtime contract.
        self.assertFalse(ds.finality_attested);self.assertIsNone(ds.calendar)
        self.assertEqual(ds.metadata['lineage']['price_basis'],'UNKNOWN');self.assertEqual(ds.metadata['lineage']['m5_origin'],'UNKNOWN')
        self.assertEqual(ds.metadata['lineage']['feed_id'],'UNKNOWN')
        p=read_json(self.output/'provenance-assessment.json');self.safe(p)
        self.assertEqual(p['input_errors'],[]);self.assertIsNotNone(p['dataset_id'])
        self.assertEqual(next(g for g in p['gaps'] if g['code']=='NORMALIZATION_TRACE')['verification_status'],'VERIFIED')
        self.assertEqual(next(g for g in p['gaps'] if g['code']=='SOURCE_AUTHENTICITY')['verification_status'],'UNVERIFIED')
        self.assertEqual(p['existing_qualification']['status'],'DATA_NOT_QUALIFIED')
        for tf,path in self.paths.items():
            self.assertEqual(path.read_bytes(),before[tf]);self.assertEqual((self.output/'candidate-package/source'/(tf.lower()+'.csv')).read_bytes(),before[tf])
        for name,checksum in r['artifact_hashes'].items():self.assertEqual(sha256((self.output/name).read_bytes()).hexdigest(),checksum)

    def test_repeatability_and_exact_decimal_volume_comparison(self):
        a=self.run_intake();self.output=self.root/'other output';b=self.run_intake()
        self.assertEqual(a,b)
        audit=read_json(self.output/'alignment-audit.json');self.assertEqual(audit['comparable_m5_bars'],30)
        self.assertEqual(audit['observed_complete_ohlc_and_tick_matches'],30);self.assertEqual(audit['tick_volume_mismatch_count'],0)
        self.assertEqual(audit['operator_count_assertion_status'],'NOT_APPLICABLE')

    def test_modified_source_bytes_fail_exact_fingerprint(self):
        self.mutate('M1',lambda rows:rows[0].update(close=100.5),update_expected=False)
        r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'BLOCKED')
        self.assertEqual(r['error_detail'],'SOURCE_FINGERPRINT_MISMATCH');self.assertIsNone(r['dataset_id'])
        self.assertFalse((self.output/'candidate-package').exists())

    def test_wrong_row_or_byte_count_rejects(self):
        for field in ('row_count','byte_count'):
            with self.subTest(field=field):
                self.output=self.root/field;self.expected['M1'][field]+=1
                r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'BLOCKED')
                self.expected['M1'][field]-=1

    def test_missing_source_fails_closed(self):
        self.paths['M1'].unlink();r=self.run_intake();self.safe(r)
        self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['error_detail'],'SOURCE_UNAVAILABLE_OR_UNSAFE')

    def test_duplicate_timestamps_reject_without_deduplication(self):
        self.mutate('M1',lambda rows:rows.__setitem__(1,dict(rows[0])))
        r=self.run_intake();self.safe(r);self.assertEqual(r['error_detail'],'TIMESTAMP_DUPLICATE')

    def test_out_of_order_reject_without_sorting(self):
        self.mutate('M1',lambda rows:rows.__setitem__(slice(0,2),[rows[1],rows[0]]))
        r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'BLOCKED')
        self.assertIn('TIMESTAMP_OUT_OF_ORDER',r['sources']['M1']['scan']['errors'])

    def test_invalid_ohlc_and_nonfinite_prices_reject(self):
        for value in ('0','-1','NaN','Infinity','102'):
            with self.subTest(value=value):
                self.paths,self.expected,self.window=fixture(self.root);self.output=self.root/('bad'+value)
                self.mutate('M1',lambda rows:rows[0].update(close=value))
                r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'BLOCKED')
                self.assertIn('OHLC_INVALID',r['sources']['M1']['scan']['errors'])

    def test_auxiliary_fields_require_finite_nonnegative_values(self):
        for field in ('tick_volume','spread','real_volume'):
            for value in ('NaN','Infinity','-1',''):
                with self.subTest(field=field,value=value):
                    self.paths,self.expected,self.window=fixture(self.root);self.output=self.root/(field+value)
                    self.mutate('M1',lambda rows:rows[0].update({field:value}))
                    r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'BLOCKED')

    def test_headers_order_missing_and_duplicate_columns_reject(self):
        for index,header in enumerate((HEADERS[::-1],HEADERS[:-1],HEADERS[:-1]+['spread'])):
            self.paths,self.expected,self.window=fixture(self.root);self.output=self.root/('header'+str(index))
            p=self.paths['M1'];lines=p.read_bytes().splitlines();p.write_bytes((','.join(header)+'\n').encode()+b'\n'.join(lines[1:])+b'\n')
            self.expected['M1'].update(file_fingerprint(p));r=self.run_intake();self.safe(r)
            self.assertEqual(r['error_detail'],'EXPORT_HEADER_ORDER_INVALID')

    def test_utc_timezone_ambiguity_and_timeframe_alignment_reject(self):
        for index,stamp in enumerate(('2026-11-12T08:00:00','2026-11-12T09:00:00+01:00','2026-11-12T08:00:30Z')):
            self.paths,self.expected,self.window=fixture(self.root);self.output=self.root/('stamp'+str(index))
            self.mutate('M1',lambda rows:rows[0].update(timestamp_utc=stamp))
            r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'BLOCKED')

    def test_missing_m1_and_m5_slots_are_not_assumed_missing_broker_candles(self):
        self.mutate('M1',lambda rows:rows.pop(10));self.mutate('M5',lambda rows:rows.pop(4))
        r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'EVIDENCE_PREPARED')
        audit=read_json(self.output/'alignment-audit.json');self.assertIsNone(audit['missing_session_candle_count'])
        self.assertEqual(audit['uncovered_m5_bars'],1)
        self.assertIsNone(read_json(self.output/'provenance-assessment.json')['mechanical']['frames']['M1']['missing_declared_calendar_ordinary_intervals'])

    def test_ohlc_and_volume_mismatch_remain_explicit_contradictions(self):
        self.mutate('M5',lambda rows:rows[0].update(close='100.5',tick_volume='6'))
        r=self.run_intake();self.safe(r);self.assertEqual(r['mechanical_status'],'CONFLICTS')
        audit=read_json(self.output/'alignment-audit.json');self.assertEqual(audit['mismatch_count'],1)
        self.assertEqual(audit['tick_volume_mismatch_count'],1)
        p=read_json(self.output/'provenance-assessment.json')
        self.assertEqual(next(g for g in p['gaps'] if g['code']=='CROSS_FRAME_CONSISTENCY')['verification_status'],'CONTRADICTED')

    def test_partial_2155_interval_not_filled_or_compared_as_five_bars(self):
        self.paths,self.expected,self.window=fixture(self.root,start='2026-11-12T21:40:00Z',count=20,partial=True)
        r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'EVIDENCE_PREPARED')
        audit=read_json(self.output/'alignment-audit.json');self.assertEqual(audit['comparable_m5_bars'],3)
        last=audit['comparisons'][-1];self.assertEqual(last['m1_count'],3)
        self.assertEqual(last['classification'],'RELAYED_PARTIAL_OR_SESSION_UNCERTAIN')
        self.assertIsNone(last['ohlc_match']);self.assertIsNone(last['tick_volume_match'])
        self.assertEqual(audit['relayed_partial_m5_count'],1)

    def test_no_quote_or_opening_permissions_inferred_for_friday_or_close_only(self):
        for day in ('2026-11-12','2026-11-13'):
            self.paths,self.expected,self.window=fixture(self.root,start=day+'T23:00:00Z',count=150)
            self.output=self.root/day;r=self.run_intake(retrieved_at='2026-11-15T00:00:00Z');self.safe(r)
            p=read_json(self.output/'provenance-assessment.json')
            observations=p['broker_comparison']['observations'];self.assertTrue(observations)
            self.assertTrue(all(o['new_position_permission'] is not True for o in observations))
            if day.endswith('13'):self.assertTrue(any(o['classification']=='FRIDAY_REOPEN_UNRESOLVED' for o in observations))

    def test_source_changes_between_inspection_and_copy_are_detected(self):
        original=module.prepare_package
        def changing(*a,**k):
            result=original(*a,**k);self.paths['M1'].write_bytes(self.paths['M1'].read_bytes()+b'\n');return result
        with patch.object(module,'prepare_package',side_effect=changing):r=self.run_intake()
        self.safe(r);self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['error_detail'],'SOURCE_CHANGED_DURING_INTAKE')

    def test_candidate_manifest_checksum_mismatch_is_not_bypassed(self):
        original=module.prepare_package
        def changing(*a,**k):
            result=original(*a,**k);p=self.output/'candidate-package/m1.csv';p.write_bytes(p.read_bytes()+b'\n');return result
        with patch.object(module,'prepare_package',side_effect=changing):r=self.run_intake()
        self.safe(r);self.assertEqual(r['status'],'BLOCKED');self.assertIn('DATASET_CHECKSUM_MISMATCH',r['reason_codes'])

    def test_broker_evidence_reference_mismatch_blocks_preparation(self):
        original=module.write_new
        def changing(path,value):
            if Path(path).name=='broker-binding.json':value=dict(value,dataset_id='0'*64)
            return original(path,value)
        with patch.object(module,'write_new',side_effect=changing):r=self.run_intake()
        self.safe(r);self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['error_detail'],'PREPARED_EVIDENCE_REFERENCE_INVALID')

    def test_existing_output_is_not_modified(self):
        self.output.mkdir();marker=self.output/'existing.txt';marker.write_bytes(b'keep')
        with self.assertRaises(ValueError):self.run_intake()
        self.assertEqual(marker.read_bytes(),b'keep');self.assertEqual(len(list(self.output.iterdir())),1)

    def test_authorization_required_and_no_automatic_approval(self):
        with self.assertRaises(ValueError):self.run_intake(authorized_local_use=False)
        self.assertFalse(self.output.exists())

    def test_line_endings_preserve_original_bytes_but_normalize_only_new_ohlc_outputs(self):
        a=self.run_intake();one=(self.output/'candidate-package/m1.csv').read_bytes()
        self.paths,self.expected,self.window=fixture(self.root,newline='\r\n');self.output=self.root/'CRLF output'
        b=self.run_intake();self.safe(b)
        self.assertNotEqual(a['sources']['M1']['observed']['sha256'],b['sources']['M1']['observed']['sha256'])
        self.assertEqual((self.output/'candidate-package/m1.csv').read_bytes(),one)
        self.assertIn(b'\r\n',(self.output/'candidate-package/source/m1.csv').read_bytes())

    def test_metadata_only_reference_conflict_reproduces_without_csv_corruption_claim(self):
        r=assess_historical_provenance('config/examples/historical-evidence/operator-manifest-v1.json')
        self.safe(r);self.assertIsNone(r['inventory']);self.assertIsNone(r['mechanical'])
        self.assertEqual(r['input_errors'],[dict(scope='manifest',code='EVIDENCE_MANIFEST_NOT_REPLAY_ELIGIBLE')])
        g=next(g for g in r['gaps'] if g['code']=='EVIDENCE_REFERENCES')
        self.assertEqual((g['verification_status'],g['blocking_reason']),('CONTRADICTED','EVIDENCE_REFERENCE_CONFLICT'))
        validate_provenance_assessment(r,'config/examples/historical-evidence/operator-manifest-v1.json')

    def test_cli_exit_three_is_prepared_not_qualified_and_one_is_failure(self):
        args=['--m1',str(self.paths['M1']),'--m5',str(self.paths['M5']),'--output-directory',str(self.output),
              '--start-utc',self.window['start'],'--end-utc',self.window['end'],'--evaluation-start-utc',self.window['evaluation_start'],
              '--retrieved-at-utc','2026-11-15T00:00:00Z','--source-reference','synthetic:exness-shaped-intake','--authorized-local-use','--synthetic-fixture']
        for tf in ('M1','M5'):
            for key,flag in (('sha256','sha256'),('byte_count','bytes'),('row_count','rows')):args+=['--'+tf.lower()+'-'+flag,str(self.expected[tf][key])]
        with redirect_stdout(StringIO()) as stdout:self.assertEqual(main(args),3)
        self.assertNotIn(str(self.paths['M1']),stdout.getvalue())
        with redirect_stdout(StringIO()):self.assertEqual(main(args),1)

    def test_intake_has_no_network_terminal_credentials_or_trading_imports(self):
        for path in ('iat/exness_intake.py','diagnostics/intake_exness_exports.py'):
            tree=ast.parse(Path(path).read_text(encoding='utf-8'))
            modules=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            modules += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any(any(bad in n.lower() for bad in ('metatrader','socket','requests','urllib','broker','credential')) for n in modules))

    def test_declared_historical_path_still_has_blocked_preflight_and_no_authentication(self):
        # Synthetic bytes exercise the real-input declaration path, not a historical validation claim.
        r=self.run_intake(dataset_kind='INDEPENDENT_HISTORICAL',reference='https://www.exness.com/')
        self.safe(r);self.assertEqual(r['status'],'EVIDENCE_PREPARED')
        p=read_json(self.output/'provenance-assessment.json');self.safe(p)
        self.assertEqual(p['existing_preflight']['status'],'BLOCKED')
        self.assertEqual(p['existing_qualification']['status'],'DATA_NOT_QUALIFIED')
        self.assertEqual(p['inventory']['frames']['M1']['original_import_sha256'],self.expected['M1']['sha256'])

    def test_missing_and_extra_row_fields_reject_without_repair(self):
        for index,change in enumerate((lambda line:line.rsplit(b',',1)[0],lambda line:line+b',extra')):
            self.paths,self.expected,self.window=fixture(self.root);self.output=self.root/('fields'+str(index))
            p=self.paths['M1'];lines=p.read_bytes().splitlines();lines[1]=change(lines[1]);p.write_bytes(b'\n'.join(lines)+b'\n')
            self.expected['M1'].update(file_fingerprint(p));r=self.run_intake();self.safe(r)
            self.assertEqual(r['status'],'BLOCKED');self.assertEqual(r['error_detail'],'EXPORT_MISSING_OR_EXTRA_FIELDS')

    def test_full_size_synthetic_boundary_shape_not_a_real_dataset_validation(self):
        # Deliberately models one possible Friday closure, not proof of the real schedule.
        self.paths,self.expected,self.window=full_shape_fixture(self.root)
        self.assertEqual((self.expected['M1']['row_count'],self.expected['M5']['row_count']),(4074,816))
        r=self.run_intake();self.safe(r);self.assertEqual(r['status'],'EVIDENCE_PREPARED')
        a=read_json(self.output/'alignment-audit.json')
        self.assertEqual((a['observed_complete_ohlc_and_tick_matches'],a['relayed_partial_m5_count']),(813,3))
        self.assertEqual(a['mismatch_count'],0);self.assertEqual(a['uncovered_m5_bars'],3)
        self.assertEqual(a['operator_count_assertion_status'],'NOT_APPLICABLE')

        summary=synthetic_summary(r,a)
        self.assertEqual(summary,read_json('docs/research_audits/exness-intake-synthetic-v1.json'))
