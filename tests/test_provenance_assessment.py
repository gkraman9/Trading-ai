"""Synthetic provenance mechanics, not real broker/authenticity validation."""
import ast
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from functools import lru_cache
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator, FormatChecker

from iat.provenance_assessment import (assess_historical_provenance,validate_provenance_assessment,
    provenance_text,broker_reference,BROKER_COMMIT,BROKER_SHA)
from iat.replay_dataset import load_dataset,utc
from iat.pilot_qualification import ITEMS
from iat.chart_benchmark import hashed,write_new
from iat.intelligence.strategy_replay import digest
from diagnostics.provenance_assessment import main
from test_evaluation_window import v2_fixture
from test_historical_replay import rewrite,recalc
from test_scenario_replay import modify_frame,run
from test_intelligence_patterns import START
from test_qualification_assistant import export_fixture,prepare_package
from test_independent_source_evidence import fixture as registry_fixture


def rehash(r):
    r['sha256']=digest({k:v for k,v in r.items() if k!='sha256'});return r


def gap(r,code):return next(g for g in r['gaps'] if g['code']==code)


def binding(path,broker='EXNESS'):
    m=load_dataset(path).metadata
    out=path.parent/'binding.json'
    out.write_text(json.dumps({'binding_version':1,'dataset_id':digest(m),'manifest_sha256':m['manifest_sha256'],'broker':broker}))
    return out


def shifted(path,day='2026-11-12',clock='21:50:00'):
    at=utc(day+'T'+clock+'Z');delta=at-START
    for tf in ('M1','M5'):
        modify_frame(path,tf,lambda rows:[r.update(timestamp=(utc(r['timestamp'])+delta).isoformat()) for r in rows])
    def change(m):
        for field in ('utc_range','evaluation'):
            for k in ('start','end'):m[field][k]=(utc(m[field][k])+delta).isoformat()
        for values in m['warmup'].values():
            for k in ('start','end'):values[k]=(utc(values[k])+delta).isoformat()
        m['source']['retrieved_at_utc']='2026-11-15T00:00:00Z'
    rewrite(path,change)
    return path


def review_fixture(root,path,decision='APPROVED'):
    m=load_dataset(path).metadata
    doc=root/'synthetic-review-document.txt';doc.write_bytes(b'SYNTHETIC MOCK ONLY NOT AUTHENTICATED BROKER EVIDENCE')
    r=hashed({'qualification_version':1,'dataset_id':digest(m),'interval':m['utc_range'],'provider_entity':'SYNTHETIC MOCK',
        'feed_id':m['lineage']['feed_id'],'instrument':'XAUUSD','price_basis':m['lineage']['price_basis'],
        'reviewer_code':'SYNTHETIC_REVIEWER','independent_review_attested':True,'reviewed_at_utc':'2026-11-16T00:00:00Z',
        'decision':decision,'evidence':{k:{'status':'VERIFIED','file':doc.name,'sha256':sha256(doc.read_bytes()).hexdigest(),
            'reference':'SYNTHETIC MOCK','scope':m['utc_range'],'explanation':'SYNTHETIC DOCUMENT CHECK ONLY'} for k in ITEMS}})
    rp=root/'independent-review.json';rp.write_text(json.dumps(r));return rp,doc


def registry_for(path):
    m=load_dataset(path).metadata;r=registry_fixture()
    r['context']['interval']=m['utc_range']
    for tf in ('M1','M5'):r['manifest_reference']['dataset_fingerprints'][tf]=m['checksums'][tf]['file_sha256']
    out=path.parent/'registry.json';out.write_text(json.dumps(r));return out


