"""SYNTHETIC_ONLY pilot tests; mock approvals are not independent source evidence."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from io import StringIO
from pathlib import Path
import json,tempfile,unittest
from unittest.mock import patch
from iat.chart_benchmark import write_new,read_json,hashed
from iat.review_pilot import register_plan,generate_pilot,annotation_v2_template,pilot_receipt,reveal_pilot,validate_pilot
from iat.pilot_qualification import qualify_historical,ITEMS
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import load_dataset
from diagnostics.review_pilot import main
from test_journal_dataset_replay import manifest_fixture,CONFIG,P7
from test_chart_benchmark import fixture_annotation


def spec():
    return {'pilot_id':'synthetic-pilot','revision':1,'parent_plan_sha256':None,
        'sampling':{'method':'FIXED_UTC_GRID','start_utc':'2026-11-12T08:21:00Z','end_utc':'2026-11-12T08:23:00Z',
                    'step_minutes':2,'predeclared_without_iat_or_outcome_access':True},
        'regime_coverage_goals':{'TREND_UP':1,'TREND_DOWN':0,'RANGE':0,'TRANSITION':1,'UNCERTAIN':0},
        'reviewer_codes':['private-reviewer-a','private-reviewer-b']}


def annotations(bundle):
    result=[]
    for p in bundle['benchmark']['packets']:
        for i,r in enumerate(bundle['plan']['reviewer_codes']):
            a=fixture_annotation(p,r,'TREND_UP' if i==0 else 'TRANSITION')
            a.update(annotation_version=2,directional_bias='BULLISH' if i==0 else 'UNCERTAIN',confidence='HIGH' if i==0 else 'LOW',
                best_decision={'action':'TRADE' if i==0 else 'WAIT','reason':'PRIVATE_PERSONAL_PROSE must never enter anonymous export'},
                structure_events=[{'event':'HH_HL' if i==0 else 'CHOCH_DOWN','timeframe':'M1',
                    'candle_ids':[p['frames']['M1'][-1]['candle_id']],'description':'PRIVATE_PERSONAL_PROSE synthetic interpretation'}])
            if i==1 and p['timestamp_utc'].endswith('21:00+00:00'):a['regime']='UNCERTAIN'
            a['key_levels'][0]['kind']='DEMAND';result.append(a)
    return result


class ReviewPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name);cls.path,_=manifest_fixture(root)
        cls.plan,_=register_plan(cls.path,spec(),synthetic_only=True,config=CONFIG,intelligence_config=P7)
        cls.bundle=generate_pilot(cls.plan,cls.path,config=CONFIG,intelligence_config=P7)
        cls.annotations=annotations(cls.bundle);cls.receipts=[pilot_receipt(cls.bundle,a) for a in cls.annotations]
        cls.result=reveal_pilot(cls.bundle,cls.receipts,authorized=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)
    def tearDown(self):self.directory.cleanup()
    def test_missing_real_data_and_synthetic_substitution_stop_cleanly(self):
        self.assertEqual(qualify_historical()['status'],'DATA_NOT_QUALIFIED')
        with patch('iat.review_pilot.prepare_benchmark') as replay:
            plan,q=register_plan(self.path,spec());replay.assert_not_called()
        self.assertIsNone(plan);self.assertIn('REAL_HISTORICAL_DATA_REQUIRED',q['reason_codes'])
        self.assertIn('HUMAN_QUALIFICATION_REVIEW_REQUIRED',q['reason_codes'])
    def test_full_synthetic_workflow_classification_and_disagreement_metrics(self):
        e=self.result['export'];self.assertEqual(e['classification'],'SYNTHETIC_ONLY')
        self.assertEqual(e['independent_analyst_agreement'],'UNMEASURED');self.assertIsNone(e['real_review_metrics'])
        m=e['synthetic_workflow_metrics'];self.assertEqual(m['annotation_denominator'],4)
        self.assertEqual(m['packet_denominator'],2);self.assertEqual(m['reviewer_to_reviewer']['regime']['denominator'],2)
        self.assertEqual(m['reviewer_wait_count'],2);self.assertEqual(m['reviewer_uncertain_regime_count'],1)
        self.assertEqual(sum(m['iat_to_reviewer']['regime']['counts'].values()),4)
        self.assertTrue(e['representative_disagreements']);self.assertFalse(e['safety']['execution_allowed']);self.assertEqual(e['safety']['signal'],'WAIT')
    def test_anonymous_export_contains_no_reviewer_codes_or_private_prose(self):
        value=json.dumps(self.result['export'])
        for private in ('private-reviewer-a','private-reviewer-b','PRIVATE_PERSONAL_PROSE','reviewer_id','annotation_sha256'):
            self.assertNotIn(private,value)
        self.assertEqual({r['reviewer'] for r in self.result['export']['iat_to_reviewer']},{'R001','R002'})
        self.assertIn('PRIVATE_PERSONAL_PROSE',json.dumps(self.result['private_review']))
    def test_authorization_missing_receipt_duplicate_and_modified_receipt_reject(self):
        with self.assertRaises(ValueError):reveal_pilot(self.bundle,self.receipts)
        with self.assertRaises(ValueError):reveal_pilot(self.bundle,self.receipts[:-1],authorized=True)
        with self.assertRaises(ValueError):reveal_pilot(self.bundle,self.receipts+[self.receipts[0]],authorized=True)
        bad=deepcopy(self.receipts);bad[0]['annotation']['regime']='RANGE'
        with self.assertRaises(ValueError):reveal_pilot(self.bundle,bad,authorized=True)
    def test_no_annotation_or_malformed_v2_cannot_be_submitted(self):
        p=self.bundle['benchmark']['packets'][0]
        with self.assertRaises(ValueError):pilot_receipt(self.bundle,annotation_v2_template(p,'private-reviewer-a'))
        for field,value in (('annotation_version',1),('regime','UNKNOWN'),('directional_bias','INVALID'),('confidence',1)):
            bad=deepcopy(self.annotations[0]);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):pilot_receipt(self.bundle,bad)
        bad=deepcopy(self.annotations[0]);bad['structure_events'][0]['candle_ids']=['future-candle']
        with self.assertRaises(ValueError):pilot_receipt(self.bundle,bad)
    def test_plan_is_predeclared_without_assessments_and_immutable(self):
        with patch('iat.review_pilot.prepare_benchmark') as replay:
            plan,_=register_plan(self.path,spec(),synthetic_only=True,config=CONFIG,intelligence_config=P7);replay.assert_not_called()
        self.assertNotIn('assessment',json.dumps(plan));self.assertEqual(plan,self.plan)
        path=self.root/'plan.json';write_new(path,plan)
        with self.assertRaises(FileExistsError):write_new(path,plan)
        bad=deepcopy(self.plan);bad['timestamps'].pop()
        with self.assertRaises(ValueError):generate_pilot(bad,self.path,config=CONFIG,intelligence_config=P7)
        changed=spec();changed['revision']=2
        with self.assertRaises(ValueError):register_plan(self.path,changed,synthetic_only=True)
        changed['parent_plan_sha256']=self.plan['sha256']
        revision,_=register_plan(self.path,changed,synthetic_only=True)
        self.assertNotEqual(revision['sha256'],self.plan['sha256'])
    def test_fixed_grid_not_outcome_or_regime_selected(self):
        for mutation in (lambda s:s['sampling'].update(method='IAT_PREDICTION_SELECTED'),
            lambda s:s['sampling'].update(predeclared_without_iat_or_outcome_access=False),
            lambda s:s.update(reviewer_codes=['one']),lambda s:s['sampling'].update(end_utc='2026-11-12T08:24:00Z')):
            s=spec();mutation(s)
            with self.assertRaises(ValueError):register_plan(self.path,s,synthetic_only=True)
    def test_repeatability_and_future_append_prefix_equivalence(self):
        repeated=generate_pilot(self.plan,self.path,config=CONFIG,intelligence_config=P7)
        self.assertEqual(repeated,self.bundle)
        again=reveal_pilot(self.bundle,list(reversed(self.receipts)),authorized=True)
        self.assertEqual(again['export'],self.result['export'])
        path,_=manifest_fixture(self.root,prefix_end=25)
        p,_=register_plan(path,spec(),synthetic_only=True,config=CONFIG,intelligence_config=P7)
        prefix=generate_pilot(p,path,config=CONFIG,intelligence_config=P7)
        self.assertEqual(prefix['benchmark']['packets'],self.bundle['benchmark']['packets'])
        self.assertEqual(prefix['structure_observations'],self.bundle['structure_observations'])
        for packet in prefix['benchmark']['packets']:
            for event in prefix['structure_observations'][packet['packet_id']]:self.assertLessEqual(event['available_at'],packet['timestamp_utc'])
            if packet['timestamp_utc'].endswith('23:00+00:00'):
                self.assertEqual(packet['frames']['M1'][-1]['timestamp'],'2026-11-12T08:22:00+00:00')
                self.assertEqual(packet['frames']['M5'][-1]['timestamp'],'2026-11-12T08:15:00+00:00')
    def test_changed_dataset_or_configuration_requires_new_plan(self):
        path,_=manifest_fixture(self.root,prefix_end=25)
        with self.assertRaises(ValueError):generate_pilot(self.plan,path,config=CONFIG,intelligence_config=P7)
        with self.assertRaises(ValueError):generate_pilot(self.plan,self.path)
    def test_gap_rejection_no_synthetic_fallback(self):
        path,_=manifest_fixture(self.root,'coverage_gap')
        with self.assertRaises(ValueError):register_plan(path,spec(),synthetic_only=True)
        plan,q=register_plan(path,spec());self.assertIsNone(plan);self.assertEqual(q['status'],'DATA_NOT_QUALIFIED')
    def test_qualification_all_evidence_human_approval_hashes_and_calendar_required(self):
        from test_evaluation_window import v2_fixture
        path=v2_fixture(self.root,historical=True,calendar=True);m=load_dataset(path).metadata
        # All bytes remain SYNTHETIC MOCKS; this checks review mechanics only.
        document=self.root/'mock-evidence.txt';document.write_text('SYNTHETIC MOCK ONLY not provider evidence')
        evidence={k:{'status':'VERIFIED','file':document.name,'sha256':sha256(document.read_bytes()).hexdigest(),
            'reference':'SYNTHETIC MOCK REVIEW','scope':m['utc_range'],'explanation':'SYNTHETIC MOCK attestation'} for k in ITEMS}
        record=hashed({'qualification_version':1,'dataset_id':digest(m),'interval':m['utc_range'],
            'provider_entity':'SYNTHETIC MOCK','feed_id':m['lineage']['feed_id'],'instrument':'XAUUSD','price_basis':m['lineage']['price_basis'],
            'reviewer_code':'mock-qualifier','independent_review_attested':True,'reviewed_at_utc':'2026-11-14T00:00:00Z',
            'decision':'APPROVED','evidence':evidence})
        rp=self.root/'human-review.json';write_new(rp,record)
        q=qualify_historical(path,rp);self.assertEqual(q['status'],'DATA_NOT_QUALIFIED')
        self.assertIn('SYNTHETIC_CALENDAR_NOT_REAL_EVIDENCE',q['reason_codes'])
        document.write_text('ALTERED')
        self.assertIn('HUMAN_QUALIFICATION_REVIEW_INVALID',qualify_historical(path,rp)['reason_codes'])
    def test_cli_unqualified_has_no_packets_and_explicit_status_report(self):
        out=self.root/'status.json'
        with redirect_stdout(StringIO()):self.assertEqual(main(['qualify','--report-path',str(out)]),3)
        self.assertEqual(read_json(out)['status'],'DATA_NOT_QUALIFIED')
        sp=self.root/'spec.json';write_new(sp,spec());dest=self.root/'pilot'
        with redirect_stdout(StringIO()):self.assertEqual(main(['register','--manifest',str(self.path),'--spec',str(sp),'--pilot-directory',str(dest)]),3)
        self.assertFalse(dest.exists())

    def test_cli_synthetic_register_packets_submit_authorized_reveal(self):
        sp=self.root/'spec.json';write_new(sp,spec());dest=self.root/'synthetic batch'
        args=['--pilot-directory',str(dest)]
        with redirect_stdout(StringIO()):self.assertEqual(main(['register-synthetic','--manifest',str(self.path),'--spec',str(sp),*args]),0)
        self.assertTrue((dest/'private'/'plan.json').exists());self.assertFalse((dest/'reviewer-packets').exists())
        with redirect_stdout(StringIO()):self.assertEqual(main(['packets','--manifest',str(self.path),*args]),0)
        bundle=read_json(dest/'private'/'bundle.json')
        with redirect_stdout(StringIO()):self.assertEqual(main(['reveal',*args,'--authorize-reveal']),3)
        for i,a in enumerate(annotations(bundle)):
            file=self.root/(str(i)+'.json');write_new(file,a)
            with redirect_stdout(StringIO()):self.assertEqual(main(['submit',*args,'--annotation',str(file)]),0)
            with redirect_stdout(StringIO()):self.assertEqual(main(['submit',*args,'--annotation',str(file)]),3)
        with redirect_stdout(StringIO()):self.assertEqual(main(['reveal',*args]),3)
        self.assertFalse((dest/'anonymous-report.json').exists())
        with redirect_stdout(StringIO()):self.assertEqual(main(['reveal',*args,'--authorize-reveal']),0)
        e=read_json(dest/'anonymous-report.json');self.assertEqual(e['classification'],'SYNTHETIC_ONLY')
        self.assertNotIn('private-reviewer-a',json.dumps(e));self.assertTrue((dest/'private'/'revealed.json').exists())
        with redirect_stdout(StringIO()):self.assertEqual(main(['reveal',*args,'--authorize-reveal']),3)

    def test_review_approval_is_required_even_when_technical_preflight_is_ready(self):
        from dataclasses import replace
        from test_evaluation_window import v2_fixture
        path=v2_fixture(self.root,historical=True,calendar=True);ds=load_dataset(path)
        # MOCK ONLY: emulate a non-synthetic calendar interface to isolate manual-review gates.
        ds=replace(ds,calendar=replace(ds.calendar,provenance_kinds=('PUBLISHED',)))
        doc=self.root/'evidence.txt';doc.write_text('SYNTHETIC MOCK ONLY')
        evidence={k:{'status':'VERIFIED','file':doc.name,'sha256':sha256(doc.read_bytes()).hexdigest(),
            'reference':'SYNTHETIC MOCK','scope':ds.metadata['utc_range'],'explanation':'SYNTHETIC MOCK ONLY'} for k in ITEMS}
        review={'qualification_version':1,'dataset_id':digest(ds.metadata),'interval':ds.metadata['utc_range'],
            'provider_entity':'SYNTHETIC MOCK','feed_id':ds.metadata['lineage']['feed_id'],'instrument':'XAUUSD','price_basis':'BID',
            'reviewer_code':'mock-source-reviewer','independent_review_attested':True,'reviewed_at_utc':'2026-11-14T00:00:00Z','decision':'PENDING','evidence':evidence}
        rp=self.root/'approval.json'
        def write():rp.write_text(json.dumps(hashed(review)))
        with patch('iat.pilot_qualification.load_dataset',return_value=ds):
            write();self.assertIn('HUMAN_APPROVAL_NOT_GRANTED',qualify_historical(path,rp)['reason_codes'])
            review['decision']='APPROVED';write()
            self.assertEqual(qualify_historical(path,rp)['status'],'HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED')
            for item in ITEMS:
                review['evidence'][item]['status']='PENDING';write()
                self.assertIn('HUMAN_EVIDENCE_'+item.upper()+'_PENDING',qualify_historical(path,rp)['reason_codes'])
                review['evidence'][item]['status']='VERIFIED'
            review['dataset_id']='0'*64;write()
            self.assertIn('HUMAN_QUALIFICATION_REVIEW_INVALID',qualify_historical(path,rp)['reason_codes'])

    def test_warmup_must_cover_the_unchanged_configuration_lookbacks(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):register_plan(self.path,spec(),synthetic_only=True,config=replace(CONFIG,atr_period=100),intelligence_config=P7)

    def test_committed_synthetic_pilot_audit_matches_recomputed_results(self):
        path=Path('docs/research_audits/real-review-pilot-synthetic-v1')
        audit=read_json(path/'audit.json');export=read_json(path/'anonymous-report.json')
        self.assertEqual(export,json.loads(json.dumps(self.result['export'])))
        self.assertEqual(audit['plan_sha256'],self.plan['sha256'])
        self.assertFalse(audit['real_independent_human_reviews_performed'])
        for k in ('full_full_bundle_identical','full_full_export_identical','prefix_packets_identical','prefix_confirmed_events_identical'):self.assertTrue(audit[k])
        self.assertEqual(read_json(path/'packet.json'),self.bundle['benchmark']['packets'][-1])

    def test_registered_strategy_registry_cannot_change_silently(self):
        with patch('iat.review_pilot.registry',return_value={'sha256':'0'*64}):
            with self.assertRaises(ValueError):generate_pilot(self.plan,self.path,config=CONFIG,intelligence_config=P7)
        self.assertIn('strategy_registry',self.plan['configuration_hashes'])
        self.assertIn('compatibility',self.plan['configuration_hashes'])
        self.assertIn('ranking',self.plan['configuration_hashes'])
