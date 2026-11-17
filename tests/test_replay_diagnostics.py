"""Labeled PR #28 synthetic replays only; no real source or analyst validation."""
import ast
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator, FormatChecker

from iat.replay_diagnostics import (generate_replay_diagnostics, validate_replay_diagnostics,
    diagnostics_text, attribute_reason_codes, _project)
from iat.scenario_replay import run_scenario_replay, _derive
from iat.replay_dataset import utc
from iat.intelligence.strategy_replay import digest
from diagnostics.replay_diagnostics import main
from test_scenario_replay import run, aligned_transition_fixture, rehash
from test_strategy_dataset_replay import scoped_fixture
from test_intelligence_patterns import START


@lru_cache(maxsize=1)
def examples():
    with tempfile.TemporaryDirectory() as d:
        path=scoped_fixture(Path(d),reversal=False)
        full=run(path)
        small=run(path,observation_times=[(START+timedelta(minutes=n)).isoformat() for n in (21,22,23)])
        return full,small


def synthetic_audit():
    cases={}
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        specs=[('continuation',False,False),('continuation_mirror',False,True),
            ('reversal',True,False),('reversal_mirror',True,True)]
        reports=[]
        for name,reversal,mirror in specs:
            reports.append((name,run(scoped_fixture(root,reversal=reversal,mirror=mirror))))
        for kind,mirror in [('invalidate',False),('invalidate',True),('replace',False),('support',False)]:
            reports.append(('aligned_'+kind+('_mirror' if mirror else ''),run(aligned_transition_fixture(root,kind,mirror))))
        path=scoped_fixture(root,reversal=False)
        times=[(START+timedelta(minutes=n)).isoformat() for n in (21,22,24,25)]
        for name,observations in [('missing_observation',times),('duplicate_observation',times[:1]*2),('reversed_observations',list(reversed(times)))]:
            reports.append((name,run(path,observation_times=observations)))
        totals={};snapshot_totals={};coverage={};reasons={};observations=0
        attribution={scope:{'denominator':0,'categories':{}} for scope in ('snapshot','transition')}
        for name,replay in reports:
            diagnostic=generate_replay_diagnostics(replay)
            # Golden audit is a projection of actual validated outputs; never override a classification.
            cases[name]={k:diagnostic[k] for k in ('input_replay_sha256','sha256','diagnostic_id','observation_count',
                'snapshot_status_counts','transition_counts','phase_counts','temporal')}
            cases[name]['key_coverage']={k:diagnostic['coverage'][k] for k in ('complete_required_chain','causal_frame_alignment','upstream_research_eligible','independently_qualified')}
            cases[name]['admission_attribution']=diagnostic['admission_attribution']
            for o in diagnostic['observations']:
                for scope in ('snapshot','transition'):
                    groups=o[scope+'_attribution']
                    if groups:attribution[scope]['denominator']+=1
                    for g in groups:
                        cats=attribution[scope]['categories'];cats[g['category']]=cats.get(g['category'],0)+1
            observations+=diagnostic['observation_count']
            for k,v in diagnostic['transition_counts'].items():totals[k]=totals.get(k,0)+v
            for k,v in diagnostic['snapshot_status_counts'].items():snapshot_totals[k]=snapshot_totals.get(k,0)+v
            for key,m in diagnostic['coverage'].items():
                agg=coverage.setdefault(key,{'numerator':0 if m['numerator'] is not None else None,'denominator':0,'percent':None,'status':m['status']})
                if m['numerator'] is not None:agg['numerator']+=m['numerator']
                agg['denominator']+=m['denominator']
            for scope,dist in diagnostic['reason_distributions'].items():
                group=reasons.setdefault(scope,{'denominator':0,'codes':{}});group['denominator']+=dist['denominator']
                for code,count in dist['codes'].items():group['codes'][code]=group['codes'].get(code,0)+count
        for m in coverage.values():
            if m['numerator'] is not None:
                m['percent']=100*m['numerator']/m['denominator'] if m['denominator'] else None
                m['status']='MEASURED' if m['denominator'] else 'NO_OBSERVATIONS'
        return dict(audit_version=1,provenance='LABELED_SYNTHETIC_ONLY',observation_count=observations,
            snapshot_status_counts=dict(sorted(snapshot_totals.items())),transition_counts=dict(sorted(totals.items())),
            coverage=coverage,reason_distributions=reasons,attribution_counts=attribution,
            unsupported_evidence_categories=diagnostic['unsupported_evidence_categories'],cases=cases,historical_validation='PENDING',
            historical_comparisons='NOT_RUN',signal='WAIT',execution_allowed=False,exness='BLOCKED')


class ReplayDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full,cls.small=examples();cls.diagnostic=generate_replay_diagnostics(cls.small)
        schema=json.loads(Path('config/replay-diagnostics-v1.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        cls.schema=Draft202012Validator(schema,format_checker=FormatChecker())
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def safe(self,d,r):
        self.assertTrue(validate_replay_diagnostics(d,r));self.schema.validate(d)
        self.assertEqual(d['signal'],'WAIT');self.assertEqual(d['mode'],'READ_ONLY_SHADOW');self.assertIs(d['execution_allowed'],False)
        self.assertEqual(d['exness'],'BLOCKED');self.assertEqual(d['historical_validation'],'PENDING');self.assertEqual(d['historical_comparisons'],'NOT_RUN')
        self.assertEqual(d['input_replay_sha256'],r['sha256']);self.assertEqual(d['source_qualification']['status'],r['qualification'])
    def test_full_replay_statuses_are_not_transition_statuses(self):
        d=generate_replay_diagnostics(self.full);self.safe(d,self.full)
        self.assertEqual(d['observation_count'],30)
        self.assertEqual(d['snapshot_status_counts'],{'ASSESSED':1,'ABSTAINED':27,'BLOCKED':2})
        self.assertEqual(d['transition_counts']['ABSTAINED'],26);self.assertEqual(d['transition_counts']['BLOCKED'],3)
        self.assertEqual(d['phase_counts'],{'WARMUP':20,'EVALUATION':10})
    def test_valid_reference_integrity_does_not_mean_sufficient_evidence(self):
        d=generate_replay_diagnostics(self.full);c=d['coverage']
        self.assertEqual(c['market_context']['numerator'],30);self.assertEqual(c['market_context']['percent'],100)
        self.assertEqual(c['complete_required_chain']['numerator'],28)
        self.assertEqual(c['missing_required_chain_observations']['numerator'],2)
        self.assertEqual(c['upstream_research_eligible']['numerator'],1)
        self.assertEqual(c['available_context_evidence']['numerator'],28)
        self.assertEqual(c['blocked_without_context_evidence']['numerator'],2)
        self.assertIsNone(c['independently_qualified']['numerator']);self.assertIsNone(c['independently_qualified']['percent'])
        self.assertEqual(c['independently_qualified']['status'],'NOT_ESTABLISHED')
    def test_empty_blocked_replay_is_not_successful_zero_coverage(self):
        r=run_scenario_replay();d=generate_replay_diagnostics(r);self.safe(d,r)
        self.assertEqual(d['observation_count'],0);self.assertEqual(d['upstream_run_status'],'BLOCKED')
        self.assertEqual(d['coverage']['market_context']['status'],'NO_OBSERVATIONS')
        self.assertIsNone(d['coverage']['market_context']['percent'])
        self.assertEqual(d['coverage']['independently_qualified']['status'],'NOT_ESTABLISHED')
        self.assertIn('DATASET_UNAVAILABLE',d['reason_distributions']['admission']['codes'])
    def test_empty_completed_schedule_is_explicitly_no_observations(self):
        with tempfile.TemporaryDirectory() as t:
            r=run(scoped_fixture(Path(t),reversal=False),observation_times=[])
        d=generate_replay_diagnostics(r);self.safe(d,r)
        self.assertEqual(d['observations'],[]);self.assertEqual(d['admission_attribution'][0]['category'],'UNATTRIBUTABLE')
    def test_unscoped_history_is_not_attributed_to_a_guessed_timeframe(self):
        d=generate_replay_diagnostics(self.full);first=d['observations'][0]
        categories={g['category']:g['upstream_codes'] for g in first['snapshot_attribution']}
        self.assertIn('HISTORY_UNSCOPED',categories)
        self.assertNotIn('M1_HISTORY',categories);self.assertNotIn('M5_HISTORY',categories)
    def test_explicit_frame_reasons_and_unknown_causes(self):
        self.assertEqual(attribute_reason_codes(['M1_HISTORY_UNAVAILABLE'])[0]['category'],'M1_HISTORY')
        self.assertEqual(attribute_reason_codes(['M5_HISTORY_UNAVAILABLE'])[0]['category'],'M5_HISTORY')
        self.assertEqual(attribute_reason_codes([])[0]['category'],'UNATTRIBUTABLE')
        self.assertEqual(attribute_reason_codes(['UNKNOWN_LEGACY_CAUSE'])[0]['category'],'UNATTRIBUTABLE')
    def test_empty_abstention_reasons_never_imply_sufficient_evidence(self):
        # Attribution-only unit input: upstream rejects such a modified source replay.
        modified=deepcopy(self.small);modified['records'][0]['snapshot_status']='ABSTAINED'
        modified['decision_log']['entries'][0]['abstention_reasons']=[]
        o=_project(modified)['observations'][0]
        self.assertEqual(o['sufficiency'],'NOT_ESTABLISHED')
        self.assertEqual(o['snapshot_attribution'][0]['category'],'UNATTRIBUTABLE')
        rehash(modified)
        with self.assertRaises(ValueError):generate_replay_diagnostics(modified)
    def test_reason_group_sorting_and_observation_frequencies(self):
        d=generate_replay_diagnostics(self.full)
        for dist in d['reason_distributions'].values():self.assertEqual(list(dist['codes']),sorted(dist['codes']))
        self.assertEqual(d['reason_distributions']['snapshot_abstained']['denominator'],27)
        self.assertEqual(d['reason_distributions']['snapshot_blocked']['denominator'],2)
        self.assertEqual(d['reason_distributions']['transition_blocked']['denominator'],3)
        self.assertEqual(d['reason_distributions']['snapshot_blocked']['codes']['HISTORY_INCOMPLETE'],2)
    def test_causal_alignment_is_not_directional_agreement(self):
        d=generate_replay_diagnostics(self.full)
        self.assertEqual(d['coverage']['causal_frame_alignment']['numerator'],28)
        for o in d['observations']:
            if o['causal_frame_alignment_confirmed']:
                self.assertLessEqual(utc(o['timeframe_context']['m5_as_of']),utc(o['timestamp_utc']))
    def test_partial_candle_boundaries_and_m5_changes(self):
        d=generate_replay_diagnostics(self.full)
        at22=d['observations'][21];self.assertEqual(at22['available_candles']['M5']['last_close_utc'],(START+timedelta(minutes=20)).isoformat())
        self.assertFalse(at22['temporal']['frame_close_changed']['M5'])
        self.assertTrue(d['observations'][24]['temporal']['frame_close_changed']['M5'])
    def test_zero_context_evidence_is_visible_without_claiming_missing_raw_bars(self):
        d=generate_replay_diagnostics(self.full)
        self.assertEqual(d['observations'][0]['evidence']['available_count'],0)
        self.assertEqual(d['observations'][0]['evidence']['confirmed_structure']['M5']['status'],'UNAVAILABLE')
        self.assertGreater(d['observations'][0]['available_candles']['M5']['closed_count'],0)
    def test_supported_category_absence_and_unsupported_proof_are_distinct(self):
        d=self.diagnostic
        self.assertIn('ZONE_INVALIDATION_PROOF',d['unsupported_evidence_categories'])
        for c in d['evidence_category_coverage'].values():self.assertIsNone(c['sufficient']['numerator'])
        self.assertEqual(d['evidence_category_coverage']['STRUCTURE']['available']['numerator'],3)
    def test_temporal_runs_changes_and_warmup_boundary(self):
        d=generate_replay_diagnostics(self.full)
        self.assertEqual(d['temporal']['contiguous_pairs']['numerator'],29)
        self.assertEqual(d['temporal']['warmup_to_evaluation_count'],1)
        self.assertTrue(d['observations'][20]['temporal']['warmup_to_evaluation'])
        for run_ in d['temporal']['snapshot_runs']:
            self.assertEqual((utc(run_['end_utc'])-utc(run_['start_utc'])).total_seconds(),60*(run_['observations']-1))
    def test_missing_observations_break_contiguous_runs(self):
        path=scoped_fixture(self.root,reversal=False)
        times=[(START+timedelta(minutes=n)).isoformat() for n in (21,22,24,25)]
        r=run(path,observation_times=times);d=generate_replay_diagnostics(r);self.safe(d,r)
        self.assertEqual(d['temporal']['contiguous_pairs']['numerator'],2)
        self.assertFalse(d['observations'][2]['temporal']['adjacent_m1_observation'])
        self.assertEqual(d['observations'][2]['temporal']['transition_run_length'],1)
    def test_prefix_and_future_append_observation_diagnostics_are_equal(self):
        d=generate_replay_diagnostics(self.full)
        r=run(scoped_fixture(self.root,reversal=False,prefix_end=25))
        prefix=generate_replay_diagnostics(r)
        self.assertEqual(d['observations'][:25],prefix['observations'])
        self.assertNotEqual(d['diagnostic_id'],prefix['diagnostic_id'])
        self.assertNotEqual(d['input_replay_sha256'],prefix['input_replay_sha256'])
    def test_repeatability_input_immutability_and_json_key_order(self):
        before=deepcopy(self.small);d=generate_replay_diagnostics(self.small)
        self.assertEqual(d,self.diagnostic);self.assertEqual(before,self.small)
        self.safe(json.loads(json.dumps(d)),dict(reversed(list(self.small.items()))))
        self.assertEqual(d,generate_replay_diagnostics(json.loads(json.dumps(self.small,sort_keys=True))))
    def test_unknown_reason_in_valid_conservative_block_is_unattributable(self):
        empty=run_scenario_replay();inputs=deepcopy(empty['inputs']);inputs['input_error']='UNMAPPED_LEGACY_FAILURE'
        r=_derive(inputs);d=generate_replay_diagnostics(r);self.safe(d,r)
        self.assertEqual(d['admission_attribution'][0]['category'],'UNATTRIBUTABLE')
    def test_external_qualification_blockers_stay_separate(self):
        from test_historical_replay import rewrite
        path=scoped_fixture(self.root,reversal=False)
        rewrite(path,lambda m:(m.update(dataset_kind='INDEPENDENT_HISTORICAL'),m['source'].update(reference='https://example.org/SYNTHETIC-MOCK-ONLY')))
        r=run(path,mode='EXTERNAL_UNQUALIFIED_RESEARCH');d=generate_replay_diagnostics(r);self.safe(d,r)
        self.assertEqual(d['observation_count'],0)
        self.assertIn('HUMAN_QUALIFICATION_REVIEW_REQUIRED',d['source_qualification']['existing_gate_reason_codes'])
        self.assertEqual(d['source_qualification']['status'],'DATA_NOT_QUALIFIED')
    def test_bad_source_checksum_rejected(self):
        r=deepcopy(self.small);r['sha256']='a'*64
        with self.assertRaises(ValueError):generate_replay_diagnostics(r)
    def test_bad_diagnostic_checksum_and_schema_version_rejected(self):
        for change in (lambda d:d.update(sha256='a'*64),lambda d:d.update(diagnostics_version=2),lambda d:d.update(diagnostics_version=True)):
            d=deepcopy(self.diagnostic);change(d)
            with self.assertRaises(ValueError):validate_replay_diagnostics(d,self.small)
    def test_source_binding_is_mandatory(self):
        with self.assertRaises(TypeError):validate_replay_diagnostics(self.diagnostic)
        with self.assertRaises(ValueError):validate_replay_diagnostics(self.diagnostic,self.full)
    def test_json_schema_requires_denominators_and_strict_fields(self):
        self.schema.validate(self.diagnostic)
        for change in (lambda d:d['coverage']['market_context'].pop('denominator'),lambda d:d.update(secret='not-allowed')):
            d=deepcopy(self.diagnostic);change(d)
            self.assertTrue(list(self.schema.iter_errors(d)))
    def test_invalid_reason_code_argument_rejected(self):
        for codes in (None,{},[3],['has spaces'],['bad;DROP']):
            with self.assertRaises(ValueError):attribute_reason_codes(codes)
    def test_export_contains_no_embedded_source_or_sensitive_metadata(self):
        r=deepcopy(self.small);source=json.dumps(r);d=generate_replay_diagnostics(r)
        output=json.dumps(d)
        for key in ('dataset_bundle','review_bundle','provider_entity','retrieved_at_utc','files','open','high','low','close'):
            self.assertNotIn('"'+key+'":',output)
        self.assertNotIn(r['inputs']['dataset_bundle']['files']['m1.csv'],output)
        self.assertEqual(json.dumps(r),source)
    def test_cli_private_exports_and_no_overwrite_or_source_modification(self):
        source=self.root/'private-replay.json';source.write_text(json.dumps(self.small));before=source.read_bytes()
        dest=self.root/'diagnostic.json';txt=self.root/'summary.txt';stdout=StringIO()
        args=['--replay-report',str(source),'--json-output',str(dest),'--text-output',str(txt)]
        with redirect_stdout(stdout):self.assertEqual(main(args),0)
        self.assertEqual(source.read_bytes(),before);self.assertEqual(json.loads(dest.read_text()),self.diagnostic)
        self.assertEqual(txt.read_text(encoding='utf-8'),diagnostics_text(self.diagnostic))
        self.assertNotIn(self.small['inputs']['dataset_bundle']['files']['m1.csv'],stdout.getvalue())
        original=dest.read_bytes()
        with redirect_stdout(StringIO()):self.assertEqual(main(args),1)
        self.assertEqual(dest.read_bytes(),original)
        with redirect_stdout(StringIO()):self.assertEqual(main(['--replay-report',str(source),'--json-output',str(source),'--text-output',str(txt)]),1)
    def test_cli_rejects_tampered_input_without_exports(self):
        source=self.root/'invalid.json';r=deepcopy(self.small);r['records'][0]['references']['market_context']='a'*64;rehash(r);source.write_text(json.dumps(r))
        dest=self.root/'d.json';txt=self.root/'s.txt'
        with redirect_stdout(StringIO()):self.assertEqual(main(['--replay-report',str(source),'--json-output',str(dest),'--text-output',str(txt)]),1)
        self.assertFalse(dest.exists());self.assertFalse(txt.exists())
    def test_no_new_analysis_network_broker_or_clock_imports(self):
        tree=ast.parse(Path('iat/replay_diagnostics.py').read_text())
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertFalse(any(any(bad in name for bad in ('engine','context_models','MetaTrader5','broker','requests','socket','random','time')) for name in imports))
    def test_golden_audit_matches_actual_diagnostics(self):
        expected=json.loads(Path('docs/research_audits/replay-diagnostics-synthetic-v1/audit.json').read_text())
        self.assertEqual(expected,synthetic_audit())
    def test_text_summary_has_explicit_unknowns_and_denominators(self):
        text=diagnostics_text(self.diagnostic)
        self.assertIn('independently_qualified: None/3 (unknown; NOT_ESTABLISHED)',text)
        self.assertIn('snapshot_abstained reasons (denominator',text)
        self.assertIn('historical validation PENDING',text)


    def test_missing_intervals_are_frame_scoped_only_when_preflight_retains_scope(self):
        from test_scenario_replay import modify_frame
        path=scoped_fixture(self.root,reversal=False)
        modify_frame(path,'M1',lambda rows:rows.pop(10))
        r=run(path);d=generate_replay_diagnostics(r);self.safe(d,r)
        self.assertEqual(d['observation_count'],0)
        self.assertIn('GAP_UNVERIFIED',d['dataset_coverage']['frame_quality']['M1']['upstream_codes'])
        self.assertEqual(d['dataset_coverage']['frame_quality']['M1']['attribution'][0]['category'],'DATA_GAP')
        self.assertTrue(d['dataset_coverage']['frame_quality']['M5']['valid'])
    def test_initial_export_failure_never_publishes_success(self):
        source=self.root/'private.json';source.write_text(json.dumps(self.small))
        dest=self.root/'new.json';txt=self.root/'summary.txt'
        target='iat.chart_benchmark.os.rename' if __import__('os').name=='nt' else 'iat.chart_benchmark.os.link'
        with patch(target,side_effect=OSError('SYNTHETIC FAILURE')),redirect_stdout(StringIO()):
            self.assertEqual(main(['--replay-report',str(source),'--json-output',str(dest),'--text-output',str(txt)]),1)
        self.assertFalse(dest.exists());self.assertFalse(txt.exists())


def source_tamper(name,change):
    def test(self):
        r=deepcopy(self.small);change(r)
        for row in r['records']:
            if name!='duplicate_identifier':row['record_id']=digest({k:v for k,v in row.items() if k not in ('record_id','sha256')})
            rehash(row)
        if r['decision_log'] is not None:r['decision_log_sha256']=digest(r['decision_log'])
        rehash(r)
        with self.assertRaises((ValueError,TypeError,KeyError)):generate_replay_diagnostics(r)
    setattr(ReplayDiagnosticsTests,'test_source_semantic_tamper_'+name,test)

for name,change in {
    'missing_reference':lambda r:r['records'][0]['references'].pop('market_context'),
    'wrong_reference':lambda r:r['records'][0]['references'].update(scenario_assessment='a'*64),
    'duplicate_identifier':lambda r:r['records'][1].update(record_id=r['records'][0]['record_id']),
    'duplicate_observation':lambda r:r['records'].insert(1,deepcopy(r['records'][0])),
    'contradictory_status':lambda r:r['records'][0].update(snapshot_status='ASSESSED'),
    'invalid_reason_shape':lambda r:r['records'][0].update(reason_codes={}),
    'unsupported_version':lambda r:r.update(audit_version=99),
    'reverse_order':lambda r:r['records'].reverse(),
    'missing_m1_evidence':lambda r:r['decision_log']['entries'][0]['timeframe_context'].update(m1_as_of=None),
    'missing_m5_evidence':lambda r:r['decision_log']['entries'][0]['timeframe_context'].update(m5_as_of=None),
    'partial_boundary':lambda r:r['records'][0]['available_candles']['M5'].update(last_close_utc=(START+timedelta(minutes=25)).isoformat()),
}.items():source_tamper(name,change)


def diagnostic_tamper(name,change):
    def test(self):
        d=deepcopy(self.diagnostic);change(d);rehash(d)
        with self.assertRaises((ValueError,TypeError,KeyError)):validate_replay_diagnostics(d,self.small)
    setattr(ReplayDiagnosticsTests,'test_diagnostic_semantic_tamper_'+name,test)

for name,change in {
    'counts':lambda d:d.update(observation_count=999),
    'coverage':lambda d:d['coverage']['independently_qualified'].update(numerator=3,percent=100,status='MEASURED'),
    'denominator':lambda d:d['coverage']['market_context'].update(denominator=1),
    'source_binding':lambda d:d.update(input_replay_sha256='a'*64),
    'status':lambda d:d['observations'][0].update(snapshot_status='ASSESSED'),
    'attribution':lambda d:d['observations'][0].update(snapshot_attribution=[]),
    'temporal':lambda d:d['observations'][0]['temporal'].update(snapshot_run_length=99),
    'qualify':lambda d:d['source_qualification'].update(status='DATA_QUALIFIED'),
    'execute':lambda d:d.update(execution_allowed=True),
    'signal':lambda d:d.update(signal='BUY'),
    'schema_field':lambda d:d.update(secret='not-allowed'),
}.items():diagnostic_tamper(name,change)
