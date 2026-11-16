"""Labeled SYNTHETIC integration; mocked source declarations are not authorization."""
import ast
import base64
from contextlib import redirect_stdout
from copy import deepcopy
import csv
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from diagnostics.scenario_replay import main
from iat.scenario_replay import run_scenario_replay, validate_scenario_replay
from iat.replay_dataset import load_dataset, utc
from iat.intelligence.engine import analyze_intelligence
from iat.intelligence.context import analyze_context, replay_context
from iat.intelligence.candles import prefix
from iat.intelligence.scenario_assessment import assess_scenarios
from iat.intelligence.scenario_transitions import assess_scenario_transition
from iat.intelligence.decision_log import DecisionLog, from_replay
from iat.intelligence.strategy_replay import digest
from test_strategy_dataset_replay import scoped_fixture, CONFIG, P7
from test_historical_replay import rewrite, recalc
from test_intelligence_patterns import START, rows
from test_intelligence_engine import WAVE


def rehash(r):
    r['sha256'] = digest({k:v for k,v in r.items() if k != 'sha256'})
    return r


def modify_frame(path, tf, change):
    source = path.parent / json.loads(path.read_text())['frames'][tf]['file']
    with source.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    change(rows)
    with source.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['timestamp','open','high','low','close'], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    recalc(path, tf)


def run(path, **kwargs):
    return run_scenario_replay(path, config=CONFIG, intelligence_config=P7, **kwargs)


def aligned_transition_fixture(root, kind='invalidate', mirror=False):
    """Synthetic OHLC, including separate M5 warm-up; overlap is exact internal aggregation.

    Outside bars form confirmed LH/LL, or EH/EL for the ranging variant. The
    support variant changes only available M1 candles; analytical rules are fixed.
    """
    path = scoped_fixture(root, reversal=False)
    a = rows(WAVE+[112.1+i*.1 for i in range(7)]+[112,112])
    b = rows(WAVE[:17], 'M5')
    for cs in (a,b):
        for c in cs:c.update(high=c['close']+5,low=c['close']-5)
    for i,c in enumerate(b):
        c['timestamp']=(START+timedelta(minutes=i*5-85)).isoformat()
        for key in ('open','high','low','close'):c[key]-=20
    for key in ('open','high','low','close'):b[-1][key]+=10
    for i in range(15,20):a[i]['high']=117
    low,high,finalhigh,finallow = (91,118,117.4,101) if kind=='replace' else (90,117.5,117.2,100)
    for i,h,l in [(20,high,low),(21,116,107.1),(22,116.5,103),(23,116,101),(24,117.4,104),
                  (25,117,107),(26,117.05,107.5),(27,117.1,107.7),(28,finalhigh,finallow)]:
        a[i].update(high=h,low=l)
    if kind=='support':
        a[26].update(open=111.7,high=112.85,low=111.65,close=112.8)
        a[27].update(open=112,high=112.9,low=111.95,close=112)
    for j in range(0,30,5):
        cs=a[j:j+5]
        b.append(dict(timestamp=cs[0]['timestamp'],open=cs[0]['open'],high=max(c['high'] for c in cs),
                      low=min(c['low'] for c in cs),close=cs[-1]['close']))
    if mirror:
        for cs in (a,b):
            for c in cs:
                o,h,l,cl=(c[k] for k in ('open','high','low','close'))
                c.update(open=200-o,high=200-l,low=200-h,close=200-cl)
    for tf,cs in [('M1',a),('M5',b)]:
        with (root/(tf.lower()+'.csv')).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['timestamp','open','high','low','close'],lineterminator='\n')
            w.writeheader();w.writerows(cs)
        recalc(path,tf)
    rewrite(path,lambda m:(m['source'].update(name='SYNTHETIC aligned OHLC only',curation_id='synthetic-aligned-'+kind+('-mirror' if mirror else '')),
                           m['lineage'].update(raw_sha256=digest({'synthetic_M1':a,'synthetic_M5':b}))))
    return path


