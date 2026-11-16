"""Deterministic SYNTHETIC_ONLY, native-shaped CSV fixtures. No real feed claims."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from io import StringIO
from pathlib import Path
import csv,json,tempfile,unittest
from unittest.mock import patch
from iat.qualification_assistant import validate_import,prepare_package,assess_candidate,inspect_csv
from iat.chart_benchmark import read_json,write_new,hashed
from iat.replay_dataset import load_dataset
from iat.intelligence.strategy_replay import digest
from diagnostics.qualification_assistant import main
from test_session_v2 import synthetic_v2
from iat.pilot_qualification import ITEMS


def export_fixture(root,*,count=150,warmup=90):
    """Both files are constructed separately from constant synthetic OHLC, not a real native feed."""
    start=datetime(2026,11,12,8,tzinfo=timezone.utc);end=start+timedelta(minutes=count);evaluate=start+timedelta(minutes=warmup)
    frames={}
    for tf,minutes in (('M1',1),('M5',5)):
        filename=tf.lower()+'-native-shaped.csv'
        with (root/filename).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['Time','Open','High','Low','Close','Ticks','Done'],lineterminator='\n');w.writeheader()
            for i in range(count//minutes):w.writerow({'Time':(start+timedelta(minutes=i*minutes)).isoformat(),'Open':100,'High':101,'Low':99,'Close':100,'Ticks':10,'Done':'true'})
        frames[tf]={'file':filename,'columns':{'timestamp':'Time','open':'Open','high':'High','low':'Low','close':'Close','volume':'Ticks','complete':'Done','symbol':None,'price_basis':None,'feed_id':None},
            'ignored_columns':[],'price_basis':'BID','feed_id':'SYNTHETIC_NATIVE_SHAPED','origin':'NATIVE_SAME_FEED','volume_kind':'TICK',
            'finality':{'policy':'PER_ROW_BOOLEAN','provider_contract':'MT5_POSITION_1_ELAPSED','true_token':'true','false_token':'false','reference':'synthetic:mock-export-contract'},
            'corrections':{'status':'NO_KNOWN_CORRECTIONS_DECLARED','reference':None,'previous_source_sha256':None}}
    cal=root/'calendar.json';cal.write_text(json.dumps(synthetic_v2()),encoding='utf-8',newline='\n')
    doc=root/'synthetic-evidence.txt';doc.write_bytes(b'SYNTHETIC ONLY; not permission, provider documentation or independent review.')
    spec={'import_version':1,'dataset_kind':'SYNTHETIC_FIXTURE','preparer_code':'operator-a','authorized_local_use':True,
        'source':{'provider_entity':'SYNTHETIC MOCK EXPORT','feed_id':'SYNTHETIC_NATIVE_SHAPED','instrument':'XAUUSD','price_basis':'BID',
            'reference':'synthetic:qualification-assistant-fixture','retrieved_at_utc':'2026-11-13T00:00:00Z','curation_id':'synthetic-native-shaped'},
        'timestamp':{'format':'ISO8601','timezone':'UTC','convention':'INTERVAL_OPEN_UTC'},
        'utc_range':{'start':start.isoformat(),'end':end.isoformat()},'evaluation':{'start':evaluate.isoformat(),'end':end.isoformat()},
        'warmup':{tf:{'start':start.isoformat(),'end':evaluate.isoformat()} for tf in frames},'frames':frames,
        'calendar':{'file':cal.name,'sha256':sha256(cal.read_bytes()).hexdigest()},
        'evidence':{k:{'file':doc.name,'sha256':sha256(doc.read_bytes()).hexdigest(),'reference':'synthetic:mock-document-not-evidence'} for k in ITEMS}}
    path=root/'import.json';save(path,spec);return path


def save(path,value):path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8',newline='\n')


def modify_csv(path,tf,change):
    spec=json.loads(path.read_text());csvpath=path.parent/spec['frames'][tf]['file']
    with csvpath.open(newline='',encoding='utf-8') as f:reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    change(rows)
    with csvpath.open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)


class QualificationAssistantTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=export_fixture(self.root)
    def tearDown(self):self.temp.cleanup()
    def change(self,fn):s=read_json(self.path);fn(s);save(self.path,s)
    def codes(self,r):return {i['code'] for i in r['issues']}
    def test_valid_native_shaped_export_mechanical_only_never_approved(self):
        r=validate_import(self.path)
        self.assertEqual(r['mechanical']['status'],'PASS',r['issues']);self.assertEqual(r['classification'],'SYNTHETIC_ONLY')
        self.assertEqual(r['status'],'DATA_NOT_QUALIFIED');self.assertTrue(r['candidate_available'])
        self.assertEqual(r['mechanical']['alignment']['evaluation']['comparable_m5_bars'],12)
        self.assertEqual(r['mechanical']['warmup']['closed_counts'],{'M1':90,'M5':18})
        self.assertEqual(r['independent_signoff']['decision'],'PENDING');self.assertIn('INDEPENDENT_REVIEW_REQUIRED',self.codes(r))
        self.assertEqual(r['gate']['status'],'DATA_NOT_QUALIFIED');self.assertEqual(r['historical_comparisons'],'NOT_RUN')
    def test_missing_m1_and_m5_intervals_and_duplicates_are_not_repaired(self):
        for tf,kind in (('M1','missing'),('M5','missing'),('M1','duplicate'),('M5','duplicate'),('M1','out-of-order')):
            self.path=export_fixture(self.root)
            if kind=='missing':modify_csv(self.path,tf,lambda rows:rows.pop(5))
            elif kind=='duplicate':modify_csv(self.path,tf,lambda rows:rows.insert(5,dict(rows[4])))
            else:modify_csv(self.path,tf,lambda rows:rows.__setitem__(slice(4,6),list(reversed(rows[4:6]))))
            r=validate_import(self.path)
            with self.subTest(tf=tf,kind=kind):
                self.assertEqual(r['mechanical']['status'],'BLOCKED')
                self.assertTrue(self.codes(r)&{'GAP_UNVERIFIED','CANDLES_MISSING','UNEXPECTED_MISSING_BARS','TIMESTAMP_DUPLICATE','TIMESTAMP_OUT_OF_ORDER'})
    def test_conflicting_cross_frame_ohlc_and_malformed_ohlc(self):
        modify_csv(self.path,'M5',lambda rows:rows[20].update(High='105'))
        r=validate_import(self.path);self.assertIn('M1_M5_ALIGNMENT_UNESTABLISHED',self.codes(r))
        self.assertGreater(r['mechanical']['alignment']['mismatch_count'],0)
        modify_csv(self.path,'M1',lambda rows:rows[5].update(High='98'))
        self.assertIn('OHLC_INVALID',self.codes(validate_import(self.path)))
    def test_naive_offset_and_dst_ambiguous_timestamps_reject(self):
        for stamp in ('2026-11-12T08:00:00','2026-11-12T10:00:00+02:00','2026-11-01T01:30:00'):
            self.path=export_fixture(self.root);modify_csv(self.path,'M1',lambda rows:rows[0].update(Time=stamp))
            self.assertIn('UTC_TIMESTAMP_REQUIRED',self.codes(validate_import(self.path)))
        self.change(lambda s:s['timestamp'].update(timezone='America/New_York'))
        self.assertIn('LOCAL_TIME_UNSUPPORTED',self.codes(validate_import(self.path)))
    def test_inconsistent_basis_feed_and_derived_m5_not_native(self):
        self.change(lambda s:s['frames']['M5'].update(price_basis='ASK',feed_id='ANOTHER_FEED',origin='AGGREGATED_FROM_M1'))
        r=validate_import(self.path)
        self.assertTrue({'PRICE_BASIS_MISMATCH','FEED_MISMATCH','NATIVE_M1_M5_REQUIRED'}<=self.codes(r))
        package=self.root/'package';prepare_package(self.path,package)
        self.assertEqual(read_json(package/'candidate-manifest.json')['lineage']['m5_origin'],'AGGREGATED_FROM_M1')
    def test_incomplete_warmup_and_missing_finality(self):
        self.path=export_fixture(self.root,count=120,warmup=60)
        self.assertIn('PILOT_WARMUP_INSUFFICIENT',self.codes(validate_import(self.path)))
        self.change(lambda s:s['frames']['M1']['finality'].update(policy='UNKNOWN'))
        self.assertIn('FINALITY_UNKNOWN',self.codes(validate_import(self.path)))
    def test_unfinished_flag_cannot_be_ignored_by_documentary_policy(self):
        modify_csv(self.path,'M5',lambda rows:rows[-1].update(Done='false'))
        self.assertIn('BAR_NOT_COMPLETE',self.codes(validate_import(self.path)))
        self.change(lambda s:s['frames']['M5']['finality'].update(policy='DOCUMENTED_CLOSED_EXPORT'))
        self.assertIn('FINALITY_UNKNOWN',self.codes(validate_import(self.path)))
    def test_provider_specific_finality_needs_adapter(self):
        self.change(lambda s:s['frames']['M5']['finality'].update(provider_contract='PROVIDER_COMPLETE_FLAG'))
        self.assertIn('FINALITY_CONTRACT_UNSUPPORTED',self.codes(validate_import(self.path)))
    def test_calendar_coverage_mismatch_and_missing_calendar(self):
        cal=read_json(self.root/'calendar.json');cal['coverage']['start']='2026-11-13';save(self.root/'calendar.json',cal)
        self.change(lambda s:s['calendar'].update(sha256=sha256((self.root/'calendar.json').read_bytes()).hexdigest()))
        r=validate_import(self.path);self.assertEqual(r['mechanical']['status'],'BLOCKED')
        self.change(lambda s:s.update(calendar=None))
        self.assertIn('CALENDAR_REQUIRED',self.codes(validate_import(self.path)))
    def test_legitimate_dated_closure_distinguished_from_unexpected_gap(self):
        cal=read_json(self.root/'calendar.json');cal['maintenance']=[{'start':'2026-11-12T08:15:00','end':'2026-11-12T08:20:00'}];save(self.root/'calendar.json',cal)
        self.change(lambda s:s['calendar'].update(sha256=sha256((self.root/'calendar.json').read_bytes()).hexdigest()))
        modify_csv(self.path,'M1',lambda rows:rows.__delitem__(slice(15,20)))
        modify_csv(self.path,'M5',lambda rows:rows.pop(3))
        r=validate_import(self.path);self.assertEqual(r['mechanical']['status'],'PASS',r['issues'])
        self.assertTrue(any(d['code']=='SESSION_CLOSURE_SKIPPED' for d in r['mechanical']['frames']['M1']['diagnostics']))
    def test_optional_volume_none_unknown_and_invalid(self):
        self.change(lambda s:s['frames']['M1'].update(volume_kind='UNKNOWN'))
        r=validate_import(self.path);self.assertIn('VOLUME_SEMANTICS_UNKNOWN',self.codes(r));self.assertEqual(r['mechanical']['status'],'PASS')
        modify_csv(self.path,'M1',lambda rows:rows[5].update(Ticks='NaN'))
        self.assertIn('VOLUME_INVALID',self.codes(validate_import(self.path)))
        self.path=export_fixture(self.root)
        self.change(lambda s:(s['frames']['M1']['columns'].update(volume=None),s['frames']['M1'].update(volume_kind='NONE',ignored_columns=['Ticks'])))
        r=validate_import(self.path);self.assertEqual(r['mechanical']['status'],'PASS');self.assertIsNone(r['normalized_files']['M1']['volume_sha256'])
    def test_corrections_unknown_and_explicit_provider_revision(self):
        self.change(lambda s:s['frames']['M1']['corrections'].update(status='UNKNOWN'))
        self.assertIn('CORRECTIONS_UNRESOLVED',self.codes(validate_import(self.path)))
        self.change(lambda s:s['frames']['M1']['corrections'].update(status='PROVIDER_CORRECTED',reference='synthetic:mock-correction',previous_source_sha256='0'*64))
        r=validate_import(self.path);self.assertEqual(r['mechanical']['status'],'PASS');self.assertEqual(r['status'],'DATA_NOT_QUALIFIED')
    def test_missing_evidence_does_not_approve_or_prevent_mechanical_diagnostics(self):
        self.change(lambda s:s['evidence']['usage'].update(file=None,sha256=None,reference=None))
        r=validate_import(self.path);self.assertEqual(r['mechanical']['status'],'PASS');self.assertIn('EVIDENCE_MISSING',self.codes(r))
        self.assertEqual(r['status'],'DATA_NOT_QUALIFIED')
    def test_repeatability_stable_hashes_and_sources_unchanged(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        a=self.root/'package-a';b=self.root/'package-b';r=prepare_package(self.path,a);self.assertEqual(r,prepare_package(self.path,b))
        self.assertEqual(read_json(a/'package.lock.json'),read_json(b/'package.lock.json'))
        for name,data in before.items():self.assertEqual((self.root/name).read_bytes(),data)
        ds=load_dataset(a/'candidate-manifest.json')
        self.assertEqual(ds.metadata['checksums']['M1']['normalized_ohlc_sha256'],r['normalized_files']['M1']['normalized_ohlc_sha256'])
        self.assertEqual((a/'source'/'m1.csv').read_bytes(),before['m1-native-shaped.csv'])
        self.assertFalse(ds.finality_attested);self.assertEqual(ds.metadata['source']['independent_review'],'PENDING')
        self.assertFalse(read_json(a/'independent-review.template.json')['independent_review_attested'])
    def test_source_inspection_does_not_read_out_or_guess_market_metadata(self):
        result=inspect_csv(self.root/'m1-native-shaped.csv');self.assertEqual(result['row_count'],150)
        self.assertEqual(result['headers'][0],'Time');self.assertNotIn('price_basis',result)
    def test_authorization_mapping_unsupported_columns_and_future_cutoff(self):
        self.change(lambda s:s.update(authorized_local_use=False))
        self.assertIn('LOCAL_USE_AUTHORIZATION_REQUIRED',self.codes(validate_import(self.path)))
        self.path=export_fixture(self.root);self.change(lambda s:s['frames']['M1']['columns'].update(timestamp='Guess'))
        self.assertIn('CSV_MAPPING_INVALID',self.codes(validate_import(self.path)))
        self.path=export_fixture(self.root);self.change(lambda s:s['source'].update(retrieved_at_utc='2026-11-12T09:00:00Z'))
        self.assertIn('EXPORT_PRECEDES_CANDLE_CLOSE',self.codes(validate_import(self.path)))
    def test_package_no_overwrite_and_partial_publication_no_lock(self):
        dest=self.root/'package';prepare_package(self.path,dest)
        with self.assertRaises(FileExistsError):prepare_package(self.path,dest)
        with patch('iat.qualification_assistant._write_bytes',side_effect=OSError('SYNTHETIC_FAILURE')):
            with self.assertRaises(OSError):prepare_package(self.path,self.root/'failed')
        self.assertFalse((self.root/'failed'/'package.lock.json').exists())
    def test_cli_inspection_validation_packaging_and_absent_review_remain_blocked(self):
        out=self.root/'inspection.json';report=self.root/'diagnostics.json';package=self.root/'candidate package'
        with redirect_stdout(StringIO()):
            self.assertEqual(main(['inspect','--file',str(self.root/'m1-native-shaped.csv'),'--report-path',str(out)]),0)
            self.assertEqual(main(['validate','--spec',str(self.path),'--report-path',str(report)]),3)
            self.assertEqual(main(['package','--spec',str(self.path),'--output-directory',str(package)]),3)
        self.assertTrue((package/'package.lock.json').exists())
        with redirect_stdout(StringIO()):self.assertEqual(main(['validate','--spec',str(self.path),'--report-path',str(report)]),3)
        result=assess_candidate(package,package/'candidate-manifest.json',package/'independent-review.template.json')
        self.assertEqual(result['status'],'DATA_NOT_QUALIFIED')

    def real_shaped_package(self):
        self.change(lambda s:(s.update(dataset_kind='INDEPENDENT_HISTORICAL'),s['source'].update(reference='https://example.org/SYNTHETIC-MOCK-NOT-REAL')))
        package=self.root/'real-shaped-MOCK-package';prepare_package(self.path,package)
        reviewed=read_json(package/'candidate-manifest.json');reviewed['source']['independent_review']='ATTESTED';reviewed['finality_attested']=True
        for value in reviewed['evidence_review'].values():value.update(status='VERIFIED',reference='https://example.org/SYNTHETIC-MOCK-NOT-REAL',reason_code='SYNTHETIC_MOCK_ONLY')
        manifest=package/'reviewed-manifest.json';save(manifest,reviewed)
        approval=read_json(package/'independent-review.template.json');approval.pop('sha256')
        approval.update(dataset_id=digest(load_dataset(manifest).metadata),reviewer_code='independent-b',independent_review_attested=True,
            reviewed_at_utc='2026-11-14T00:00:00Z',decision='APPROVED')
        for item in approval['evidence'].values():item.update(status='VERIFIED',explanation='SYNTHETIC MOCK ONLY')
        record=package/'external-review.json';save(record,hashed(approval))
        return package,manifest,record

    def test_no_self_approval_and_existing_gate_still_rejects_synthetic_calendar(self):
        package,manifest,record=self.real_shaped_package()
        result=assess_candidate(package,manifest,record)
        self.assertEqual(result['status'],'DATA_NOT_QUALIFIED');self.assertIn('SYNTHETIC_CALENDAR_NOT_REAL_EVIDENCE',result['reason_codes'])
        approval=read_json(record);approval['reviewer_code']='OPERATOR-A';save(record,hashed({k:v for k,v in approval.items() if k!='sha256'}))
        self.assertEqual(assess_candidate(package,manifest,record)['reason_codes'],['SELF_APPROVAL_FORBIDDEN'])

    def test_external_gate_success_is_delegated_not_generated_and_remains_read_only(self):
        package,manifest,record=self.real_shaped_package()
        # MOCK ONLY: the real gate is independently tested, including its refusal above.
        with patch('iat.qualification_assistant.qualify_historical',return_value={'status':'HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED'}) as gate:
            result=assess_candidate(package,manifest,record);gate.assert_called_once_with(manifest,record)
        self.assertEqual(result['status'],'HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED')
        self.assertEqual(result['historical_validation'],'PENDING');self.assertEqual(result['historical_comparisons'],'NOT_RUN')
        self.assertFalse(result['safety']['execution_allowed'])

    def test_tampered_package_and_changed_reviewed_data_reject(self):
        package,manifest,record=self.real_shaped_package()
        reviewed=read_json(manifest);reviewed['lineage']['m5_origin']='AGGREGATED_FROM_M1';save(manifest,reviewed)
        self.assertEqual(assess_candidate(package,manifest,record)['reason_codes'],['REVIEWED_MANIFEST_CHANGED_DATA'])
        (package/'source'/'m1.csv').write_bytes(b'ALTERED SOURCE')
        self.assertEqual(assess_candidate(package,manifest,record)['reason_codes'],['PACKAGE_INVALID'])

    def test_source_change_during_import_is_detected(self):
        from iat.replay_dataset import read_bytes as actual_read
        calls=0
        def changed(path):
            nonlocal calls
            data=actual_read(path)
            if Path(path).name=='m1-native-shaped.csv':
                calls+=1
                if calls>1:return data+b'\n'
            return data
        with patch('iat.qualification_assistant.read_bytes',side_effect=changed):
            self.assertIn('SOURCE_CHANGED_DURING_IMPORT',self.codes(validate_import(self.path)))

    def test_explicit_utc_bars_across_dst_match_iana_session_calendar(self):
        for date,start_hour in (('2026-11-01',4),('2026-03-08',5)):
            self.path=export_fixture(self.root);old=datetime(2026,11,12,8,tzinfo=timezone.utc)
            new=datetime.fromisoformat(date).replace(hour=start_hour,tzinfo=timezone.utc);delta=new-old
            def shift(rows):
                for row in rows:row['Time']=(datetime.fromisoformat(row['Time'])+delta).isoformat()
            for tf in ('M1','M5'):modify_csv(self.path,tf,shift)
            s=read_json(self.path)
            for bounds in (s['utc_range'],s['evaluation'],*s['warmup'].values()):
                for k in ('start','end'):bounds[k]=(datetime.fromisoformat(bounds[k])+delta).isoformat()
            cal=synthetic_v2();cal['timezone']='America/New_York'
            day=new.date();cal['coverage']={'start':(day-timedelta(days=1)).isoformat(),'end':(day+timedelta(days=2)).isoformat()}
            cal['verification']['expires_at']=(new+timedelta(days=1)).isoformat()
            cal['verification']['provenance'][0]['captured_at']=(new-timedelta(days=2)).isoformat()
            save(self.root/'calendar.json',cal);s['calendar']['sha256']=sha256((self.root/'calendar.json').read_bytes()).hexdigest();save(self.path,s)
            r=validate_import(self.path)
            with self.subTest(date=date):self.assertEqual(r['mechanical']['status'],'PASS',r['issues'])

    def test_mapped_per_row_symbol_basis_and_feed_cannot_conflict(self):
        for field,value,code in (('symbol','EURUSD','SYMBOL_MISMATCH'),('price_basis','ASK','PRICE_BASIS_MISMATCH'),('feed_id','OTHER','FEED_MISMATCH')):
            self.path=export_fixture(self.root);self.change(lambda s:s['frames']['M1']['columns'].update(**{field:'Metadata'}))
            file=self.root/'m1-native-shaped.csv'
            with file.open(newline='') as f:rows=list(csv.DictReader(f))
            expected={'symbol':'XAUUSD','price_basis':'BID','feed_id':'SYNTHETIC_NATIVE_SHAPED'}[field]
            for row in rows:row['Metadata']=expected
            rows[4]['Metadata']=value
            with file.open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
            self.assertIn(code,self.codes(validate_import(self.path)))

    def test_committed_synthetic_sample_matches_runtime_and_never_claims_real_validation(self):
        root=Path('docs/research_audits/qualification-assistant-synthetic-v1')
        r=validate_import(self.path);self.assertEqual(r,read_json(root/'sample-report.json'))
        audit=read_json(root/'audit.json');self.assertFalse(audit['real_export_validated']);self.assertFalse(audit['independent_human_approval_obtained'])
        self.assertTrue(audit['package_locks_identical'])
        for result in audit['cases'].values():
            self.assertTrue(result['repeatable']);self.assertTrue(result['source_files_unchanged']);self.assertEqual(result['qualification'],'DATA_NOT_QUALIFIED')
