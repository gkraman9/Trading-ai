"""Synthetic source statements and review declarations, never fabricated Exness evidence."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import json,tempfile,unittest
from iat.independent_source_evidence import (review_registry,validate_registry,validate_source_report,read_registry,KIND,
    SESSION_FIELDS,PRICE_FIELDS,CRITERIA)
from iat.historical_evidence_manifest import REQUIRED_CODES,qualification_gate
from iat.chart_benchmark import hashed,write_new
from iat.replay_dataset import digest,load_dataset,DatasetError
from diagnostics.independent_source_review import main

EXAMPLE=Path('config/examples/independent-source-review/exness-review-v1.json')


def fixture():
    r=json.loads(EXAMPLE.read_text());r.update(data_kind='SYNTHETIC_FIXTURE',collector_id='synthetic-collector')
    r['context'].update(broker='Synthetic Broker',account_scope='synthetic-demo')
    r['claims']=[{'id':'close','category':'dated_sessions_timezone_dst','predicate':'quote_close_utc',
        'candidate_value':'21:58:00','description':'SYNTHETIC closing assertion, not broker evidence.'}]
    e=deepcopy(r['evidence'][0]);e.update(id='source-a',claim_id='close',value='21:58:00',publisher='Synthetic Publisher',title='SYNTHETIC schedule document',
        reference='synthetic:schedule-a',published_at_utc='2026-11-01T00:00:00Z',retrieved_at_utc='2026-11-15T00:00:00Z',
        effective_start_utc='2026-11-01T00:00:00Z',effective_end_utc='2026-12-01T00:00:00Z',
        broker='Synthetic Broker',account_scope='synthetic-demo',account_category='DEMO',instrument='XAUUSD',summary='SYNTHETIC statement used only to exercise review logic.',
        collection_method='SYNTHETIC_FIXTURE',verification_status='ARTIFACT_PROVIDED',reviewer_notes=None,conflicting_references=[],
        quotation_timezone='UTC',trading_timezone='UTC',dst_rule='SYNTHETIC UTC convention',wall_time_anchors=[],
        session_details=dict.fromkeys(SESSION_FIELDS),price_details=dict.fromkeys(PRICE_FIELDS),limitations=['SYNTHETIC only'])
    r.update(evidence=[e],reviews=[]);return r


def reviewer(r,id='review-a',evidence_ids=None,conclusion='SUPPORTS'):
    return {'id':id,'reviewer_id':'synthetic-reviewer-'+id,'reviewed_at_utc':'2026-11-16T00:00:00Z',
        'evidence_ids':evidence_ids or ['source-a'],'claim_id':'close','scope':deepcopy(r['context']),'conclusion':conclusion,
        'criteria':dict.fromkeys(CRITERIA,'SUPPORTED'),'unresolved_conflicts':[],
        'explanation':'SYNTHETIC reasoned review, not authentic independent approval.',
        'provenance':{'method':'MANUAL_REVIEW_DECLARATION_NOT_AUTHENTICATED','document':'synthetic-review.txt','sha256':'a'*64}}


class IndependentSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.r=fixture()
        self.artifact=self.root/'synthetic-source.txt';self.artifact.write_bytes(b'SYNTHETIC source assertion: close 21:58 UTC. Not real broker evidence.\n')
        self.r['evidence'][0]['artifact']={'file':self.artifact.name,'sha256':digest(self.artifact.read_bytes())}
    def tearDown(self):self.temp.cleanup()
    def report(self,r=None):return review_registry(self.r if r is None else r,artifact_root=self.root)
    def classification(self,report=None):return (self.report() if report is None else report)['claim_matrix'][0]['classification']
    def source(self,report=None):return (self.report() if report is None else report)['source_assessments'][0]
    def safety(self,p):
        validate_source_report(p);self.assertEqual(p['qualification_gate'] if 'qualification_gate' in p else p['qualification'],'DATA_NOT_QUALIFIED')
        gate=qualification_gate(None)
        for k,v in gate.items():
            if k!='reason_codes':self.assertEqual(p[k],v)
        self.assertTrue(set(REQUIRED_CODES)|{'INDEPENDENT_QUALIFICATION_REQUIRED'}<=set(p['reason_codes']))
        self.assertFalse(p['calendar_modifications']);self.assertEqual(p['missing_evidence'],list(p['coverage']))
    def test_valid_source_schema_and_no_review_implies_not_reviewed(self):
        self.assertTrue(validate_registry(self.r));p=self.report();self.assertEqual(self.classification(p),'NOT_REVIEWED');self.safety(p)
    def test_missing_source_reference(self):
        self.r['evidence'][0]['reference']=None;self.assertEqual(self.classification(),'SOURCE_UNAVAILABLE')
    def test_no_source_at_all(self):
        self.r['evidence']=[];self.assertEqual(self.classification(),'INSUFFICIENT_EVIDENCE')
    def test_unsupported_source_category(self):
        self.r['evidence'][0]['category']='profits'
        with self.assertRaises(ValueError):self.report()
    def test_invalid_evidence_date(self):
        self.r['evidence'][0]['retrieved_at_utc']='2026-99-99'
        with self.assertRaises(ValueError):self.report()
    def test_future_published_or_retrieved_source_is_unresolved(self):
        for field in ('published_at_utc','retrieved_at_utc'):
            r=deepcopy(self.r);r['evidence'][0][field]='2027-01-01T00:00:00Z';p=self.report(r)
            self.assertIn('SOURCE_FUTURE_DATED',self.source(p)['reason_codes']);self.assertNotEqual(self.classification(p),'SUPPORTED_WITH_APPLICABILITY')
    def test_historical_effective_date_mismatch(self):
        self.r['evidence'][0]['effective_end_utc']='2026-11-05T00:00:00Z';self.assertEqual(self.classification(),'INSUFFICIENT_EVIDENCE')
    def test_unknown_effective_end_is_not_inferred(self):
        self.r['evidence'][0]['effective_end_utc']=None;self.assertEqual(self.classification(),'SOURCE_PRESENT_APPLICABILITY_UNKNOWN')
    def test_wrong_instrument(self):
        self.r['evidence'][0]['instrument']='XAUUSD247';self.assertIn('SOURCE_INSTRUMENT_MISMATCH',self.source()['reason_codes'])
    def test_wrong_account(self):
        self.r['evidence'][0]['account_scope']='different-demo';self.assertIn('SOURCE_ACCOUNT_SCOPE_MISMATCH',self.source()['reason_codes'])
    def test_unknown_account_is_not_inferred_from_broker_url(self):
        self.r['evidence'][0]['account_scope']=None;self.assertEqual(self.classification(),'SOURCE_PRESENT_APPLICABILITY_UNKNOWN')
    def test_wrong_broker(self):
        self.r['evidence'][0]['broker']='Other Broker';self.assertIn('SOURCE_BROKER_MISMATCH',self.source()['reason_codes'])
    def test_unsupported_timezone(self):
        self.r['evidence'][0]['quotation_timezone']='Invalid/Unsupported';self.assertIn('TIMEZONE_UNSUPPORTED',self.source()['reason_codes'])
    def test_dst_ambiguity_is_not_silently_folded(self):
        self.r['evidence'][0]['wall_time_anchors']=[{'local':'2026-11-01T01:30:00','timezone':'America/New_York','expected_utc':None}]
        self.assertIn('SESSION_TIME_AMBIGUOUS',self.source()['reason_codes'])
    def test_dst_nonexistent_time_is_not_silently_shifted(self):
        self.r['evidence'][0]['wall_time_anchors']=[{'local':'2026-03-08T02:30:00','timezone':'America/New_York','expected_utc':None}]
        self.assertIn('SESSION_TIME_NONEXISTENT',self.source()['reason_codes'])
    def test_explicit_utc_anchor_mismatch(self):
        self.r['evidence'][0]['wall_time_anchors']=[{'local':'2026-11-11T21:58:00','timezone':'UTC','expected_utc':'2026-11-11T22:58:00Z'}]
        self.assertIn('WALL_TIME_UTC_CONFLICT',self.source()['reason_codes'])
    def test_conflicting_close_values_preserve_both_and_candidate(self):
        e=deepcopy(self.r['evidence'][0]);e.update(id='source-b',reference='synthetic:alternative',value='21:59:00');self.r['evidence'].append(e)
        p=self.report();m=p['claim_matrix'][0];self.assertEqual(m['classification'],'CONFLICTING_EVIDENCE')
        self.assertEqual(m['claim']['candidate_value'],'21:58:00');self.assertEqual({v['value'] for v in m['source_values']},{'21:58:00','21:59:00'});self.safety(p)
    def test_source_count_cannot_vote_away_a_conflict(self):
        e=deepcopy(self.r['evidence'][0]);e.update(id='source-b',value='22:00:00');self.r['evidence'].append(e)
        for i in range(5):
            e=deepcopy(self.r['evidence'][0]);e['id']='same-claim-'+str(i);self.r['evidence'].append(e)
        self.assertEqual(self.classification(),'CONFLICTING_EVIDENCE')
    def test_different_historical_period_is_excluded_from_active_contradictions(self):
        e=deepcopy(self.r['evidence'][0]);e.update(id='summer',value='20:58:00',effective_start_utc='2026-05-01T00:00:00Z',effective_end_utc='2026-10-01T00:00:00Z');self.r['evidence'].append(e)
        self.assertNotEqual(self.classification(),'CONFLICTING_EVIDENCE');self.assertEqual(len(self.report()['claim_matrix'][0]['source_values']),2)
    def test_unsupported_holiday_assumption_does_not_clear_gap(self):
        self.r['evidence'][0]['session_details']['holiday_exceptions']='No holidays asserted without evidence.'
        self.assertEqual(self.report()['coverage']['holidays_special_closures']['status'],'UNRESOLVED')
    def test_missing_maintenance_evidence_remains_visible(self):self.assertIn('maintenance_interruptions',self.report()['missing_evidence'])
    def test_unknown_price_basis_remains_visible(self):self.assertIn('historical_price_basis',self.report()['missing_evidence'])
    def test_missing_candle_finality_remains_visible(self):
        p=self.report();self.assertIn('candle_finality_corrections',p['missing_evidence']);self.assertIn('CANDLE_FINALITY_UNCERTAIN',p['reason_codes'])
    def test_incorrect_artifact_hash(self):
        self.r['evidence'][0]['artifact']['sha256']='a'*64;self.assertEqual(self.source()['source_integrity']['status'],'MISMATCH');self.assertEqual(self.classification(),'SOURCE_UNAVAILABLE')
    def test_one_byte_source_tamper(self):
        self.artifact.write_bytes(self.artifact.read_bytes()+b' ');self.assertEqual(self.source()['source_integrity']['status'],'MISMATCH')
    def test_source_hash_match_does_not_authenticate_publisher(self):
        p=self.report();self.assertEqual(self.source(p)['source_integrity']['status'],'MATCH');self.assertEqual(self.source(p)['source_authority'],'DECLARED_PUBLISHER_IDENTIFIABLE_NOT_AUTHENTICATED');self.safety(p)
    def test_explicit_conflicting_references_preserved(self):
        e=deepcopy(self.r['evidence'][0]);e['id']='source-b';self.r['evidence'].append(e);self.r['evidence'][0]['conflicting_references']=['source-b'];self.assertEqual(self.classification(),'CONFLICTING_EVIDENCE')
    def test_dangling_conflicting_reference_is_invalid(self):
        self.r['evidence'][0]['conflicting_references']=['nonexistent']
        with self.assertRaises(ValueError):self.report()
    def test_unreviewed_evidence_is_not_approved(self):self.assertEqual(self.source()['independent_review']['status'],'NOT_REVIEWED')
    def test_supported_review_is_a_declaration_and_never_qualifies(self):
        self.r['reviews']=[reviewer(self.r)];p=self.report();self.assertEqual(self.classification(p),'SUPPORTED_WITH_APPLICABILITY');self.safety(p)
        self.assertEqual(p['review_authenticity'],'NOT_EXTERNALLY_AUTHENTICATED_NO_APPROVAL_GRANTED')
    def test_acknowledgement_is_not_support_or_qualification(self):
        self.r['reviews']=[reviewer(self.r,conclusion='ACKNOWLEDGED')];self.assertEqual(self.source()['claim_support'],'ACKNOWLEDGED_ONLY');self.assertNotEqual(self.classification(),'SUPPORTED_WITH_APPLICABILITY')
    def test_self_review_is_not_independent(self):
        self.r['reviews']=[reviewer(self.r)];self.r['reviews'][0]['reviewer_id']=self.r['collector_id']
        with self.assertRaises(ValueError):self.report()
    def test_forged_approval_fields_are_rejected(self):
        self.r['evidence'][0]['approved']=True
        with self.assertRaises(ValueError):self.report()
    def test_approved_is_not_a_permitted_review_conclusion(self):
        self.r['reviews']=[reviewer(self.r,conclusion='APPROVED')]
        with self.assertRaises(ValueError):self.report()
    def test_reviewer_disagreement_is_not_erased(self):
        self.r['reviews']=[reviewer(self.r),reviewer(self.r,id='review-b',conclusion='REJECTS')];p=self.report();self.assertEqual(self.classification(p),'CONFLICTING_EVIDENCE');self.safety(p)
    def test_future_or_wrong_scope_review_is_unresolved(self):
        for field in ('date','scope'):
            r=deepcopy(self.r);v=reviewer(r)
            if field=='date':v['reviewed_at_utc']='2027-01-01T00:00:00Z'
            else:v['scope']['account_scope']='other-scope'
            r['reviews']=[v];p=self.report(r);self.assertNotEqual(self.classification(p),'SUPPORTED_WITH_APPLICABILITY');self.assertIn('REVIEW_DATE_OR_SCOPE_UNSUPPORTED',self.source(p)['reason_codes'])
    def test_duplicate_evidence_ids(self):
        self.r['evidence'].append(deepcopy(self.r['evidence'][0]))
        with self.assertRaises(ValueError):self.report()
    def test_unsafe_artifact_paths(self):
        for value in ('../private.txt','C:\\private.txt','/tmp/private.txt','dir/private.txt','\\\\server\\share\\file.txt'):
            r=deepcopy(self.r);r['evidence'][0]['artifact']['file']=value
            with self.assertRaises(ValueError):self.report(r)
    def test_network_unc_root_and_url_credentials_rejected(self):
        for root in ('\\\\server\\share','//server/share','https://example.invalid'):
            with self.assertRaises(ValueError):review_registry(self.r,artifact_root=root)
        self.r['evidence'][0]['reference']='https://user:password@example.invalid/source'
        with self.assertRaises(ValueError):self.report()
    def test_registry_size_and_malformed_json(self):
        p=self.root/'registry.json'
        for raw in (b' '*262145,b'{bad',b'{"registry_version":1,"registry_version":1}'):
            p.write_bytes(raw)
            with self.assertRaises(ValueError):read_registry(p)
    def test_unsupported_schema_version(self):
        self.r['registry_version']=2
        with self.assertRaises(ValueError):self.report()
    def test_source_limits(self):
        self.r['evidence']=[deepcopy(self.r['evidence'][0]) for _ in range(65)]
        with self.assertRaises(ValueError):self.report()
    def test_large_source_artifact_is_unavailable_not_supported(self):
        with self.artifact.open('r+b') as f:f.truncate(4*1024*1024+1)
        self.assertEqual(self.source()['source_integrity']['status'],'UNAVAILABLE')
    def test_deterministic_output_and_record_order(self):
        e=deepcopy(self.r['evidence'][0]);e['id']='source-b';self.r['evidence'].append(e)
        p=self.report();self.r['evidence'].reverse();self.assertEqual(p,self.report())
    def test_no_mutation_of_registry_artifacts_or_calendar(self):
        calendar=Path('config/profiles/exness-xauusd-v2.candidate.json');before=calendar.read_bytes();original=deepcopy(self.r);artifact=self.artifact.read_bytes()
        p=self.report();self.assertEqual(original,self.r);self.assertEqual(before,calendar.read_bytes());self.assertEqual(artifact,self.artifact.read_bytes());self.safety(p)
    def test_source_packet_and_registry_are_not_replay_inputs(self):
        for obj in (self.report(),self.r):
            p=self.root/'not-dataset.json';p.write_text(json.dumps(obj))
            with self.assertRaisesRegex(DatasetError,'EVIDENCE_MANIFEST_NOT_REPLAY_ELIGIBLE'):load_dataset(p)
    def test_no_network_mt5_orders_or_profitability(self):
        with patch('socket.create_connection',side_effect=AssertionError('Network forbidden')),patch.dict('sys.modules',{'MetaTrader5':None}):p=self.report()
        self.safety(p);self.assertFalse(p['safety']['broker_access']);self.assertEqual(p['safety']['orders_requested'],0);self.assertFalse(p['safety']['profitability_tested'])
    def test_rehashed_packet_cannot_downgrade_safety_or_remove_blockers(self):
        for field,value in (('qualification','DATA_QUALIFIED'),('ordinary_strategy_inputs_allowed',True),('review_packets_allowed',True),('historical_comparisons','PASS')):
            p=self.report();p.pop('sha256');p[field]=value
            with self.assertRaises(ValueError):validate_source_report(hashed(p))
        p=self.report();p.pop('sha256');p['reason_codes'].remove('INDEPENDENT_QUALIFICATION_REQUIRED')
        with self.assertRaises(ValueError):validate_source_report(hashed(p))
    def cli(self,**extra):
        registry=self.root/'registry.json';registry.write_text(json.dumps(self.r));output=extra.pop('output',self.root/'review.json')
        args=['--registry',str(registry),'--report-path',str(output)]
        for k,v in extra.items():args+=['--'+k,str(v)]
        with redirect_stdout(StringIO()) as out:code=main(args)
        return code,out.getvalue(),output
    def test_cli_report_is_blocked_and_contains_no_personal_paths(self):
        code,out,path=self.cli(**{'artifact-root':self.root});self.assertEqual(code,3)
        p=json.loads(path.read_text());validate_source_report(p);self.assertNotIn(str(self.root),json.dumps(p));self.assertNotIn(str(self.root),out)
    def test_existing_destination_and_traversal_output_rejected(self):
        p=self.root/'existing.json';p.write_bytes(b'ORIGINAL');code,_,_=self.cli(output=p);self.assertEqual(code,2);self.assertEqual(p.read_bytes(),b'ORIGINAL')
        code,_,_=self.cli(output=self.root/'..'/'outside.json');self.assertEqual(code,2)
    def test_missing_artifact_and_missing_manifest_are_explicit(self):
        self.artifact.unlink();self.assertEqual(self.source()['source_integrity']['status'],'UNAVAILABLE')
        p=review_registry(self.r,manifest_path=self.root/'missing.json');self.assertEqual(p['local_manifest_inspection']['status'],'INVALID_OR_CONFLICTING_MANIFEST');self.safety(p)
    def test_public_reference_example_has_no_fabricated_approval_or_artifact_hashes(self):
        r=json.loads(EXAMPLE.read_text());validate_registry(r);p=review_registry(r);self.safety(p);self.assertEqual(r['reviews'],[])
        self.assertTrue(all(e['artifact'] is None for e in r['evidence'] if e['collection_method']=='MANUAL_PUBLIC_TEXT_REVIEW'))
        self.assertEqual(p['local_manifest_inspection']['status'],'NOT_SUPPLIED')
    def test_one_supported_review_cannot_erase_another_reviewers_uncertainty(self):
        self.r['reviews']=[reviewer(self.r),reviewer(self.r,id='uncertain')];self.r['reviews'][1]['criteria']['claim_support']='UNRESOLVED'
        self.assertNotEqual(self.classification(),'SUPPORTED_WITH_APPLICABILITY')
    def test_local_manifest_is_inspected_without_rerunning_csvs(self):
        from test_historical_evidence_manifest import EvidenceManifestTests
        case=EvidenceManifestTests();case.setUp()
        try:
            case.fixture();m=case.verify();path=self.root/'private-manifest.json';write_new(path,m)
            ref=self.r['manifest_reference'];ref['manifest_payload_sha256']=m['sha256'];ref['diagnostic_payload_sha256']=m['reproduction']['diagnostic_payload_sha256']
            ref['dataset_fingerprints']={tf:m['local_facts'][tf]['file_fingerprint']['sha256'] for tf in ('M1','M5','diagnostic','calendar')}
            self.r['context']['interval']=m['operator_assertions']['window']
            with patch('iat.historical_evidence_manifest.verify_local',side_effect=AssertionError('No raw replay here')):p=review_registry(self.r,manifest_path=path)
            self.assertEqual(p['local_manifest_inspection']['status'],'LOCAL_MANIFEST_BYTES_INSPECTED');self.assertEqual(p['local_manifest_inspection']['raw_csv_reproduction'],'NOT_RUN');self.safety(p)
            ref['dataset_fingerprints']['M1']='b'*64;p=review_registry(self.r,manifest_path=path)
            self.assertEqual(p['local_manifest_inspection']['status'],'INVALID_OR_CONFLICTING_MANIFEST');self.safety(p)
        finally:case.tearDown()
    def test_wrong_local_manifest_payload_is_not_an_independent_verification(self):
        from iat.historical_evidence_manifest import create_manifest
        o=json.loads(Path('config/examples/historical-evidence/operator-reported-v1.json').read_text());path=self.root/'wrong-manifest.json';write_new(path,create_manifest(o))
        p=review_registry(self.r,manifest_path=path);self.assertEqual(p['local_manifest_inspection']['status'],'INVALID_OR_CONFLICTING_MANIFEST');self.safety(p)
    def test_unknown_price_basis_cannot_be_inferred_from_spread(self):
        self.r['evidence'][0]['price_details'].update(price_basis='UNKNOWN',spread_representation='Column named spread exists.')
        p=self.report();self.assertEqual(p['coverage']['historical_price_basis']['status'],'UNRESOLVED');self.safety(p)
    def test_document_reference_is_not_automatically_read(self):
        self.r['evidence'][0]['artifact']=None;self.r['evidence'][0]['reference']='document:not-present.pdf'
        p=self.report();self.assertEqual(self.source(p)['source_integrity']['status'],'NOT_SUPPLIED');self.safety(p)
    def test_cli_malformed_input_failure_keeps_all_blockers(self):
        path=self.root/'bad.json';path.write_text('['*2000+'0'+']'*2000);output=self.root/'bad-result.json'
        with redirect_stdout(StringIO()):code=main(['--registry',str(path),'--report-path',str(output)])
        self.assertEqual(code,2);p=json.loads(output.read_text());self.assertEqual(p['kind'],'HISTORICAL_SOURCE_REVIEW_INPUT_FAILURE');self.assertTrue(set(REQUIRED_CODES)<=set(p['reason_codes']));self.assertFalse(p['safety']['execution_allowed'])
    def test_artifact_symlink_does_not_escape_local_root(self):
        linked=self.root/'linked.txt'
        try:linked.symlink_to(self.artifact)
        except (OSError,NotImplementedError):self.skipTest('OS does not permit symbolic links')
        self.r['evidence'][0]['artifact']['file']='linked.txt';self.assertEqual(self.source()['source_integrity']['status'],'UNAVAILABLE')
    def test_impossible_session_clock_is_not_supported(self):
        self.r['evidence'][0]['value']='25:99:00'
        with self.assertRaises(ValueError):self.report()
    def test_wrong_account_category_is_not_inferred_as_equivalent(self):
        self.r['evidence'][0]['account_category']='LIVE';self.assertIn('SOURCE_ACCOUNT_CATEGORY_MISMATCH',self.source()['reason_codes'])
    def test_date_only_wall_anchor_does_not_infer_midnight(self):
        self.r['evidence'][0]['wall_time_anchors']=[{'local':'2026-11-11','timezone':'UTC','expected_utc':None}]
        with self.assertRaises(ValueError):self.report()
    def test_publication_after_retrieval_keeps_date_conflict_visible(self):
        self.r['evidence'][0]['published_at_utc']='2026-11-15T12:00:00Z';self.assertIn('SOURCE_DATE_CHRONOLOGY_CONFLICT',self.source()['reason_codes'])
