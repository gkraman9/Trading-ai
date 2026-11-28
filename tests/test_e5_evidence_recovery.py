"""Research-only E5 evidence/age review; every replay price is invented."""
import json
from hashlib import sha256
from pathlib import Path
import unittest
from e5_analysis_age_study import study
from iat.intelligence.strategy_replay import digest
from iat.e5_protocol import protocol

ROOT = Path(__file__).resolve().parents[1]


class E5EvidenceRecovery(unittest.TestCase):
    def test_inventory_hashes_bind_exact_metadata_not_approval(self):
        r = json.loads((ROOT / 'docs/source_reviews/e5-evidence-recovery-v1.json').read_text())
        self.assertEqual(r['sha256'], digest({k:v for k,v in r.items() if k != 'sha256'}))
        for ref in r['metadata_references']:
            self.assertEqual(ref['file_sha256'], sha256((ROOT/ref['path']).read_bytes()).hexdigest())
            self.assertEqual(ref['verified_property'], 'EXACT_COMMITTED_BYTES_NOT_PROVIDER_AUTHENTICITY')
        self.assertEqual(r['independently_qualified_e5_candidates'], 0)
        self.assertEqual(r['qualification'], 'DATA_NOT_QUALIFIED')
        self.assertEqual(r['historical_comparisons'], 'NOT_RUN')
        self.assertFalse(r['execution_allowed'])


class E5AnalysisAgeResearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = study()

    def test_exact_limit_accepts_monitoring_with_no_stale_transition(self):
        self.assertEqual(self.result['at_30_seconds'], dict(open_count=1, states=['MONITORING'], stale_transition_count=0))

    def test_fresh_quote_one_millisecond_over_age_becomes_unresolved(self):
        changes=self.result['first_unresolved']
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['at_utc'], '2026-11-12T15:36:30.001000+00:00')
        self.assertEqual(changes[0]['reason_codes'], ['STRUCTURAL_ANALYSIS_STALE'])
        self.assertEqual(self.result['invented_quote_receipt_delay_ms'], 0)

    def test_new_closed_m1_does_not_recover_or_force_close_old_exposure(self):
        self.assertEqual(self.result['after_next_m1'], dict(unresolved=1, states=['UNRESOLVED'], closed_count=0))

    def test_frozen_protocol_and_safety_are_preserved(self):
        r=self.result
        self.assertEqual(r['protocol_sha256'], protocol()['sha256'])
        self.assertEqual(r['analysis_age_limit_ms'], 30000)
        self.assertEqual(r['qualification'], 'DATA_NOT_QUALIFIED')
        self.assertEqual(r['historical_performance'], 'UNMEASURED')
        self.assertEqual(r['historical_comparisons'], 'NOT_RUN')
        self.assertEqual((r['mode'],r['signal'],r['exness']), ('READ_ONLY_SHADOW','WAIT','BLOCKED'))
        self.assertIs(r['execution_allowed'], False)

    def test_study_repeats_and_matches_frozen_synthetic_report(self):
        r=self.result
        self.assertEqual(r['sha256'], digest({k:v for k,v in r.items() if k != 'sha256'}))
        self.assertEqual(r, study())
        self.assertEqual(r, json.loads((ROOT/'docs/research_audits/e5-analysis-age.synthetic.json').read_text()))