def audit():
    cases = {}
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        for reversal in (False, True):
            for mirror in (False, True):
                path = scoped_fixture(root, reversal=reversal, mirror=mirror)
                r = run(path)
                name = ('reversal' if reversal else 'continuation') + ('_mirror' if mirror else '')
                cases[name] = {'status':r['status'], 'source_files':r['replay_manifest']['dataset']['checksums'],
                    'replay_sha256':r['sha256'], 'decision_log_sha256':r['decision_log_sha256'],
                    'summary':r['summary'], 'record_ids':[row['record_id'] for row in r['records']],
                    'transition_ids':[row['transition_id'] for row in r['records']]}
        for kind,mirror in [('invalidate',False),('invalidate',True),('replace',False),('support',False)]:
            path=aligned_transition_fixture(root,kind,mirror)
            r=run(path)
            cases['aligned_'+kind+('_mirror' if mirror else '')]={
                'status':r['status'],'source_files':r['replay_manifest']['dataset']['checksums'],
                'replay_sha256':r['sha256'],'decision_log_sha256':r['decision_log_sha256'],
                'summary':r['summary'],'record_ids':[row['record_id'] for row in r['records']],
                'transition_ids':[row['transition_id'] for row in r['records']],
                'invalidation_evidence':[row['invalidation_evidence'] for row in r['records'] if row['invalidation_evidence']]}
        path = scoped_fixture(root, reversal=False)
        times = [(START+timedelta(minutes=n)).isoformat() for n in (21,22,24,25)]
        for name, observations in [('missing_observation', times), ('duplicate_observation', times[:1]*2),
                                   ('reversed_observations', list(reversed(times)))]:
            r = run(path, observation_times=observations)
            cases[name] = {'status':r['status'], 'summary':r['summary'], 'reason_codes':r['reason_codes'], 'sha256':r['sha256']}
    counts = {}
    for case in cases.values():
        for state, count in case['summary']['all']['transition_counts'].items():
            counts[state] = counts.get(state, 0) + count
    return {'audit_version':1, 'provenance':'LABELED_SYNTHETIC_OHLC_ONLY', 'cases':cases,
            'observed_transition_counts':dict(sorted(counts.items())), 'historical_validation':'PENDING',
            'historical_comparisons':'NOT_RUN','exness':'BLOCKED','signal':'WAIT','execution_allowed':False}


class ScenarioReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.path = scoped_fixture(Path(cls.shared.name), reversal=False)
        cls.full = run(cls.path)
        cls.small = run(cls.path, observation_times=[(START+timedelta(minutes=n)).isoformat() for n in (21,22,23)])
    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def safe(self, r):
        self.assertTrue(validate_scenario_replay(r))
        self.assertEqual(r['mode'],'READ_ONLY_SHADOW'); self.assertEqual(r['signal'],'WAIT')
        self.assertIs(r['execution_allowed'],False); self.assertEqual(r['exness'],'BLOCKED')
        self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED'); self.assertEqual(r['historical_validation'],'PENDING')
        self.assertEqual(r['historical_comparisons'],'NOT_RUN'); self.assertFalse(r['safety']['broker_access'])
        self.assertEqual(r['safety']['orders_requested'],0); self.assertFalse(r['safety']['profitability_tested'])
    def test_full_chain_and_actual_warmup_evaluation_counts(self):
        r = self.full; self.safe(r); self.assertEqual(r['status'],'COMPLETED')
        self.assertEqual(r['summary']['all']['snapshots'],30)
        self.assertEqual(r['summary']['warmup']['snapshots'],20); self.assertEqual(r['summary']['evaluation']['snapshots'],10)
        self.assertEqual(r['summary']['all']['quality_blocked_snapshots'],2)
        self.assertEqual(r['summary']['all']['transition_counts'],{'ABSTAINED':26,'BLOCKED':3,'NEW':1})
    def test_no_upstream_intelligence_context_or_assessment_mutation(self):
        ds = load_dataset(self.path); at = START+timedelta(minutes=22)
        one, five = (prefix(ds.rows[tf],tf,at) for tf in ('M1','M5'))
        before = deepcopy([one,five]); opts = dict(provenance=ds.provenance,calendar=ds.calendar,observed_finality=ds.finality_attested)
        ir = analyze_intelligence('XAUUSD',one,five,at,config=P7,**opts)
        ctx = analyze_context('XAUUSD',one,five,at,config=CONFIG,intelligence_config=P7,**opts)
        s = assess_scenarios(ctx,as_of=at); row = self.full['records'][21]
        self.assertEqual(row['references']['market_intelligence'],digest(ir.to_dict()))
        self.assertEqual(row['references']['market_context'],digest(ctx.to_dict()))
        self.assertEqual(row['references']['scenario_assessment'],s['sha256'])
        self.assertEqual(row['selected_hypothesis'],ctx.confluence['selected_hypothesis'])
        self.assertEqual([one,five],before)
    def test_decision_log_v1_matches_existing_replay(self):
        ds = load_dataset(self.path)
        decisions = []
        from dataclasses import replace
        for entry in replay_context('XAUUSD',ds.rows['M1'],ds.rows['M5'],config=CONFIG,intelligence_config=P7,
                provenance=ds.provenance,calendar=ds.calendar,observed_finality=ds.finality_attested):
            phase = 'WARMUP' if utc(entry['report']['analysis_at'])<=utc(ds.metadata['evaluation']['start']) else 'EVALUATION'
            decisions.append(replace(from_replay(entry),phase=phase))
        log = DecisionLog(1,{'context':CONFIG.digest,'intelligence':P7.digest},tuple(decisions))
        self.assertEqual(self.full['decision_log'],json.loads(json.dumps(log.to_dict())))
        self.assertEqual(self.full['decision_log_sha256'],log.sha256)
    def test_repeatability_serialization_and_key_order(self):
        again = run(self.path); self.assertEqual(self.full,again)
        self.safe(json.loads(json.dumps(self.small)))
        self.safe(dict(reversed(list(self.small.items()))))
    def test_cutoff_prefix_equivalence(self):
        r = run(self.path,cutoff_utc=(START+timedelta(minutes=25)).isoformat())
        self.assertEqual(self.full['records'][:25],r['records'])
        self.assertEqual(self.full['decision_log']['entries'][:25],r['decision_log']['entries'])
    def test_truncated_files_and_future_append_preserve_earlier_records(self):
        path = scoped_fixture(self.root,reversal=False,prefix_end=25)
        r = run(path)
        self.assertEqual(self.full['records'][:25],r['records'])
        self.assertNotEqual(self.full['replay_manifest']['dataset']['manifest_sha256'],r['replay_manifest']['dataset']['manifest_sha256'])
        self.assertNotEqual(self.full['sha256'],r['sha256'])
    def test_closed_m5_alignment_boundary(self):
        for minute, expected in ((21,20),(24,20),(25,25),(29,25),(30,30)):
            row = self.full['records'][minute-1]
            self.assertEqual(utc(row['available_candles']['M5']['last_close_utc']),START+timedelta(minutes=expected))
            self.assertLessEqual(utc(row['available_candles']['M5']['last_close_utc']),utc(row['timestamp_utc']))
    def test_partial_m1_and_m5_never_reach_earlier_analysis(self):
        def checked(symbol, one, five, at, **kwargs):
            self.assertTrue(all(utc(c['timestamp'])+timedelta(minutes=1)<=at for c in one))
            self.assertTrue(all(utc(c['timestamp'])+timedelta(minutes=5)<=at for c in five))
            return analyze_intelligence(symbol,one,five,at,**kwargs)
        with patch('iat.scenario_replay.analyze_intelligence',side_effect=checked):
            r = run(self.path,cutoff_utc=(START+timedelta(minutes=22)).isoformat())
        self.assertEqual(r['records'],self.full['records'][:22])
    def test_missing_observation_abstains_and_does_not_fill(self):
        times = [(START+timedelta(minutes=n)).isoformat() for n in (21,22,24,25)]
        r = run(self.path,observation_times=times); self.safe(r)
        self.assertEqual(len(r['records']),4)
        self.assertEqual(r['records'][2]['transition_reason_codes'],['OBSERVATION_GAP'])
        self.assertEqual(r['records'][2]['transition_classification'],'ABSTAINED')
    def test_duplicate_and_reversed_observations_block_without_sorting(self):
        for times in ([21,21],[22,21]):
            r = run(self.path,observation_times=[(START+timedelta(minutes=n)).isoformat() for n in times])
            self.assertEqual(r['status'],'BLOCKED'); self.assertEqual(r['records'],[]); self.safe(r)
    def test_missing_manifest_and_invalid_inputs_fail_closed(self):
        for path in (None,self.root/'absent.json'):
            r = run(path); self.assertEqual(r['status'],'BLOCKED'); self.safe(r)
        for kwargs in ({'cutoff_utc':'invalid'},{'observation_times':['bad']},{'observation_times':{}},
                       {'cutoff_utc':(START+timedelta(minutes=22,seconds=30)).isoformat()}):
            r = run(self.path,**kwargs); self.assertEqual(r['status'],'BLOCKED'); self.safe(r)
    def test_source_files_unchanged_and_source_hashes_frozen(self):
        before = {p.name:sha256(p.read_bytes()).hexdigest() for p in self.path.parent.iterdir() if p.is_file()}
        r = run(self.path); self.safe(r)
        after = {p.name:sha256(p.read_bytes()).hexdigest() for p in self.path.parent.iterdir() if p.is_file()}
        self.assertEqual(before,after)
        for tf in ('M1','M5'):
            self.assertEqual(r['replay_manifest']['dataset']['checksums'][tf]['file_sha256'],before[tf.lower()+'.csv'])
    def test_admission_rejects_bad_candles_without_analytical_calls(self):
        changes = {
            'duplicate': lambda rows:rows.insert(5,dict(rows[4])),
            'reversed': lambda rows:rows.__setitem__(slice(4,6),list(reversed(rows[4:6]))),
            'missing':lambda rows:rows.pop(5),
            'ohlc':lambda rows:rows[5].update(high='0'),
            'misaligned':lambda rows:rows[5].update(timestamp=(utc(rows[5]['timestamp'])+timedelta(seconds=30)).isoformat()),
            'nonutc':lambda rows:rows[5].update(timestamp='2026-11-12T08:05:00'),
            'outside_range':lambda rows:rows[-1].update(timestamp='2026-11-12T09:00:00Z'),
        }
        for tf in ('M1','M5'):
            for name, change in changes.items():
                path=scoped_fixture(self.root,reversal=False); modify_frame(path,tf,change)
                with self.subTest(tf=tf,defect=name),patch('iat.scenario_replay.analyze_context') as analysis:
                    r=run(path); analysis.assert_not_called()
                    self.assertEqual(r['status'],'BLOCKED'); self.assertFalse(r['records']); self.safe(r)
    def test_cross_frame_mismatch_blocks(self):
        path=scoped_fixture(self.root,reversal=False)
        modify_frame(path,'M5',lambda rows:rows[-1].update(high='1000'))
        r=run(path); self.assertIn('M1_M5_OHLC_MISMATCH',r['reason_codes']); self.safe(r)
    def test_missing_finality_blocks(self):
        path=scoped_fixture(self.root,reversal=False); rewrite(path,lambda m:m.update(finality_attested=False))
        r=run(path); self.assertIn('CANDLE_FINALITY_UNCERTAIN',r['reason_codes']); self.safe(r)
    def test_unknown_lineage_is_not_inferred(self):
        for field in ('m5_origin','price_basis'):
            path=scoped_fixture(self.root,reversal=False); rewrite(path,lambda m:m['lineage'].update({field:'UNKNOWN'}))
            r=run(path); self.assertIn('SOURCE_METADATA_UNESTABLISHED',r['reason_codes']); self.safe(r)
    def test_synthetic_cannot_be_relabeled_external(self):
        r=run(self.path,mode='EXTERNAL_UNQUALIFIED_RESEARCH')
        self.assertEqual(r['reason_codes'],['REPLAY_SOURCE_MODE_MISMATCH']); self.safe(r)
    def test_unqualified_external_source_never_bypasses_existing_gate(self):
        path=scoped_fixture(self.root,reversal=False)
        rewrite(path,lambda m:(m.update(dataset_kind='INDEPENDENT_HISTORICAL'),m['source'].update(reference='https://example.org/SYNTHETIC-MOCK-ONLY')))
        with patch('iat.scenario_replay.analyze_context') as analysis:
            r=run(path,mode='EXTERNAL_UNQUALIFIED_RESEARCH'); analysis.assert_not_called()
        self.assertIn('EXTERNAL_RESEARCH_REQUIRES_EXISTING_QUALIFICATION_GATE',r['reason_codes'])
        self.assertIn('HUMAN_QUALIFICATION_REVIEW_REQUIRED',r['reason_codes'])
        self.assertEqual(r['qualification_review']['status'],'DATA_NOT_QUALIFIED'); self.safe(r)
    def test_no_source_approval_override_argument(self):
        with self.assertRaises(TypeError):run_scenario_replay(self.path,qualified=True)
        with self.assertRaises(ValueError):run_scenario_replay(self.path,mode='HISTORICAL_VALIDATED')
    def test_schema_and_file_checksum_errors_block(self):
        path=scoped_fixture(self.root,reversal=False)
        (self.root/'m1.csv').write_bytes((self.root/'m1.csv').read_bytes()+b'\n')
        r=run(path); self.assertEqual(r['status'],'BLOCKED'); self.safe(r)
        path=scoped_fixture(self.root,reversal=False); rewrite(path,lambda m:m.update(version=99))
        self.assertEqual(run(path)['status'],'BLOCKED')
    def test_wrong_or_missing_configuration_keys_rejected(self):
        r=deepcopy(self.small); r['inputs']['configuration']['context']['new_threshold']=1; rehash(r)
        with self.assertRaises(ValueError):validate_scenario_replay(r)
    def test_embedded_file_tampering_is_rejected(self):
        r=deepcopy(self.small); r['inputs']['dataset_bundle']['files']['m1.csv']=base64.b64encode(b'forged prices').decode(); rehash(r)
        with self.assertRaises(ValueError):validate_scenario_replay(r)
    def test_malformed_bundle_version_and_paths_rejected(self):
        for change in (lambda b:b.update(bundle_version=2),lambda b:b['files'].update({'../escape.csv':'YQ=='})):
            r=deepcopy(self.small); change(r['inputs']['dataset_bundle']); rehash(r)
            with self.assertRaises(ValueError):validate_scenario_replay(r)
    def test_unknown_report_fields_and_checksum_rejected(self):
        r=deepcopy(self.small); r['approved']=True; rehash(r)
        with self.assertRaises(ValueError):validate_scenario_replay(r)
        r=deepcopy(self.small); r['sha256']='a'*64
        with self.assertRaises(ValueError):validate_scenario_replay(r)
    def test_no_network_terminal_or_order_imports(self):
        for file in ('iat/scenario_replay.py','diagnostics/scenario_replay.py'):
            tree=ast.parse(Path(file).read_text())
            names=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
            names += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any(name and any(bad in name.lower() for bad in ('metatrader','broker','socket','requests')) for name in names))
    def test_cli_atomic_non_overwrite_and_missing_input(self):
        dest=self.root/'private.json'
        with redirect_stdout(StringIO()):result=main(['--manifest',str(self.path),'--report-path',str(dest)])
        self.assertEqual(result,0); before=dest.read_bytes(); self.safe(json.loads(before))
        with redirect_stdout(StringIO()):result=main(['--manifest',str(self.path),'--report-path',str(dest)])
        self.assertEqual(result,1); self.assertEqual(dest.read_bytes(),before)
        dest=self.root/'blocked.json'
        with redirect_stdout(StringIO()):result=main(['--report-path',str(dest)])
        self.assertEqual(result,3); self.safe(json.loads(dest.read_text()))
    def test_publication_failure_leaves_no_success_report(self):
        dest=self.root/'never-written.json'
        target='iat.chart_benchmark.os.rename' if __import__('os').name=='nt' else 'iat.chart_benchmark.os.link'
        with patch(target,side_effect=OSError('SYNTHETIC DISK FAILURE')),redirect_stdout(StringIO()):
            self.assertEqual(main(['--manifest',str(self.path),'--report-path',str(dest)]),1)
            self.assertFalse(dest.exists())
    def test_golden_synthetic_integration_audit(self):
        p=Path('docs/research_audits/scenario-replay-integration-synthetic-v1/audit.json')
        self.assertEqual(json.loads(p.read_text()),audit())


    def test_aligned_m5_invalidation_is_evidence_supported_in_both_directions(self):
        for mirror in (False,True):
            path=aligned_transition_fixture(self.root,'invalidate',mirror)
            r=run(path); self.safe(r)
            self.assertEqual(r['preflight']['preflight']['alignment']['mismatch_count'],0)
            last=r['records'][-1]; self.assertEqual(last['transition_classification'],'INVALIDATED')
            self.assertTrue(last['invalidation_evidence'])
            self.assertEqual(last['invalidation_evidence'][0]['available_at'],last['timestamp_utc'])
            self.assertTrue(all(x.startswith('M5:PIVOT:') for x in last['invalidation_evidence'][0]['source_references']))
    def test_aligned_replacement_does_not_forge_invalidation(self):
        r=run(aligned_transition_fixture(self.root,'replace')); self.safe(r)
        self.assertEqual(r['records'][-1]['transition_classification'],'REPLACED')
        self.assertEqual(r['records'][-1]['invalidation_evidence'],[])
    def test_aligned_strengthening_and_weakening_reuse_upstream_support(self):
        r=run(aligned_transition_fixture(self.root,'support')); self.safe(r)
        self.assertEqual(r['records'][26]['transition_classification'],'STRENGTHENING')
        self.assertEqual(r['records'][27]['transition_classification'],'WEAKENING')
    def test_real_review_bundle_rechecks_documents_and_still_rejects_synthetic_calendar(self):
        from test_evaluation_window import v2_fixture
        from iat.pilot_qualification import ITEMS
        from iat.chart_benchmark import hashed
        path=v2_fixture(self.root,historical=True,calendar=True)
        meta=load_dataset(path).metadata
        doc=self.root/'mock-evidence.txt';doc.write_bytes(b'SYNTHETIC MOCK ONLY, NOT PROVIDER EVIDENCE')
        review=hashed({'qualification_version':1,'dataset_id':digest(meta),'interval':meta['utc_range'],
            'provider_entity':'SYNTHETIC MOCK','feed_id':meta['lineage']['feed_id'],'instrument':'XAUUSD','price_basis':'BID',
            'reviewer_code':'mock-reviewer','independent_review_attested':True,'reviewed_at_utc':'2026-11-14T00:00:00Z',
            'decision':'APPROVED','evidence':{k:{'status':'VERIFIED','file':doc.name,'sha256':sha256(doc.read_bytes()).hexdigest(),
                'reference':'SYNTHETIC MOCK','scope':meta['utc_range'],'explanation':'SYNTHETIC MOCK ONLY'} for k in ITEMS}})
        rp=self.root/'review.json';rp.write_text(json.dumps(review))
        r=run(path,mode='EXTERNAL_UNQUALIFIED_RESEARCH',review_path=rp)
        self.assertEqual(r['status'],'BLOCKED'); self.assertIn('SYNTHETIC_CALENDAR_NOT_REAL_EVIDENCE',r['reason_codes']); self.safe(r)
        doc.write_bytes(b'CHANGED')
        r=run(path,mode='EXTERNAL_UNQUALIFIED_RESEARCH',review_path=rp)
        self.assertIn('HUMAN_QUALIFICATION_REVIEW_INVALID',r['reason_codes']); self.safe(r)
    def test_calendar_coverage_is_enforced_before_analysis(self):
        from test_evaluation_window import v2_fixture
        path=v2_fixture(self.root,count=30,evaluation_minutes=10,calendar=True)
        r=run(path,cutoff_utc=(START+timedelta(minutes=15)).isoformat()); self.safe(r)
        self.assertEqual(r['status'],'COMPLETED')
        cal=self.root/'sessions.json';data=json.loads(cal.read_text());data['coverage']['start']='2026-11-13'
        cal.write_text(json.dumps(data))
        rewrite(path,lambda m:m['calendar'].update(sha256=sha256(cal.read_bytes()).hexdigest()))
        r=run(path); self.assertEqual(r['status'],'BLOCKED'); self.safe(r)


    def test_committed_replay_manifest_is_file_bound_and_deterministic(self):
        r=run(aligned_transition_fixture(self.root,'invalidate'))
        example=Path('docs/research_audits/scenario-replay-integration-synthetic-v1/replay-manifest.json')
        self.assertEqual(json.loads(example.read_text()),r['replay_manifest'])
    def test_v1_manifest_cannot_supply_missing_lineage_by_inference(self):
        from test_historical_replay import write_fixture
        r=run(write_fixture(self.root))
        self.assertEqual(r['status'],'BLOCKED'); self.assertIn('MANIFEST_V2_REQUIRED',r['reason_codes']); self.safe(r)