def synthetic_audit():
    cases={}
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        for name,kind in [('clean','clean'),('missing','missing'),('duplicate','duplicate'),('ohlc','ohlc'),('aggregation','aggregation')]:
            path=v2_fixture(root,count=30,evaluation_minutes=10)
            if kind=='missing':modify_frame(path,'M1',lambda rows:rows.pop(5))
            if kind=='duplicate':modify_frame(path,'M1',lambda rows:rows.insert(5,dict(rows[4])))
            if kind=='ohlc':modify_frame(path,'M1',lambda rows:rows[4].update(high='0'))
            if kind=='aggregation':modify_frame(path,'M5',lambda rows:rows[-1].update(high='999'))
            r=assess_historical_provenance(path)
            cases[name]={'sha256':r['sha256'],'dataset_id':r['dataset_id'],'source_file_hashes':{tf:r['inventory']['frames'][tf]['supplied_csv_sha256'] for tf in ('M1','M5')},
                'mechanical':r['mechanical'],'evidence_coverage':r['evidence_coverage'],'gap_labels':{g['code']:g['verification_status'] for g in r['gaps']}}
        for name,day,clock in [('exness_break','2026-11-12','21:50:00'),('close_only','2026-11-12','23:00:00'),('friday_unknown','2026-11-13','23:00:00')]:
            path=shifted(v2_fixture(root,count=30,evaluation_minutes=10),day,clock)
            r=assess_historical_provenance(path,broker_binding_path=binding(path))
            cases[name]={'sha256':r['sha256'],'dataset_id':r['dataset_id'],'broker_comparison':r['broker_comparison'],
                'evidence_coverage':r['evidence_coverage'],'source_file_hashes':{tf:r['inventory']['frames'][tf]['supplied_csv_sha256'] for tf in ('M1','M5')}}
        path=v2_fixture(root,count=30,evaluation_minutes=10)
        r=assess_historical_provenance(path,broker_binding_path=binding(path,'NON_EXNESS'))
        cases['non_exness']={'sha256':r['sha256'],'broker_comparison':r['broker_comparison'],'evidence_coverage':r['evidence_coverage']}
    return {'audit_version':1,'data_kind':'LABELED_SYNTHETIC_ONLY','cases':cases,
        'broker_reference_commit':BROKER_COMMIT,'broker_reference_sha256':BROKER_SHA,
        'qualification':'DATA_NOT_QUALIFIED','historical_validation':'PENDING','historical_comparisons':'NOT_RUN',
        'exness':'BLOCKED','signal':'WAIT','execution_allowed':False,'raw_support_correspondence_embedded':False}


class ProvenanceAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=v2_fixture(self.root,count=30,evaluation_minutes=10)
    def tearDown(self):self.temp.cleanup()
    @classmethod
    def setUpClass(cls):
        cls.schema=Draft202012Validator(json.loads(Path('config/historical-provenance-assessment-v1.schema.json').read_text()),format_checker=FormatChecker())
    def report(self,**kwargs):return assess_historical_provenance(self.path,**kwargs)
    def safe(self,r,**kwargs):
        self.assertTrue(validate_provenance_assessment(r,self.path,**kwargs));self.schema.validate(r)
        self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED');self.assertEqual(r['historical_validation'],'PENDING')
        self.assertEqual(r['historical_comparisons'],'NOT_RUN');self.assertEqual(r['exness'],'BLOCKED')
        self.assertEqual(r['signal'],'WAIT');self.assertIs(r['execution_allowed'],False);self.assertFalse(r['safety']['broker_access'])
        self.assertEqual(r['safety']['orders_requested'],0);self.assertFalse(r['safety']['profitability_tested'])
    def test_mechanical_integrity_is_not_source_authenticity(self):
        r=self.report();self.safe(r)
        self.assertEqual(gap(r,'FILE_INTEGRITY')['verification_status'],'VERIFIED')
        self.assertEqual(gap(r,'CANDLE_INTEGRITY')['verification_status'],'VERIFIED')
        self.assertEqual(gap(r,'CROSS_FRAME_CONSISTENCY')['verification_status'],'VERIFIED')
        self.assertEqual(gap(r,'SOURCE_AUTHENTICITY')['verification_status'],'UNVERIFIED')
        self.assertIsNone(r['evidence_coverage']['independent_authenticity']['denominator'])
        self.assertIsNone(r['inventory']['frames']['M1']['original_import_sha256'])
    def test_empty_source_has_unknown_inventory_not_zero_rows(self):
        r=assess_historical_provenance();self.assertTrue(validate_provenance_assessment(r));self.schema.validate(r)
        self.assertIsNone(r['inventory']);self.assertIsNone(r['dataset_id']);self.assertIsNone(r['mechanical'])
        self.assertEqual(gap(r,'FILE_INTEGRITY')['verification_status'],'UNVERIFIED')
    def test_missing_hash_is_not_verified(self):
        rewrite(self.path,lambda m:m['frames']['M1'].pop('sha256'))
        r=self.report();self.safe(r);self.assertIsNone(r['inventory'])
        self.assertNotEqual(gap(r,'FILE_INTEGRITY')['verification_status'],'VERIFIED')
    def test_altered_dataset_bytes_are_contradicted(self):
        p=self.root/'m1.csv';p.write_bytes(p.read_bytes()+b'\n')
        r=self.report();self.safe(r)
        self.assertEqual(gap(r,'FILE_INTEGRITY')['verification_status'],'CONTRADICTED')
        self.assertIn('DATASET_CHECKSUM_MISMATCH',{e['code'] for e in r['input_errors']})
    def test_duplicates_out_of_order_and_alignment_are_not_repaired(self):
        for kind,change,field in [
            ('duplicate',lambda rows:rows.insert(5,dict(rows[4])),'duplicate_timestamps'),
            ('order',lambda rows:rows.__setitem__(slice(4,6),list(reversed(rows[4:6]))),'out_of_order_pairs'),
            ('alignment',lambda rows:rows[4].update(timestamp=(utc(rows[4]['timestamp'])+timedelta(seconds=30)).isoformat()),'misaligned_openings')]:
            self.path=v2_fixture(self.root,count=30,evaluation_minutes=10)
            modify_frame(self.path,'M1',change);r=self.report();self.safe(r)
            self.assertEqual(r['mechanical']['frames']['M1'][field],1)
            self.assertEqual(gap(r,'CANDLE_INTEGRITY')['verification_status'],'CONTRADICTED')
            self.assertIsNone(r['mechanical']['alignment'])
    def test_missing_candles_without_calendar_are_grid_gaps_not_certified_broker_gaps(self):
        modify_frame(self.path,'M1',lambda rows:rows.pop(10));r=self.report();self.safe(r)
        f=r['mechanical']['frames']['M1'];self.assertEqual(f['missing_utc_grid_intervals'],1)
        self.assertIsNone(f['missing_declared_calendar_ordinary_intervals'])
        self.assertEqual(gap(r,'COVERAGE_CONTINUITY')['verification_status'],'PARTIALLY_VERIFIED')
    def test_declared_calendar_can_reproduce_missing_ordinary_intervals(self):
        self.path=v2_fixture(self.root,count=30,evaluation_minutes=10,calendar=True)
        modify_frame(self.path,'M1',lambda rows:rows.pop(10));r=self.report();self.safe(r)
        self.assertEqual(r['mechanical']['frames']['M1']['missing_declared_calendar_ordinary_intervals'],1)
        self.assertEqual(gap(r,'COVERAGE_CONTINUITY')['verification_status'],'CONTRADICTED')
    def test_invalid_and_nonfinite_ohlc_are_counted_without_public_prices(self):
        for value in ('0','nan'):
            self.path=v2_fixture(self.root,count=30,evaluation_minutes=10)
            modify_frame(self.path,'M1',lambda rows:rows[4].update(high=value))
            r=self.report();self.safe(r);self.assertEqual(r['mechanical']['frames']['M1']['invalid_ohlc_rows'],1)
            self.assertNotIn('"high":',json.dumps(r,allow_nan=False))
    def test_m1_to_m5_aggregation_mismatch_is_mechanical_contradiction(self):
        modify_frame(self.path,'M5',lambda rows:rows[2].update(high='999'))
        r=self.report();self.safe(r)
        self.assertEqual(r['mechanical']['alignment']['mismatch_count'],1)
        self.assertEqual(gap(r,'CROSS_FRAME_CONSISTENCY')['verification_status'],'CONTRADICTED')
    def test_derived_m5_is_internal_aggregation_not_native_feed_authentication(self):
        r=self.report();self.safe(r)
        self.assertEqual(r['mechanical']['alignment_assurance'],'INTERNAL_AGGREGATION_ONLY')
        self.assertEqual(r['mechanical']['alignment']['evaluation']['cross_frame_claim'],'NOT_ESTABLISHED')
    def test_explicit_exness_binding_does_not_infer_unknown_price_basis(self):
        rewrite(self.path,lambda m:m['lineage'].update(price_basis='UNKNOWN'))
        bp=binding(self.path);r=self.report(broker_binding_path=bp);self.safe(r,broker_binding_path=bp)
        self.assertEqual(r['inventory']['declared_price_basis'],'UNKNOWN')
        self.assertEqual(gap(r,'PRICE_BASIS')['verification_status'],'UNVERIFIED')
        self.assertEqual(r['broker_reference']['claims']['chart_ohlc_basis'],'BID')
    def test_provider_name_is_not_a_broker_binding(self):
        rewrite(self.path,lambda m:m['source'].update(name='EXNESS CLAIMED BY OPERATOR'))
        r=self.report();self.safe(r)
        self.assertEqual(r['broker_comparison']['applicability'],'UNVERIFIED');self.assertIsNone(r['broker_comparison']['evaluated_bars'])
    def test_non_exness_never_gets_exness_session_rules(self):
        self.path=shifted(self.path);bp=binding(self.path,'NON_EXNESS')
        r=self.report(broker_binding_path=bp);self.safe(r,broker_binding_path=bp)
        self.assertEqual(r['broker_comparison']['applicability'],'NOT_APPLICABLE');self.assertEqual(r['broker_comparison']['observations'],[])
    def test_scope_binding_tamper_is_not_silently_accepted(self):
        bp=binding(self.path);b=json.loads(bp.read_text());b['dataset_id']='a'*64;bp.write_text(json.dumps(b))
        r=self.report(broker_binding_path=bp);self.safe(r,broker_binding_path=bp)
        self.assertEqual(gap(r,'EVIDENCE_REFERENCES')['verification_status'],'CONTRADICTED')
        self.assertEqual(r['broker_comparison']['applicability'],'UNVERIFIED')
    def test_partial_m5_at_2158_and_closed_period_rows_are_identified_conditionally(self):
        self.path=shifted(self.path);bp=binding(self.path)
        r=self.report(broker_binding_path=bp);self.safe(r,broker_binding_path=bp)
        rows=r['broker_comparison']['observations'];bar=next(x for x in rows if x['timeframe']=='M5' and '21:55:00' in x['open_utc'])
        self.assertEqual(bar['reported_quote_seconds'],180);self.assertEqual(bar['classification'],'PARTIAL_QUOTE_INTERVAL')
        self.assertGreater(r['broker_comparison']['closed_quote_conflicts'],0)
        self.assertEqual(gap(r,'BROKER_SESSION_COMPATIBILITY')['verification_status'],'CONTRADICTED')
        self.assertIsNone(r['mechanical']['frames']['M5']['partial_session_bars']) # No supplied calendar was silently installed.
    def test_close_only_quotations_do_not_authorize_opening(self):
        self.path=shifted(self.path,clock='23:00:00');bp=binding(self.path)
        r=self.report(broker_binding_path=bp);self.safe(r,broker_binding_path=bp)
        first=next(x for x in r['broker_comparison']['observations'] if x['timeframe']=='M5')
        self.assertEqual(first['classification'],'QUOTED_WITH_CLOSE_ONLY_PORTION');self.assertFalse(first['new_position_permission'])
        after=next(x for x in r['broker_comparison']['observations'] if '23:02:00' in x['open_utc'])
        self.assertIsNone(after['new_position_permission']);self.assertFalse(after['iat_execution_allowed'])
    def test_friday_reopening_remains_unknown(self):
        self.path=shifted(self.path,day='2026-11-13',clock='23:00:00');bp=binding(self.path)
        r=self.report(broker_binding_path=bp);self.safe(r,broker_binding_path=bp)
        self.assertGreater(r['broker_comparison']['friday_ambiguous_bars'],0)
        self.assertTrue(all(x['classification']=='FRIDAY_REOPEN_UNRESOLVED' for x in r['broker_comparison']['observations']))
        self.assertTrue(all(x['new_position_permission'] is None for x in r['broker_comparison']['observations']))
    def test_2021_or_other_dates_do_not_inherit_2026_exness_rules(self):
        self.path=shifted(self.path,day='2021-05-25',clock='08:00:00');bp=binding(self.path)
        r=self.report(broker_binding_path=bp);self.safe(r,broker_binding_path=bp)
        self.assertEqual(r['broker_comparison']['applicability'],'NOT_APPLICABLE')
    def test_complete_on_paper_review_is_still_not_authenticated_or_qualified(self):
        self.path=v2_fixture(self.root,count=120,evaluation_minutes=60,historical=True,calendar=True)
        rp,doc=review_fixture(self.root,self.path)
        r=self.report(independent_review_path=rp);self.safe(r,independent_review_path=rp)
        self.assertEqual(gap(r,'SOURCE_AUTHENTICITY')['verification_status'],'PARTIALLY_VERIFIED')
        self.assertEqual(r['existing_qualification']['status'],'DATA_NOT_QUALIFIED')
        self.assertIn('SYNTHETIC_CALENDAR_NOT_REAL_EVIDENCE',r['existing_qualification']['reason_codes'])
    def test_even_existing_gate_pass_is_only_a_separate_attestation_result(self):
        self.path=v2_fixture(self.root,count=120,evaluation_minutes=60,historical=True,calendar=True)
        rp,_=review_fixture(self.root,self.path);ds=load_dataset(self.path)
        mock=replace(ds,calendar=replace(ds.calendar,provenance_kinds=('PUBLISHED',)))
        with patch('iat.pilot_qualification.load_dataset',return_value=mock):
            r=self.report(independent_review_path=rp);self.safe(r,independent_review_path=rp)
        self.assertEqual(r['existing_qualification']['status'],'HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED')
        self.assertEqual(gap(r,'INDEPENDENT_QUALIFICATION')['verification_status'],'PARTIALLY_VERIFIED')
        self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED')
    def test_document_bytes_tamper_remains_a_reference_conflict(self):
        self.path=v2_fixture(self.root,count=120,evaluation_minutes=60,historical=True,calendar=True)
        rp,doc=review_fixture(self.root,self.path);doc.write_bytes(b'CHANGED')
        r=self.report(independent_review_path=rp);self.safe(r,independent_review_path=rp)
        self.assertEqual(gap(r,'EVIDENCE_REFERENCES')['verification_status'],'CONTRADICTED')
    def test_original_hash_is_available_only_after_normalization_reproduction(self):
        spec=export_fixture(self.root);prepare_package(spec,self.root/'package');self.path=self.root/'package'/'candidate-manifest.json'
        r=self.report(import_spec_path=spec);self.safe(r,import_spec_path=spec)
        self.assertEqual(gap(r,'NORMALIZATION_TRACE')['verification_status'],'VERIFIED')
        s=json.loads(spec.read_text())
        for tf in ('M1','M5'):
            self.assertEqual(r['inventory']['frames'][tf]['original_import_sha256'],sha256((self.root/s['frames'][tf]['file']).read_bytes()).hexdigest())
        self.assertEqual(r['inventory']['original_timezone_declaration'],'UTC')
    def test_transform_reference_for_different_rows_is_contradicted(self):
        spec=export_fixture(self.root)
        r=self.report(import_spec_path=spec);self.safe(r,import_spec_path=spec)
        self.assertEqual(gap(r,'NORMALIZATION_TRACE')['verification_status'],'CONTRADICTED')
        self.assertIsNone(r['inventory']['frames']['M1']['original_import_sha256'])
    def test_corrections_unknown_and_missing_spread_do_not_become_verified(self):
        r=self.report();self.safe(r)
        self.assertEqual(r['inventory']['spread_availability'],'UNKNOWN')
        self.assertEqual(gap(r,'CORRECTIONS')['verification_status'],'UNVERIFIED')
        self.assertIsNone(gap(r,'SPREAD_INFORMATION')['blocking_reason'])
    def test_retrieval_before_declared_bar_close_is_a_mechanical_conflict(self):
        rewrite(self.path,lambda m:m['source'].update(retrieved_at_utc='2026-11-12T08:10:00Z'))
        r=self.report();self.safe(r)
        self.assertGreater(r['mechanical']['frames']['M1']['closed_after_declared_retrieval_count'],0)
        self.assertEqual(gap(r,'CANDLE_INTEGRITY')['verification_status'],'CONTRADICTED')
    def test_source_registry_is_bound_to_exact_files_and_dates(self):
        rp=registry_for(self.path)
        r=self.report(source_registry_path=rp);self.safe(r,source_registry_path=rp)
        self.assertIsNotNone(r['source_review'])
        self.assertEqual(next(x for x in r['references'] if x['role']=='source_registry')['binding'],'VERIFIED')
        registry=json.loads(rp.read_text());registry['manifest_reference']['dataset_fingerprints']['M1']='a'*64;rp.write_text(json.dumps(registry))
        r=self.report(source_registry_path=rp);self.safe(r,source_registry_path=rp)
        self.assertEqual(gap(r,'EVIDENCE_REFERENCES')['verification_status'],'CONTRADICTED')
    def test_replay_diagnostics_bind_to_this_dataset_only(self):
        replay=run(self.path,observation_times=[(START+timedelta(minutes=20)).isoformat()])
        rp=self.root/'replay.json';rp.write_text(json.dumps(replay))
        r=self.report(replay_report_path=rp);self.safe(r,replay_report_path=rp)
        self.assertIsNotNone(r['replay_evidence']);self.assertEqual(r['replay_evidence']['observation_count'],1)
        rewrite(self.path,lambda m:m['source'].update(curation_id='OTHER'))
        r=self.report(replay_report_path=rp);self.safe(r,replay_report_path=rp)
        self.assertEqual(gap(r,'EVIDENCE_REFERENCES')['verification_status'],'CONTRADICTED')
    def test_report_is_deterministic_and_does_not_modify_original_inputs(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        a=self.report();b=self.report();self.assertEqual(a,b);self.safe(json.loads(json.dumps(a)))
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
        self.assertEqual([g['code'] for g in a['gaps']],sorted(g['code'] for g in a['gaps']))
        self.assertEqual(len({g['gap_id'] for g in a['gaps']}),len(a['gaps']))
    def test_pinned_broker_metadata_has_no_raw_correspondence_or_account_details(self):
        b=broker_reference();self.assertEqual(b['source_commit'],BROKER_COMMIT);self.assertEqual(b['sha256'],BROKER_SHA)
        s=json.dumps(b);self.assertNotIn('Thank you for contacting',s)
        for key in ('account_number','server','password','reviewer_code'):self.assertNotIn(key,s)
    def test_json_schema_rejects_unknown_fields(self):
        self.schema.check_schema(self.schema.schema)
        r=self.report();r['untrusted_approval']=True
        self.assertTrue(list(self.schema.iter_errors(r)))
    def test_unknown_report_version_and_checksum_are_rejected(self):
        for change in (lambda r:r.update(assessment_version=2),lambda r:r.update(assessment_version=True),lambda r:r.update(sha256='a'*64)):
            r=self.report();change(r)
            with self.assertRaises(ValueError):validate_provenance_assessment(r,self.path)
    def test_source_changes_after_report_prevent_semantic_validation(self):
        r=self.report();rewrite(self.path,lambda m:m['source'].update(curation_id='changed'))
        with self.assertRaises(ValueError):validate_provenance_assessment(r,self.path)
    def test_cli_private_atomic_exports_no_overwrite_or_raw_support(self):
        dest=self.root/'private-report.json';txt=self.root/'summary.txt';out=StringIO()
        args=['--manifest',str(self.path),'--json-output',str(dest),'--text-output',str(txt)]
        with redirect_stdout(out):self.assertEqual(main(args),3)
        report=json.loads(dest.read_text());self.safe(report)
        self.assertEqual(txt.read_text(encoding='utf-8'),provenance_text(report))
        self.assertNotIn('Thank you for contacting',dest.read_text());self.assertNotIn('reviewer_code',dest.read_text())
        before=dest.read_bytes()
        with redirect_stdout(StringIO()):self.assertEqual(main(args),1)
        self.assertEqual(dest.read_bytes(),before)
    def test_cli_missing_dataset_produces_gaps_not_approval(self):
        dest=self.root/'none.json';txt=self.root/'none.txt'
        with redirect_stdout(StringIO()):self.assertEqual(main(['--json-output',str(dest),'--text-output',str(txt)]),3)
        r=json.loads(dest.read_text());self.schema.validate(r);self.assertIsNone(r['inventory'])
    def test_cli_publication_failure_does_not_publish_success(self):
        dest=self.root/'fail.json';txt=self.root/'fail.txt'
        target='iat.chart_benchmark.os.rename' if __import__('os').name=='nt' else 'iat.chart_benchmark.os.link'
        with patch(target,side_effect=OSError('SYNTHETIC_FAILURE')),redirect_stdout(StringIO()):
            self.assertEqual(main(['--manifest',str(self.path),'--json-output',str(dest),'--text-output',str(txt)]),1)
        self.assertFalse(dest.exists());self.assertFalse(txt.exists())
    def test_no_broker_network_clock_or_trading_imports(self):
        tree=ast.parse(Path('iat/provenance_assessment.py').read_text(encoding='utf-8'))
        names=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        names += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(any(bad in n.lower() for bad in ('metatrader','requests','socket','broker','random')) for n in names))
    def test_golden_synthetic_audit_and_metadata_catalog(self):
        p=Path('docs/research_audits/provenance-gap-analysis-synthetic-v1/audit.json')
        self.assertEqual(json.loads(p.read_text()),synthetic_audit())
        catalog=json.loads(Path('docs/source_reviews/provenance-gap-analysis-v1/available-sources.json').read_text())
        for r in catalog['metadata_references']:self.assertEqual(sha256(Path(r['path']).read_bytes()).hexdigest(),r['file_sha256'])
        self.assertTrue(all(not x['raw_market_bytes_inspected'] for x in catalog['sources']))


    def test_partial_cross_frame_coverage_is_not_reported_fully_verified(self):
        modify_frame(self.path,'M1',lambda rows:rows.pop(5))
        r=self.report();self.safe(r)
        self.assertEqual(r['mechanical']['alignment']['uncovered_m5_bars'],1)
        self.assertEqual(gap(r,'CROSS_FRAME_CONSISTENCY')['verification_status'],'PARTIALLY_VERIFIED')
    def test_nested_registry_references_are_not_assumed_verified(self):
        rp=registry_for(self.path);r=self.report(source_registry_path=rp);self.safe(r,source_registry_path=rp)
        self.assertIn('historical_evidence_manifest',r['source_review']['unverified_references'])
        self.assertEqual(gap(r,'EVIDENCE_REFERENCES')['verification_status'],'PARTIALLY_VERIFIED')
    def test_registry_calendar_reference_must_match_when_available(self):
        self.path=v2_fixture(self.root,count=30,evaluation_minutes=10,calendar=True)
        rp=registry_for(self.path);r=self.report(source_registry_path=rp);self.safe(r,source_registry_path=rp)
        self.assertEqual(gap(r,'EVIDENCE_REFERENCES')['verification_status'],'CONTRADICTED')
    def test_quote_basis_does_not_overwrite_ask_export_declaration(self):
        rewrite(self.path,lambda m:m['lineage'].update(price_basis='ASK'))
        bp=binding(self.path);r=self.report(broker_binding_path=bp);self.safe(r,broker_binding_path=bp)
        self.assertEqual(r['inventory']['declared_price_basis'],'ASK')
        self.assertEqual(gap(r,'PRICE_BASIS')['verification_status'],'PARTIALLY_VERIFIED')
    def test_missing_optional_reference_stays_unverified(self):
        r=self.report(source_registry_path=self.root/'absent.json')
        self.safe(r,source_registry_path=self.root/'absent.json')
        self.assertEqual(gap(r,'EVIDENCE_REFERENCES')['verification_status'],'UNVERIFIED')
    def test_broker_reference_payload_cannot_be_rehashed_to_new_claims(self):
        b=broker_reference();b['claims']['chart_ohlc_basis']='ASK';rehash(b)
        with patch.object(Path,'read_bytes',return_value=json.dumps(b).encode()):
            with self.assertRaises(ValueError):broker_reference()
    def test_no_approval_override_or_qualification_argument_exists(self):
        with self.assertRaises(TypeError):assess_historical_provenance(self.path,qualified=True)
    def test_all_declared_gap_references_resolve_and_labels_do_not_grant_access(self):
        r=self.report();ids={v['reference_id'] for v in r['references']}
        for g in r['gaps']:self.assertTrue(set(g['source_references'])<=ids)
        self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED');self.assertFalse(r['execution_allowed'])


    def test_missing_originals_are_unverified_not_a_fabricated_data_contradiction(self):
        spec=export_fixture(self.root);details=json.loads(spec.read_text())
        (self.root/details['frames']['M1']['file']).unlink()
        r=self.report(import_spec_path=spec);self.safe(r,import_spec_path=spec)
        self.assertEqual(gap(r,'NORMALIZATION_TRACE')['verification_status'],'UNVERIFIED')
        self.assertEqual(gap(r,'EVIDENCE_REFERENCES')['verification_status'],'UNVERIFIED')
        self.assertIsNone(r['inventory']['frames']['M1']['original_import_sha256'])


