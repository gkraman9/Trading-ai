"""Synthetic offline inputs only; operator observations are assertions, never market proof."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import csv,json,tempfile,unittest
from iat.historical_evidence_manifest import (create_manifest,verify_local,validate_manifest,validate_observations,
    qualification_gate,read_observations,REQUIRED_CODES,MAX_FILE_BYTES)
from iat.historical_session_boundaries import inspect_csv_files
from iat.pilot_preparation import file_fingerprint
from iat.chart_benchmark import hashed,check_hash
from iat.replay_dataset import load_dataset,DatasetError
from diagnostics.historical_evidence_manifest import main
from test_historical_session_boundaries import session_fixture,observations,START,END

EXAMPLE=Path('config/examples/historical-evidence/operator-reported-v1.json')


class EvidenceManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.o=json.loads(EXAMPLE.read_text());self.paths={k:self.root/(k+('.csv' if k in ('M1','M5') else '.json')) for k in ('M1','M5','diagnostic','calendar')}
    def tearDown(self):self.temp.cleanup()
    def save(self,key,value):self.paths[key].write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    def fixture(self,start=START,end=END):
        # Invented flat prices, generic synthetic quote intervals. Actual unverified
        # candidate is only the configuration under test, not broker evidence.
        c=json.loads(Path('config/profiles/exness-xauusd-v2.candidate.json').read_text());rows=observations(c,start,end)
        self.paths['calendar'].write_bytes(Path('config/profiles/exness-xauusd-v2.candidate.json').read_bytes())
        for tf in ('M1','M5'):
            with self.paths[tf].open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=self.o['files'][tf]['headers'],lineterminator='\n');w.writeheader()
                for bar in rows[tf]:w.writerow({'timestamp_utc':bar['timestamp'],**{k:bar[k] for k in ('open','high','low','close')},'tick_volume':10,'spread':20,'real_volume':0})
            self.o['files'][tf].update(name=self.paths[tf].name,**file_fingerprint(self.paths[tf]),row_count=len(rows[tf]))
        self.o.update(data_kind='SYNTHETIC_FIXTURE',source_description='SYNTHETIC fixture not real prices',window={'start':start,'end':end})
        self.refresh_diagnostic()
        self.o['calendar']['file_sha256']=file_fingerprint(self.paths['calendar'])['sha256']
        validate_observations(self.o)
        return self.o
    def refresh_diagnostic(self):
        from iat.historical_evidence_manifest import MAPPING
        r=inspect_csv_files(self.paths['M1'],self.paths['M5'],self.paths['calendar'],self.o['window']['start'],self.o['window']['end'],MAPPING)
        self.save('diagnostic',r);self.o['diagnostic'].update(file_sha256=file_fingerprint(self.paths['diagnostic'])['sha256'],name='diagnostic.json')
        self.o['findings']={'comparison_counts':r['comparison_counts'],'absent_m1_slot_counts':r['m1_slot_absence_counts'],
            'partials':[{'open_utc':b['geometry']['scheduled_open_utc'],'classification':b['geometry']['classification'],'market_open_seconds':b['geometry']['market_open_seconds'],'schedule_verified':b['geometry']['schedule_verified']} for b in r['m5_intervals'] if b['geometry']['classification']=='PARTIAL_SESSION_CLOSE'],
            'reason_codes':r['reason_codes']}
    def verify(self):return verify_local(self.o,**{k.lower()+'_path':p for k,p in self.paths.items()})
    def resha(self,key):
        f=file_fingerprint(self.paths[key])
        if key in ('M1','M5'):self.o['files'][key].update(f)
        else:self.o[key]['file_sha256']=f['sha256']
    def invalid(self,r,code=None):
        self.assertEqual(r['evidence_state'],'INVALID_OR_CONFLICTING_EVIDENCE')
        self.assertEqual(r['reproduction']['status'],'NOT_REPRODUCED')
        if code:self.assertIn(code,r['reason_codes'])
        self.safety(r)
    def safety(self,r):
        self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED');self.assertEqual(r['historical_validation'],'PENDING');self.assertEqual(r['historical_comparisons'],'NOT_RUN')
        self.assertEqual(r['exness'],'BLOCKED');self.assertEqual(r['safety']['signal'],'WAIT')
        self.assertFalse(r['safety']['execution_allowed']);self.assertFalse(r['safety']['broker_access']);self.assertEqual(r['safety']['orders_requested'],0)
        self.assertFalse(r['safety']['profitability_tested']);self.assertFalse(r['qualification_gate']['ordinary_strategy_inputs_allowed'])
        self.assertTrue(set(REQUIRED_CODES)<=set(r['reason_codes']));validate_manifest(r)
    def test_reported_records_exact_assertions_without_inspecting_local_files(self):
        with patch('iat.historical_evidence_manifest.file_fingerprint',side_effect=AssertionError('Must not read sources')):
            r=create_manifest(self.o)
        self.assertEqual(r['evidence_state'],'OPERATOR_REPORTED');self.assertIsNone(r['local_facts']);self.assertEqual(r['externally_verified_evidence'],[])
        self.assertEqual(r['operator_assertions']['files']['M1']['sha256'],'c98944d8de6251efecc4e75071517030e3ae1fea9cabb71f22f498a29097e54f')
        self.assertEqual(r,json.loads(Path('config/examples/historical-evidence/operator-manifest-v1.json').read_text()));self.safety(r)
    def test_reported_serialization_and_order_are_deterministic(self):
        self.assertEqual(create_manifest(self.o),create_manifest(deepcopy(self.o)))
        self.assertEqual(create_manifest(self.o)['sha256'],create_manifest(dict(reversed(list(self.o.items()))))['sha256'])
    def test_full_local_integrity_reproduction_is_repeatable_and_never_qualifies(self):
        self.fixture();before={k:p.read_bytes() for k,p in self.paths.items()}
        r=self.verify();self.assertEqual(r,self.verify());self.safety(r)
        self.assertEqual(r['state_history'],['OPERATOR_REPORTED','LOCAL_INTEGRITY_VERIFIED','LOCAL_MECHANICAL_REPRODUCED','INDEPENDENT_QUALIFICATION_REQUIRED'])
        self.assertEqual(r['reproduction']['status'],'REPRODUCED');self.assertEqual(r['local_facts']['M1']['row_count'],188)
        self.assertEqual(r['local_facts']['research_findings']['comparison_counts']['FIVE_M1_MATCH'],37)
        self.assertEqual(r['operator_assertions']['data_kind'],'SYNTHETIC_FIXTURE')
        self.assertEqual({k:p.read_bytes() for k,p in self.paths.items()},before)
        self.assertNotEqual(r['local_facts']['diagnostic']['file_fingerprint']['sha256'],r['local_facts']['diagnostic']['embedded_payload_sha256'])
    def test_one_byte_csv_modification(self):
        self.fixture();p=self.paths['M1'];p.write_bytes(p.read_bytes()+b' ');self.invalid(self.verify(),'FILE_SHA256_MISMATCH')
    def test_one_byte_diagnostic_modification(self):
        self.fixture();p=self.paths['diagnostic'];p.write_bytes(p.read_bytes()+b' ');self.invalid(self.verify(),'FILE_SHA256_MISMATCH')
    def test_missing_source(self):
        self.fixture();self.paths['M1'].unlink();self.invalid(self.verify(),'LOCAL_FILE_UNAVAILABLE_OR_UNSAFE')
    def test_truncated_source(self):
        self.fixture();p=self.paths['M5'];p.write_bytes(p.read_bytes()[:100]);self.invalid(self.verify(),'FILE_SHA256_MISMATCH')
    def test_wrong_byte_count(self):
        self.fixture();self.o['files']['M1']['byte_count']+=1;self.invalid(self.verify(),'FILE_BYTE_COUNT_MISMATCH')
    def test_unexpected_csv_header_even_after_updated_hash(self):
        self.fixture();p=self.paths['M1'];p.write_text(p.read_text().replace('tick_volume','fake_volume'));self.resha('M1');self.invalid(self.verify(),'CSV_HEADER_MISMATCH')
    def test_wrong_row_count(self):
        self.fixture();self.o['files']['M1']['row_count']+=1;self.invalid(self.verify(),'CSV_ROW_COUNT_OR_SCOPE_MISMATCH')
    def test_duplicate_timestamps(self):
        self.fixture();p=self.paths['M1'];lines=p.read_text().splitlines();lines[-1]=lines[-2];p.write_text('\n'.join(lines)+'\n');self.resha('M1');self.invalid(self.verify(),'CSV_CHRONOLOGY_OR_OHLC_INVALID')
    def test_out_of_order_timestamps(self):
        self.fixture();p=self.paths['M1'];lines=p.read_text().splitlines();lines[1],lines[2]=lines[2],lines[1];p.write_text('\n'.join(lines)+'\n');self.resha('M1');self.invalid(self.verify(),'CSV_CHRONOLOGY_OR_OHLC_INVALID')
    def test_invalid_and_nonfinite_ohlc(self):
        self.fixture();p=self.paths['M1'];original=p.read_text()
        for bad in ('nan','inf','-1','garbage'):
            p.write_text(original.replace(',100.0,101.0,99.0,100.0,',','+bad+',101.0,99.0,100.0,',1));self.resha('M1')
            self.invalid(self.verify())
    def test_incorrect_alignment_count(self):
        self.fixture();self.o['findings']['comparison_counts']['FIVE_M1_MATCH']+=1;self.invalid(self.verify(),'COMPARISON_COUNTS_MISMATCH')
    def test_incorrect_partial_duration(self):
        self.fixture();self.o['findings']['partials'][0]['market_open_seconds']=181;self.invalid(self.verify(),'PARTIAL_SESSION_FINDINGS_MISMATCH')
    def test_missing_required_reason_code_is_not_accepted(self):
        self.o['findings']['reason_codes'].remove('CANDLE_FINALITY_UNCERTAIN')
        with self.assertRaises(ValueError):create_manifest(self.o)
    def test_altered_diagnostic_reason_code_cannot_be_rehashed_into_success(self):
        self.fixture();r=json.loads(self.paths['diagnostic'].read_text());r['reason_codes'].remove('HOLIDAY_COVERAGE_UNKNOWN');r.pop('sha256');self.save('diagnostic',hashed(r));self.resha('diagnostic')
        self.invalid(self.verify(),'DIAGNOSTIC_REPRODUCTION_MISMATCH')
    def test_calendar_cannot_be_declared_independently_verified(self):
        self.o['calendar']['independently_verified']=True
        with self.assertRaises(ValueError):create_manifest(self.o)
    def test_changed_calendar_bytes_fail_closed(self):
        self.fixture();self.paths['calendar'].write_bytes(self.paths['calendar'].read_bytes()+b' ');self.invalid(self.verify(),'FILE_SHA256_MISMATCH')
    def test_conflicting_feed_and_basis_and_derived_m5(self):
        for field,left,right in [('feed_identity','feed A','feed B'),('price_basis','BID','ASK'),('origin','NATIVE_OPERATOR_REPORTED','DERIVED')]:
            o=deepcopy(self.o);o['files']['M1'][field]=left;o['files']['M5'][field]=right
            self.invalid(create_manifest(o))
    def test_missing_rights_and_independent_approval_remain_missing(self):
        r=create_manifest(self.o)
        for k in ('historical_usage_rights','independent_approval'):self.assertEqual(r['evidence_gaps'][k]['status'],'MISSING')
        self.safety(r)
    def test_referenced_document_is_not_verified_or_approved(self):
        self.o['evidence_references']['independent_approval']={'document':'review-request.pdf','sha256':'a'*64};r=create_manifest(self.o)
        self.assertEqual(r['evidence_gaps']['independent_approval']['status'],'OPERATOR_REFERENCE_NOT_VERIFIED');self.safety(r)
    def test_unsupported_observation_or_manifest_version(self):
        o=deepcopy(self.o);o['observation_version']=2
        with self.assertRaises(ValueError):create_manifest(o)
        r=create_manifest(self.o);r.pop('sha256');r['manifest_schema_version']=2
        with self.assertRaises(ValueError):validate_manifest(hashed(r))
    def test_oversized_input(self):
        p=self.root/'big.json';p.write_bytes(b' '*65537)
        with self.assertRaises(ValueError):read_observations(p)
    def test_oversized_source(self):
        self.fixture()
        with self.paths['M1'].open('r+b') as f:f.truncate(MAX_FILE_BYTES+1)
        self.invalid(self.verify(),'LOCAL_FILE_SIZE_LIMIT')
    def test_oversized_row_declaration(self):
        self.o['files']['M1']['row_count']=5001
        with self.assertRaises(ValueError):create_manifest(self.o)
    def test_path_traversal_is_not_a_local_identity(self):
        for value in ('../secret.csv','C:\\private.csv','/tmp/private.csv','data/secret.csv'):
            o=deepcopy(self.o);o['files']['M1']['name']=value
            with self.assertRaises(ValueError):create_manifest(o)
    def cli(self,mode='reported',**extra):
        p=self.root/'observations.json';p.write_text(json.dumps(self.o));args=[mode,'--observations',str(p),'--report-path',str(extra.pop('output',self.root/'manifest.json'))]
        for k,v in extra.items():args+=['--'+k,str(v)]
        with redirect_stdout(StringIO()) as stdout:code=main(args)
        return code,stdout.getvalue()
    def test_reported_cli_nonzero_readonly_and_no_personal_paths(self):
        code,text=self.cli();self.assertEqual(code,3);self.assertNotIn(str(self.root),text)
        r=json.loads((self.root/'manifest.json').read_text());self.assertNotIn(str(self.root),json.dumps(r));self.safety(r)
    def test_existing_destination_is_not_overwritten(self):
        p=self.root/'existing.json';p.write_bytes(b'ORIGINAL');code,_=self.cli(output=p);self.assertEqual(code,2);self.assertEqual(p.read_bytes(),b'ORIGINAL')
    def test_unsafe_output_and_alias_are_rejected(self):
        for p in (self.root/'..'/'escape.json',self.root/'evidence.csv',self.root/'observations.json'):
            code,_=self.cli(output=p);self.assertEqual(code,2)
    def test_verify_cli_reproduces_without_approval(self):
        self.fixture();code,_=self.cli('verify',m1=self.paths['M1'],m5=self.paths['M5'],diagnostic=self.paths['diagnostic'],calendar=self.paths['calendar'])
        self.assertEqual(code,3);r=json.loads((self.root/'manifest.json').read_text());self.assertEqual(r['reproduction']['status'],'REPRODUCED');self.safety(r)
    def test_missing_local_paths_produce_failure_not_success_report(self):
        self.fixture();code,_=self.cli('verify');self.assertEqual(code,2)
        r=json.loads((self.root/'manifest.json').read_text());self.assertEqual(r['evidence_state'],'INVALID_OR_CONFLICTING_EVIDENCE');self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED')
    def test_manifest_cannot_enter_replay_loader_even_if_rehashed_as_qualified(self):
        r=create_manifest(self.o);p=self.root/'not-replay.json';p.write_text(json.dumps(r))
        with self.assertRaisesRegex(DatasetError,'EVIDENCE_MANIFEST_NOT_REPLAY_ELIGIBLE'):load_dataset(p)
        r.pop('sha256');r['qualification']='DATA_QUALIFIED';r=hashed(r)
        with self.assertRaises(ValueError):validate_manifest(r)
        self.assertEqual(qualification_gate(r)['status'],'BLOCKED')
    def test_cannot_drop_blockers_or_forge_approval_in_rehashed_manifest(self):
        r=create_manifest(self.o);r.pop('sha256');r['reason_codes'].remove('PARTIAL_SESSION_CANDLE')
        with self.assertRaises(ValueError):validate_manifest(hashed(r))
        r=create_manifest(self.o);r.pop('sha256');r['externally_verified_evidence']=['self-approved']
        with self.assertRaises(ValueError):validate_manifest(hashed(r))
    def test_file_digest_cannot_substitute_for_payload_digest(self):
        self.fixture();r=json.loads(self.paths['diagnostic'].read_text());r['sha256']=self.o['diagnostic']['file_sha256'];self.save('diagnostic',r);self.resha('diagnostic');self.invalid(self.verify())
    def test_collection_date_and_provenance_never_claim_runtime_revision(self):
        r=create_manifest(self.o);self.assertIsNone(r['operator_assertions']['collection_date_utc']);self.assertNotIn('runtime_code_revision',r)
    def test_verify_conflicting_provenance_has_one_terminal_invalid_transition(self):
        self.fixture();self.o['files']['M1']['feed_identity']='A';self.o['files']['M5']['feed_identity']='B';self.invalid(self.verify(),'PROVENANCE_CONFLICT')
    def test_control_characters_in_codes_are_not_printable_evidence(self):
        self.o['findings']['reason_codes']=sorted(self.o['findings']['reason_codes']+['UNSAFE\x1b[31m'])
        with self.assertRaises(ValueError):create_manifest(self.o)
    def test_modified_diagnostic_with_updated_file_hash_but_stale_payload_fails(self):
        self.fixture();r=json.loads(self.paths['diagnostic'].read_text());r['comparison_counts']['FIVE_M1_MATCH']+=1;self.save('diagnostic',r);self.resha('diagnostic');self.invalid(self.verify())
    def test_timestamp_coverage_declaration_is_checked(self):
        self.fixture();self.o['files']['M1']['first_open_utc']='2026-11-12T19:01:00Z';self.invalid(self.verify(),'CSV_TIMESTAMP_COVERAGE_MISMATCH')
    def test_symlink_output_is_not_followed(self):
        target=self.root/'target.json';target.write_text('ORIGINAL');link=self.root/'link.json'
        try:link.symlink_to(target)
        except (OSError,NotImplementedError):self.skipTest('OS does not permit creation of symbolic links')
        code,_=self.cli(output=link);self.assertEqual(code,2);self.assertEqual(target.read_text(),'ORIGINAL')
    def test_actual_header_record_source_invariance_even_on_failed_verification(self):
        self.fixture();before={k:p.read_bytes() for k,p in self.paths.items()};self.o['findings']['partials'][0]['market_open_seconds']=179
        self.invalid(self.verify());self.assertEqual(before,{k:p.read_bytes() for k,p in self.paths.items()})
    def test_three_day_synthetic_reproduction_has_three_conditional_boundaries(self):
        # Invented flat OHLC sampled from candidate geometry; these are NOT operator bytes.
        self.fixture(start='2026-11-11T00:00:00Z',end='2026-11-14T00:00:00Z')
        r=self.verify();self.safety(r);self.assertEqual(r['reproduction']['status'],'REPRODUCED')
        self.assertEqual(len(r['operator_assertions']['findings']['partials']),3)
        self.assertEqual(r['operator_assertions']['findings']['absent_m1_slot_counts'],{'MISSING_UNESTABLISHED_UNVERIFIED_CALENDAR':6})
        self.assertTrue(all(not p['schedule_verified'] and p['market_open_seconds']==180 for p in r['operator_assertions']['findings']['partials']))
        self.assertEqual(r['operator_assertions']['data_kind'],'SYNTHETIC_FIXTURE')
    def test_verification_uses_no_network_or_mt5_binding(self):
        self.fixture()
        with patch('socket.create_connection',side_effect=AssertionError('Network prohibited')),patch.dict('sys.modules',{'MetaTrader5':None}):
            r=self.verify()
        self.assertEqual(r['reproduction']['status'],'REPRODUCED');self.safety(r)
    def test_excessive_json_nesting_produces_a_failure_artifact(self):
        p=self.root/'nested.json';p.write_text('['*2000+'0'+']'*2000);output=self.root/'failure.json'
        with redirect_stdout(StringIO()):code=main(['reported','--observations',str(p),'--report-path',str(output)])
        self.assertEqual(code,2);r=json.loads(output.read_text());self.assertEqual(r['evidence_state'],'INVALID_OR_CONFLICTING_EVIDENCE')
        self.assertFalse(r['safety']['execution_allowed'])
        self.assertTrue(set(REQUIRED_CODES)<=set(r['reason_codes']))
    def test_unc_and_network_paths_are_rejected_before_any_file_access(self):
        from iat.historical_evidence_manifest import local_path
        from diagnostics.historical_evidence_manifest import safe_output
        for value in ('\\\\server\\share\\private.json','//server/share/private.json','https://example.invalid/data.json'):
            with self.assertRaises(ValueError):local_path(value)
            with self.assertRaises(ValueError):safe_output(value,[])
            with self.assertRaises(ValueError):safe_output(self.root/'safe.json',[value])
            with self.assertRaises(ValueError):read_observations(value)
