"""Synthetic comparison regressions and published source-review claim boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from datetime import timedelta
from iat.historical_replay import run_dataset
from iat.replay_comparison import compare_reports
from iat.replay_dataset import load_dataset
from test_evaluation_window import v2_fixture
from test_context_components import CONFIG
from test_context_engine import P7
from test_intelligence_patterns import START


class InputIdentityComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            path=v2_fixture(Path(folder),count=30,evaluation_minutes=15)
            data=load_dataset(path)
            cls.full=run_dataset(data,config=CONFIG,intelligence_config=P7)
            prefix=copy.deepcopy(data)
            prefix.rows['M1'][:]=prefix.rows['M1'][:25]
            prefix.rows['M5'][:]=prefix.rows['M5'][:5]
            end=(START+timedelta(minutes=25)).isoformat()
            prefix.metadata['utc_range']['end']=end
            prefix.metadata['evaluation']['end']=end
            cls.prefix=run_dataset(prefix,config=CONFIG,intelligence_config=P7)

    def test_identical_eligible_inputs_compare_and_prefix_matches(self):
        result=compare_reports(self.full,self.full,self.prefix)
        self.assertEqual(result['repeatability']['status'],'PASS')
        self.assertEqual(result['prefix_equivalence']['status'],'PASS')
        self.assertEqual(result['prefix_equivalence']['compared_decisions'],25)
        self.assertFalse(result['execution_allowed'])

    def test_equal_logs_from_changed_source_do_not_prove_repeatability(self):
        changed=copy.deepcopy(self.full)
        changed['dataset']['source']['curation_id']='different-synthetic-source'
        result=compare_reports(self.full,changed,self.prefix)['repeatability']
        self.assertEqual(result['status'],'NOT_RUN')
        self.assertEqual(result['reason'],'INPUT_OR_CONFIGURATION_MISMATCH')
        self.assertIsNone(result['equal'])
        self.assertEqual(result['decision_log_hashes'][0],result['decision_log_hashes'][1])

    def test_changed_dataset_checksums_or_config_cannot_claim_repeatability(self):
        for defect in ('checksums','configuration','evidence'):
            changed=copy.deepcopy(self.full)
            if defect=='checksums':changed['dataset']['checksums']['M1']['file_sha256']='a'*64
            elif defect=='configuration':changed['configurations']['window']=999
            else:changed['dataset']['evidence_review']['finality']['reason_code']='DIFFERENT_REVIEW'
            with self.subTest(defect=defect):
                self.assertEqual(compare_reports(self.full,changed,self.prefix)['repeatability']['status'],'NOT_RUN')

    def test_prefix_must_share_source_lineage_and_warmup(self):
        for defect in ('source','lineage','warmup','start','evaluation'):
            changed=copy.deepcopy(self.prefix);d=changed['dataset']
            if defect=='source':d['source']['name']='OTHER SYNTHETIC PROVIDER'
            elif defect=='lineage':d['lineage']['feed_id']='OTHER SYNTHETIC FEED'
            elif defect=='warmup':d['warmup']['M5']['start']=(START+timedelta(minutes=5)).isoformat()
            elif defect=='start':d['utc_range']['start']=(START+timedelta(minutes=5)).isoformat()
            else:d['evaluation']['start']=(START+timedelta(minutes=20)).isoformat()
            with self.subTest(defect=defect):
                result=compare_reports(self.full,self.full,changed)['prefix_equivalence']
                self.assertEqual(result['status'],'NOT_RUN')
                self.assertEqual(result['reason'],'SOURCE_OR_WARMUP_MISMATCH')
                self.assertIsNone(result['differences'])

    def test_prefix_range_must_be_contained(self):
        for key in ('utc_range','evaluation'):
            changed=copy.deepcopy(self.prefix)
            changed['dataset'][key]['end']=(START+timedelta(minutes=35)).isoformat()
            with self.subTest(key=key):
                result=compare_reports(self.full,self.full,changed)['prefix_equivalence']
                self.assertEqual(result['status'],'NOT_RUN')
                self.assertEqual(result['reason'],'PREFIX_RANGE_NOT_CONTAINED')

    def test_different_analytical_window_prevents_prefix_comparison(self):
        changed=copy.deepcopy(self.prefix);changed['configurations']['window']=999
        self.assertEqual(compare_reports(self.full,self.full,changed)['prefix_equivalence']['reason'],
                         'ANALYTICAL_CONFIGURATION_MISMATCH')


class SourceQualificationReviewTests(unittest.TestCase):
    def setUp(self):
        self.review=json.loads(Path('docs/source_reviews/source-qualification-2026-11-14.json').read_text())

    def test_no_qualified_source_cannot_claim_run_or_measurements(self):
        r=self.review['result']
        self.assertEqual(r['qualified_sources'],0)
        self.assertEqual(r['historical_validation'],'PENDING')
        self.assertEqual(r['replay_execution'],'NOT_RUN')
        for k in ('coverage','valid_snapshots','blocked_snapshots','abstention_reasons','selected_hypotheses','stable_choch_counts'):
            self.assertIsNone(r[k])
        self.assertIsNone(r['repeatability']['decision_log_hashes'])
        self.assertIsNone(r['prefix_equivalence']['differences'])
        for key in ('repeatability','prefix_equivalence'):self.assertEqual(r[key]['status'],'NOT_RUN')
        for key in ('new_manifest_prepared','new_raw_data_acquired','raw_data_published'):self.assertFalse(r[key])
        self.assertEqual(self.review['safety'],{'exness':'BLOCKED','signal':'WAIT','execution_allowed':False,'broker_access':False})

    def test_candidates_have_resolvable_primary_references_and_exact_gaps(self):
        refs={r['id']:r for r in self.review['references']}
        self.assertEqual({c['id'] for c in self.review['candidates']},{'pilot','oanda','fxcm','dukascopy'})
        for c in self.review['candidates']:
            self.assertEqual(c['qualification'],'NOT_QUALIFIED')
            self.assertTrue(c['checks_performed']);self.assertTrue(c['missing_evidence'])
            self.assertFalse(c['sample_prepared'])
            for name in c['references']:
                self.assertIn(name,refs);self.assertTrue(refs[name]['url'].startswith('https://'))
        self.assertEqual(refs['pilot-card']['content_sha256'],'7ac3b98b7bd639f8f33f6a6858b36d7eb05683e6494d6da76235751e3409a132')
        self.assertEqual(refs['oanda-hours-ca']['http_status'],403)

    def test_published_defaults_and_prior_manifest_remain_pending(self):
        from iat.intelligence.context_models import ContextConfig
        from iat.intelligence.models import IntelligenceConfig
        self.assertEqual(self.review['analytical_defaults'],{'context_sha256':ContextConfig().digest,'intelligence_sha256':IntelligenceConfig().digest})
        prior=json.loads(Path('docs/source_reviews/xauusd-pilot.manifest.json').read_text())
        self.assertFalse(prior['finality_attested'])
        self.assertIsNone(prior['calendar'])
        self.assertEqual(prior['evidence_review']['calendar']['status'],'PENDING')
        self.assertEqual(prior['evidence_review']['finality']['status'],'PENDING')