def add_tampering(name,change):
    def test(self):
        r=deepcopy(self.small); change(r)
        for row in r['records']:
            row['record_id']=digest({k:v for k,v in row.items() if k not in ('record_id','sha256')})
            rehash(row)
        rehash(r)
        with self.assertRaises((ValueError,KeyError,TypeError)):validate_scenario_replay(r)
    setattr(ScenarioReplayTests,'test_rechecksummed_semantic_tamper_'+name,test)

for name,change in {
    'intelligence_ref':lambda r:r['records'][1]['references'].update(market_intelligence='a'*64),
    'context_ref':lambda r:r['records'][1]['references'].update(market_context='a'*64),
    'assessment_ref':lambda r:r['records'][1]['references'].update(scenario_assessment='a'*64),
    'transition_ref':lambda r:r['records'][1]['references'].update(scenario_transition='a'*64),
    'decision_ref':lambda r:r['records'][1]['references'].update(decision='a'*64),
    'evidence_refs':lambda r:r['records'][1].update(evidence_ids=['M1:FAKE:'+'a'*64]),
    'invalidation_without_proof':lambda r:r['records'][1].update(transition_classification='INVALIDATED',invalidation_evidence=[]),
    'unsupported_transition':lambda r:r['records'][1].update(transition_classification='TRADE'),
    'future_cutoff':lambda r:r['records'][1]['available_candles']['M5'].update(last_close_utc='2099-01-01T00:00:00Z'),
    'record_order':lambda r:r['records'].reverse(),
    'dataset_identity':lambda r:r['records'][1].update(dataset_id='a'*64),
    'source_metadata':lambda r:r['replay_manifest']['dataset']['lineage'].update(price_basis='ASK'),
    'source_promotion':lambda r:r.update(qualification='DATA_QUALIFIED'),
    'historical_promotion':lambda r:r.update(historical_validation='PASSED'),
    'execution':lambda r:r.update(execution_allowed=True),
    'signal':lambda r:r.update(signal='BUY'),
    'broker':lambda r:r['safety'].update(broker_access=True),
    'reason_codes':lambda r:r['records'][1].update(reason_codes=['APPROVED']),
    'summary_counts':lambda r:r['summary']['all'].update(snapshots=999),
    'log_rewrite':lambda r:r['decision_log']['entries'][0].update(selected_hypothesis='BUY'),
    'config_hash':lambda r:r['replay_manifest']['configuration_hashes'].update(context='a'*64),
    'policy':lambda r:r['replay_manifest']['policy'].update(version=2),
}.items():add_tampering(name,change)