def tamper(name,change):
    def test(self):
        r=self.report();change(r);rehash(r)
        with self.assertRaises((ValueError,TypeError,KeyError)):validate_provenance_assessment(r,self.path)
    setattr(ProvenanceAssessmentTests,'test_rechecksummed_tamper_'+name,test)

for name,change in {
 'label':lambda r:gap(r,'SOURCE_AUTHENTICITY').update(verification_status='VERIFIED'),
 'reason':lambda r:gap(r,'INDEPENDENT_QUALIFICATION').update(blocking_reason=None),
 'scope':lambda r:gap(r,'FILE_INTEGRITY')['scope'].update(dataset_id='a'*64),
 'id':lambda r:gap(r,'FILE_INTEGRITY').update(gap_id='a'*64),
 'source_reference':lambda r:gap(r,'FILE_INTEGRITY').update(source_references=['MANIFEST:'+'a'*64]),
 'references':lambda r:r['references'][0].update(binding='VERIFIED',file_sha256='a'*64),
 'broker_commit':lambda r:r['broker_reference'].update(source_commit='a'*40),
 'price':lambda r:r['inventory'].update(declared_price_basis='ASK'),
 'normalization':lambda r:r['inventory']['normalization'].update(verification_status='VERIFIED'),
 'qualification':lambda r:r.update(qualification='DATA_QUALIFIED'),
 'historical':lambda r:r.update(historical_validation='PASSED'),
 'execution':lambda r:r.update(execution_allowed=True),
 'signal':lambda r:r.update(signal='BUY'),
 'unknown_denominator':lambda r:r['evidence_coverage']['independent_authenticity'].update(denominator=0),
 'raw_support':lambda r:r.update(raw_correspondence='must not be present'),
}.items():tamper(name,change)
