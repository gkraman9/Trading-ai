"""Synthetic workflow only. No actual independent reviewer annotations."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from pathlib import Path
import json,os,tempfile,unittest
from unittest.mock import patch
from iat.chart_benchmark import (prepare_benchmark,validate_bundle,packet_at,validate_packet,packet_html,
    annotation_template,validate_annotation,receipt_for,compare_benchmark,write_new,read_json,hashed,uncertainty_flags)
from iat.replay_dataset import load_dataset
from iat.intelligence.strategy_replay import digest
from diagnostics.chart_benchmark import main
from test_journal_dataset_replay import manifest_fixture,CONFIG,P7


STAMP='2026-11-12T08:23:00Z'


def fixture_annotation(packet,reviewer,regime='TREND_UP'):
    a=annotation_template(packet,reviewer);a.update(blinded_attestation=True,regime=regime)
    a['uncertainty']={'level':'HIGH','flags':['STRUCTURE_CONFLICT'],'explanation':'SYNTHETIC opposing structures require confirmation.'}
    a['supporting_evidence']=[{'category':'STRUCTURE','timeframe':'M1','direction':'BEARISH',
        'candle_ids':[packet['frames']['M1'][-1]['candle_id']],'description':'SYNTHETIC lower close suggests a structure change.'}]
    a['conflicting_evidence']=[{'category':'STRUCTURE','timeframe':'M5','direction':'BULLISH',
        'candle_ids':[packet['frames']['M5'][-1]['candle_id']],'description':'SYNTHETIC preceding M5 up-structure conflicts.'}]
    a['key_levels']=[{'kind':'SUPPORT','price':104.5,'timeframe':'M1','candle_ids':[packet['frames']['M1'][-2]['candle_id']],
                      'rationale':'SYNTHETIC previous lower boundary.'}]
    a['scenarios'][0]['plausibility']='LEADING';a['scenarios'][1]['plausibility']='LEADING'
    a['would_change_view']=['SYNTHETIC new confirmed M5 bearish structure.']
    return a


class ChartBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory();root=Path(cls.fixture.name)
        cls.path,_=manifest_fixture(root)
        cls.bundle=prepare_benchmark(cls.path,[STAMP],['analyst-a','analyst-b'],config=CONFIG,intelligence_config=P7)
    @classmethod
    def tearDownClass(cls):cls.fixture.cleanup()
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def receipts(self,bundle=None):
        bundle=bundle or self.bundle;p=bundle['packets'][0]
        return [receipt_for(bundle,fixture_annotation(p,'analyst-a','TREND_UP')),receipt_for(bundle,fixture_annotation(p,'analyst-b','TRANSITION'))]
    def test_closed_only_packet_excludes_unfinished_m5_and_iat_answers(self):
        p=self.bundle['packets'][0];validate_packet(p)
        self.assertEqual(p['frames']['M1'][-1]['timestamp'],'2026-11-12T08:22:00+00:00')
        self.assertEqual(p['frames']['M5'][-1]['timestamp'],'2026-11-12T08:15:00+00:00')
        encoded=json.dumps(p)+packet_html(p)
        for secret in ('adaptive_report','TREND_UP','TRANSITION','CHOCH','assessment_sha256','08:25:00','08:45:00','manifest_sha256'):
            self.assertNotIn(secret,encoded)
        self.assertIn('<svg',packet_html(p));self.assertNotIn('<script',packet_html(p))
    def test_future_append_and_prefix_do_not_change_packet_or_chart(self):
        path,_=manifest_fixture(self.root,prefix_end=25)
        prefix=prepare_benchmark(path,[STAMP],['analyst-a','analyst-b'],config=CONFIG,intelligence_config=P7)
        self.assertEqual(prefix['packets'],self.bundle['packets'])
        self.assertEqual(packet_html(prefix['packets'][0]),packet_html(self.bundle['packets'][0]))
        self.assertNotEqual(prefix['journal_dataset_result']['dataset']['manifest_sha256'],self.bundle['journal_dataset_result']['dataset']['manifest_sha256'])
    def test_full_run_repeatability(self):
        self.assertEqual(self.bundle,prepare_benchmark(self.path,[STAMP],['analyst-a','analyst-b'],config=CONFIG,intelligence_config=P7))
    def test_choch_is_hidden_until_annotations_saved_and_comparison_retains_disagreement(self):
        with self.assertRaises(ValueError):compare_benchmark(self.bundle,[])
        receipts=self.receipts()
        with self.assertRaises(ValueError):compare_benchmark(self.bundle,receipts[:1])
        r=compare_benchmark(self.bundle,receipts)
        original=r['reveal'][0]['frozen_original']['adaptive_report']
        self.assertEqual(original['regime']['directional'],'TRANSITION')
        self.assertTrue(any(e['details'].get('event_type')=='BEARISH_CHOCH' for e in original['interpretations']['evidence']))
        self.assertEqual(r['synthetic_workflow_metrics']['annotation_denominator'],2)
        self.assertEqual(r['synthetic_workflow_metrics']['regime_agreement_count'],1)
        self.assertEqual(r['reviewer_pairwise']['pair_denominator'],1)
        self.assertEqual(r['reviewer_pairwise']['regime_disagreement_count'],1)
        self.assertEqual(len(r['annotations']),2);self.assertTrue(r['representative_disagreements'])
        self.assertEqual(r['independent_analyst_agreement'],'UNMEASURED');self.assertIsNone(r['independent_analyst_metrics'])
        self.assertEqual(r['historical_comparisons'],'NOT_RUN')
        self.assertEqual(r['historical_validation'],'PENDING')
    def test_outcomes_remain_separate_and_original_hashes_unchanged(self):
        r=compare_benchmark(self.bundle,self.receipts())
        reveal=r['reveal'][0];original=reveal['frozen_original']
        self.assertEqual(original['adaptive_report']['sha256'],self.bundle['bindings'][self.bundle['packets'][0]['packet_id']]['assessment_sha256'])
        self.assertEqual({x['horizon_minutes'] for x in reveal['price_outcome_reviews_separate']},{5,15})
        self.assertNotIn('price_outcomes',r['synthetic_workflow_metrics'])
        self.assertEqual(r,compare_benchmark(self.bundle,list(reversed(self.receipts()))))
    def test_annotation_schema_strict_versions_refs_numbers_and_attestations(self):
        p=self.bundle['packets'][0];good=fixture_annotation(p,'analyst-a');validate_annotation(good,p)
        mutations=[lambda a:a.update(annotation_version=True),lambda a:a.update(extra='x'),lambda a:a.update(blinded_attestation=False),
            lambda a:a.update(packet_sha256='wrong'),lambda a:a['key_levels'][0].update(price=float('nan')),
            lambda a:a['supporting_evidence'][0].update(candle_ids=['future-candle']),
            lambda a:a['supporting_evidence'][0].update(timeframe='H1'),lambda a:a['uncertainty'].update(flags=['INVENTED']),
            lambda a:a.update(annotation_kind='INDEPENDENT_ANALYST',independence_attestation=True),
            lambda a:a.update(would_change_view=[]),lambda a:a['scenarios'].pop()]
        for mutation in mutations:
            a=deepcopy(good);mutation(a)
            with self.subTest(annotation=a),self.assertRaises(ValueError):validate_annotation(a,p)
    def test_template_is_not_a_recorded_annotation(self):
        p=self.bundle['packets'][0]
        with self.assertRaises(ValueError):receipt_for(self.bundle,annotation_template(p,'analyst-a'))
        a=fixture_annotation(p,'unlisted')
        with self.assertRaises(ValueError):receipt_for(self.bundle,a)
    def test_duplicate_and_tampered_receipts_reject(self):
        receipts=self.receipts()
        with self.assertRaises(ValueError):compare_benchmark(self.bundle,receipts+[receipts[0]])
        receipts[0]['annotation']['regime']='RANGE'
        with self.assertRaises(ValueError):compare_benchmark(self.bundle,receipts)
    def test_gap_or_source_label_cannot_bypass_preflight(self):
        path,_=manifest_fixture(self.root,'coverage_gap')
        with self.assertRaises(ValueError):prepare_benchmark(path,[STAMP],['analyst-a'])
        with self.assertRaises(TypeError):prepare_benchmark(path,[STAMP],['analyst-a'],provenance='HISTORICAL_RESEARCH')
    def test_invalid_selection_roster_and_blocked_timestamp(self):
        for stamps,names in (([],['a']),([STAMP,STAMP],['a']),([STAMP],['a','a']),([STAMP],['../escape']),
            (['2026-11-12T08:23:30Z'],['a']),(['2026-11-12T09:00:00Z'],['a']),(['2026-11-12T08:10:00Z'],['a'])):
            with self.subTest(stamps=stamps,names=names),self.assertRaises(ValueError):prepare_benchmark(self.path,stamps,names,config=CONFIG,intelligence_config=P7)
    def test_packet_and_bundle_tampering_reject(self):
        p=deepcopy(self.bundle['packets'][0]);p['frames']['M5'][-1]['timestamp']='2026-11-12T08:20:00+00:00'
        p=hashed({k:v for k,v in p.items() if k!='sha256'})
        with self.assertRaises(ValueError):validate_packet(p)
        b=deepcopy(self.bundle);b['reviewer_ids'].append('third')
        with self.assertRaises(ValueError):validate_bundle(b)
    def test_uncertainty_levels_not_invented_and_evidence_denominators_explicit(self):
        r=compare_benchmark(self.bundle,self.receipts());metrics=r['synthetic_workflow_metrics']
        for row in r['comparisons']:
            self.assertEqual(row['uncertainty']['level_comparison'],'NOT_COMPARABLE_NO_IAT_CONFIDENCE_SCALE')
        for role in ('supporting_evidence','conflicting_evidence'):
            self.assertEqual(metrics['evidence'][role]['comparison_denominator'],2)
            self.assertLessEqual(metrics['evidence'][role]['shared_token_count'],metrics['evidence'][role]['union_token_denominator'])
        self.assertEqual(metrics['uncertainty_flag_denominators']['STRUCTURE_CONFLICT']['presence_agreement_count'],2)
    def test_atomic_new_files_never_overwrite_or_leave_success_on_failure(self):
        path=self.root/'result.json';write_new(path,{'status':'SYNTHETIC'})
        with self.assertRaises(FileExistsError):write_new(path,{'status':'CHANGED'})
        self.assertEqual(read_json(path),{'status':'SYNTHETIC'})
        with patch('iat.chart_benchmark.os.rename' if os.name=='nt' else 'iat.chart_benchmark.os.link',side_effect=OSError('SYNTHETIC')):
            with self.assertRaises(OSError):write_new(self.root/'failed.json',{'status':'SUCCESS'})
        self.assertFalse((self.root/'failed.json').exists())
    def test_cli_record_reveal_missing_roster_and_no_overwrite(self):
        bundle_path=self.root/'bundle.json';write_new(bundle_path,self.bundle);receipts=self.root/'receipts';receipts.mkdir();report=self.root/'result.json'
        args=['--private-bundle',str(bundle_path),'--receipts-directory',str(receipts)]
        with redirect_stdout(StringIO()):self.assertEqual(main(['reveal',*args,'--report-path',str(report)]),3)
        self.assertFalse(report.exists())
        for reviewer in self.bundle['reviewer_ids']:
            annotation=self.root/(reviewer+'.json');write_new(annotation,fixture_annotation(self.bundle['packets'][0],reviewer))
            with redirect_stdout(StringIO()):self.assertEqual(main(['record',*args,'--annotation',str(annotation)]),0)
            with redirect_stdout(StringIO()):self.assertEqual(main(['record',*args,'--annotation',str(annotation)]),3)
        with redirect_stdout(StringIO()):self.assertEqual(main(['reveal',*args,'--report-path',str(report)]),0)
        self.assertEqual(read_json(report)['independent_analyst_agreement'],'UNMEASURED')
        with redirect_stdout(StringIO()):self.assertEqual(main(['reveal',*args,'--report-path',str(report)]),3)

    def test_cli_prepare_separates_review_files_and_requires_fresh_output(self):
        output=self.root/'review batch'
        args=['prepare','--manifest',str(self.path),'--at',STAMP,'--reviewer','analyst-a','--output-directory',str(output)]
        with redirect_stdout(StringIO()):self.assertEqual(main(args),0)
        self.assertEqual(read_json(output/'COMPLETE.json')['independent_analyst_agreement'],'UNMEASURED')
        public=output/'reviewer-packets';private=output/'private'
        self.assertTrue((private/'bundle.json').exists())
        for file in public.iterdir():
            content=file.read_text()
            self.assertNotIn('adaptive_report',content)
            self.assertNotIn('assessment_sha256',content)
        with redirect_stdout(StringIO()):self.assertEqual(main(args),3)

    def test_historical_provenance_label_still_requires_all_existing_evidence(self):
        from test_historical_replay import rewrite
        path,_=manifest_fixture(self.root)
        rewrite(path,lambda m:(m.update(dataset_kind='INDEPENDENT_HISTORICAL',finality_attested=False),m['source'].update(reference='https://example.org/SYNTHETIC-MOCK')))
        with self.assertRaises(ValueError):prepare_benchmark(path,[STAMP],['analyst-a'])

    def test_public_contract_rejects_interpretations_smuggled_into_text(self):
        p=deepcopy(self.bundle['packets'][0]);p['instructions']='IAT says TREND_UP'
        p['packet_id']=digest({k:v for k,v in p.items() if k not in ('packet_id','sha256')})
        p=hashed({k:v for k,v in p.items() if k!='sha256'})
        with self.assertRaises(ValueError):validate_packet(p)

    def test_committed_worked_packet_and_audit_match_actual_replay(self):
        root=Path('docs/research_audits/chart-review-synthetic-v1');audit=read_json(root/'audit.json')
        self.assertEqual(read_json(root/'packet.json'),self.bundle['packets'][0])
        self.assertEqual((root/'packet.html').read_text(),packet_html(self.bundle['packets'][0]))
        receipts=[receipt_for(self.bundle,read_json(root/(r+'.annotation.json'))) for r in self.bundle['reviewer_ids']]
        result=compare_benchmark(self.bundle,receipts)
        self.assertEqual(result['synthetic_workflow_metrics'],audit['synthetic_workflow_metrics'])
        self.assertEqual(digest(result['comparisons']),digest(audit['comparisons']))
        self.assertEqual(result['independent_analyst_agreement'],'UNMEASURED')
        self.assertEqual(audit['packet_sha256'],self.bundle['packets'][0]['sha256'])
        self.assertTrue(audit['full_full_identical']);self.assertTrue(audit['prefix_packet_identical'])
