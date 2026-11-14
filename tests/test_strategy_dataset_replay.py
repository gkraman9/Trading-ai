"""End-to-end SYNTHETIC manifests; historical declarations in tests are mocks."""
from contextlib import redirect_stdout
from copy import deepcopy
import csv,json,tempfile,unittest
from dataclasses import replace
from datetime import datetime,timedelta
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from iat.strategy_dataset_replay import run_strategy_manifest,validate_strategy_dataset_report,window_accounting
from iat.replay_dataset import load_dataset
from iat.historical_replay import dataset_preflight,run_dataset
from iat.intelligence.strategy_replay import replay_strategies,digest
from diagnostics.strategy_dataset_replay import main
from test_strategy_replay import replay_fixture
from test_context_components import CONFIG
from test_context_engine import P7
from test_evaluation_window import v2_fixture
from test_historical_replay import rewrite,recalc


def scoped_fixture(root,*,reversal=True,mirror=False,prefix_end=None,total_minutes=30):
    """M5 warm-up derives from omitted synthetic parents; overlap derives from M1."""
    a,b,_=replay_fixture(reversal,False)
    if reversal:a[9]['high']=100.165  # Prior resistance supplies the existing zone observation.
    while len(a)<total_minutes:
        last=a[-1];at=datetime.fromisoformat(last['timestamp'])+timedelta(minutes=1);v=last['close']
        a.append(dict(timestamp=at.isoformat(),open=v,high=v+.005,low=v-.005,close=v))
    b=[r for r in b if datetime.fromisoformat(r['timestamp'])<datetime.fromisoformat(a[0]['timestamp'])]
    if not reversal:
        # Synthetic earlier M5 pivots sit below the later M1 expansion, preserving
        # an established M5 trend without changing strategy or quality thresholds.
        for c in b:
            for key in ('open','high','low','close'):c[key]-=.2
    omitted=[]
    for c in b:
        omitted.extend(dict(c,timestamp=(datetime.fromisoformat(c['timestamp'])+timedelta(minutes=i)).isoformat()) for i in range(5))
    for j in range(0,len(a)-4,5):
        cs=a[j:j+5]
        b.append(dict(timestamp=cs[0]['timestamp'],open=cs[0]['open'],high=max(c['high'] for c in cs),
                      low=min(c['low'] for c in cs),close=cs[-1]['close']))
    if mirror:
        for cs in (a,b,omitted):
            for c in cs:
                o,h,l,cl=(c[k] for k in ('open','high','low','close'));c.update(open=200-o,high=200-l,low=200-h,close=200-cl)
    raw_sha=digest(omitted+a)
    start=datetime.fromisoformat(a[0]['timestamp'])
    boundary=start+timedelta(minutes=25 if reversal else 20)
    end=start+timedelta(minutes=prefix_end or total_minutes)
    a=[r for r in a if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=1)<=end]
    b=[r for r in b if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=5)<=end]
    frames={}
    for tf,rows in (('M1',a),('M5',b)):
        p=root/(tf.lower()+'.csv')
        with p.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['timestamp','open','high','low','close'],lineterminator='\n');w.writeheader();w.writerows(rows)
        frames[tf]={'file':p.name,'sha256':sha256(p.read_bytes()).hexdigest()}
    manifest={'version':2,'symbol':'XAUUSD','dataset_kind':'SYNTHETIC_FIXTURE',
              'source':{'name':'SYNTHETIC scoped fixture','reference':'synthetic:strategy-dataset-unit',
                        'curation_id':'synthetic-scoped','retrieved_at_utc':'2026-11-14T00:00:00Z','independent_review':'PENDING'},
              'utc_range':{'start':b[0]['timestamp'],'end':end.isoformat()},'frames':frames,'calendar':None,'finality_attested':True,
              'evaluation':{'start':boundary.isoformat(),'end':end.isoformat()},
              'warmup':{tf:{'start':rows[0]['timestamp'],'end':boundary.isoformat()} for tf,rows in (('M1',a),('M5',b))},
              'lineage':{'feed_id':'SYNTHETIC_ONLY','price_basis':'BID','timestamp_convention':'INTERVAL_OPEN_UTC',
                         'm5_origin':'AGGREGATED_FROM_M1','raw_sha256':raw_sha},
              'evidence_review':{k:{'status':'PENDING','reference':'synthetic:mock-evidence','reason_code':'SYNTHETIC_ONLY'}
                                 for k in ('usage','instrument','timestamp','price_basis','calendar','finality')}}
    path=root/'manifest.json';path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n');return path


def group(phase,strategy,direction):
    return next(g for g in phase['groups'] if g['strategy_id']==strategy and g['direction']==direction)


class DatasetStrategyTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def run_manifest(self,path):return run_strategy_manifest(path,config=CONFIG,intelligence_config=P7)
    def test_sweep_carries_active_warmup_setup_and_expires_once_in_evaluation_both_directions(self):
        for mirror in (False,True):
            path=scoped_fixture(self.root,mirror=mirror);r=self.run_manifest(path);validate_strategy_dataset_report(r)
            direction='BULLISH' if mirror else 'BEARISH';strategy='SWEEP_M1_STRUCTURE_CHANGE';account=r['window_accounting']
            warm=group(account['warmup'],strategy,direction);ev=group(account['evaluation_window'],strategy,direction)
            self.assertEqual(account['warmup']['timestamps'],25);self.assertEqual(account['evaluation_window']['timestamps'],5)
            self.assertEqual(warm['snapshot_outcomes']['QUALIFIES'],2);self.assertEqual(warm['setup_counts']['first_qualified'],1)
            self.assertEqual(ev['setup_counts']['carried_in_active'],1);self.assertEqual(ev['setup_counts']['first_qualified'],0)
            self.assertEqual(ev['setup_counts']['expired_qualified'],1);self.assertEqual(ev['setup_counts']['active_at_end'],0)
            self.assertEqual(ev['setup_ids']['carried_in_active'],ev['setup_ids']['expired_qualified'])
            self.assertEqual(r['historical_validation'],'PENDING');self.assertIsNone(r['historical_metrics'])
    def test_continuation_evaluation_first_qualification_and_invalidation_count_once(self):
        for mirror in (False,True):
            path=scoped_fixture(self.root,reversal=False,mirror=mirror);r=self.run_manifest(path)
            ev=group(r['window_accounting']['evaluation_window'],'M5_TREND_M1_CONFIRMATION','BEARISH' if mirror else 'BULLISH')
            self.assertEqual(ev['setup_counts']['first_qualified'],1)
            self.assertEqual(ev['setup_counts']['invalidated_qualified'],1)
            self.assertEqual(ev['snapshot_outcomes']['QUALIFIES'],2)
    def test_all_checks_use_shared_preflight_and_log_v1_is_unchanged(self):
        path=scoped_fixture(self.root);ds=load_dataset(path);r=self.run_manifest(path)
        shared=dataset_preflight(ds,intelligence_config=P7)
        self.assertEqual(r['preflight'],shared['preflight'])
        self.assertEqual(r['preflight'],run_dataset(ds,config=CONFIG,intelligence_config=P7)['preflight'])
        old=replay_strategies('XAUUSD',ds.rows['M1'],ds.rows['M5'],config=CONFIG,intelligence_config=P7,
                              provenance=ds.provenance,calendar=ds.calendar,observed_finality=ds.finality_attested)
        self.assertEqual(r['strategy_replay_log'],old)
        self.assertEqual(old['log_version'],1)
        coverage=r['preflight']['alignment']['evaluation']
        self.assertEqual(coverage['consistency_evidence'],'INTERNAL_AGGREGATION_ONLY')
        self.assertEqual(coverage['cross_frame_claim'],'NOT_ESTABLISHED')
        self.assertEqual(coverage['comparable_m5_bars'],1)
        self.assertEqual(coverage['warmup_uncovered_m5_bars'],17)
    def test_checksum_and_consistency_rejection_never_calls_strategy_engine(self):
        for defect in ('checksum','consistency','ohlc','unclosed','gap'):
            path=scoped_fixture(self.root)
            p=self.root/'m1.csv'
            if defect=='checksum':p.write_bytes(p.read_bytes()+b'\n')
            else:
                with p.open(newline='') as f:rows=list(csv.DictReader(f))
                if defect=='unclosed':rows.append(dict(rows[-1],timestamp=json.loads(path.read_text())['utc_range']['end']))
                elif defect=='gap':rows.pop(10)
                elif defect=='ohlc':rows[10]['high']='0'
                else:rows[10]['high']=str(float(rows[10]['high'])+1)
                with p.open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=['timestamp','open','high','low','close']);w.writeheader();w.writerows(rows)
                recalc(path,'M1')
            with self.subTest(defect=defect),patch('iat.strategy_dataset_replay.replay_strategies') as engine:
                r=self.run_manifest(path);engine.assert_not_called()
                self.assertIn(r['status'],('BLOCKED','FAIL'));self.assertIsNone(r['strategy_replay_log'])
                self.assertIsNone(r['window_accounting']);self.assertIsNone(r['historical_metrics'])
                self.assertEqual(r['historical_comparisons'],'NOT_RUN')
                if defect=='unclosed':self.assertIn('BAR_OUTSIDE_DATASET_RANGE',r['reason_codes'])
    def test_historical_label_without_evidence_is_blocked(self):
        path=scoped_fixture(self.root)
        rewrite(path,lambda m:(m.update(dataset_kind='INDEPENDENT_HISTORICAL',finality_attested=False),
                              m['source'].update(reference='https://example.org/SYNTHETIC-MOCK-NOT-REAL')))
        with patch('iat.strategy_dataset_replay.replay_strategies') as engine:
            r=self.run_manifest(path);engine.assert_not_called()
        self.assertIn('INDEPENDENT_REVIEW_PENDING',r['reason_codes'])
        self.assertIn('SESSION_CALENDAR_REQUIRED',r['reason_codes']);self.assertIn('EVIDENCE_FINALITY_PENDING',r['reason_codes'])
        self.assertIsNone(r['historical_metrics']);self.assertIsNone(r['strategy_replay_log'])
        with self.assertRaises(TypeError):run_strategy_manifest(path,provenance='HISTORICAL_RESEARCH')
    def test_mock_reviewed_history_branch_needs_sufficient_coverage(self):
        # Test-only mock declarations/calendar; not a permitted real historical export.
        for count,minutes in ((15,5),(120,60)):
            path=v2_fixture(self.root,count=count,evaluation_minutes=minutes,historical=True,calendar=True)
            r=self.run_manifest(path);validate_strategy_dataset_report(r)
            if minutes==5:
                self.assertEqual(r['reason_codes'],['EVALUATION_COVERAGE_INSUFFICIENT'])
                self.assertIsNone(r['strategy_replay_log']);self.assertIsNone(r['historical_metrics'])
            else:
                self.assertEqual(r['historical_validation'],'DATASET_PIPELINE_CHECKS_PASSED')
                self.assertIsNotNone(r['historical_metrics']);self.assertEqual(r['historical_comparisons'],'NOT_RUN')
    def test_unverified_exness_calendar_rejects_before_strategy_replay(self):
        path=scoped_fixture(self.root);calendar=self.root/'sessions.json'
        calendar.write_bytes(Path('config/profiles/exness-xauusd-v2.candidate.json').read_bytes())
        rewrite(path,lambda m:m.update(calendar={'file':calendar.name,'sha256':sha256(calendar.read_bytes()).hexdigest()}))
        with patch('iat.strategy_dataset_replay.replay_strategies') as engine:
            r=self.run_manifest(path);engine.assert_not_called()
        self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['historical_metrics'])
        self.assertIn('CALENDAR_COVERAGE_UNVERIFIED',r['reason_codes'])
    def test_each_required_source_review_gate_is_reused(self):
        for item in ('usage','instrument','timestamp','price_basis','calendar','finality'):
            path=v2_fixture(self.root,count=120,evaluation_minutes=60,historical=True,calendar=True)
            rewrite(path,lambda m:m['evidence_review'][item].update(status='PENDING'))
            with self.subTest(item=item),patch('iat.strategy_dataset_replay.replay_strategies') as engine:
                r=self.run_manifest(path);engine.assert_not_called()
                self.assertIn('EVIDENCE_'+item.upper()+'_PENDING',r['reason_codes'])
                self.assertIsNone(r['strategy_replay_log']);self.assertIsNone(r['historical_metrics'])
    def test_unknown_lineage_cannot_be_resolved_by_historical_label(self):
        for key,value,code in (('m5_origin','UNKNOWN','M5_LINEAGE_UNVERIFIED'),('price_basis','UNKNOWN','PRICE_BASIS_UNVERIFIED'),
                               ('timestamp_convention','PENDING','TIMESTAMP_CONVENTION_UNVERIFIED')):
            path=v2_fixture(self.root,count=120,evaluation_minutes=60,historical=True,calendar=True)
            rewrite(path,lambda m:m['lineage'].update({key:value}))
            with self.subTest(key=key),patch('iat.strategy_dataset_replay.replay_strategies') as engine:
                r=self.run_manifest(path);engine.assert_not_called()
                self.assertIn(code,r['reason_codes'])
    def test_published_audit_matches_manifest_pipeline_hash_and_phase_counts(self):
        audit=json.loads(Path('docs/source_reviews/strategy-dataset-integration-v1.json').read_text())
        for reversal in (False,True):
            for mirror in (False,True):
                path=scoped_fixture(self.root,reversal=reversal,mirror=mirror,total_minutes=35)
                r=self.run_manifest(path)
                direction=('BULLISH' if mirror else 'BEARISH') if reversal else ('BEARISH' if mirror else 'BULLISH')
                name=('sweep_' if reversal else 'continuation_')+direction.lower()
                c=next(c for c in audit['cases'] if c['case']==name)
                self.assertEqual(c['manifest_sha256'],r['dataset']['manifest_sha256'])
                self.assertEqual(c['software_repeatability']['strategy_log_hashes'],[r['strategy_replay_log']['sha256']]*2)
                strategy='SWEEP_M1_STRUCTURE_CHANGE' if reversal else 'M5_TREND_M1_CONFIRMATION'
                self.assertEqual(c['warmup_target']['setup_counts'],group(r['window_accounting']['warmup'],strategy,direction)['setup_counts'])
                self.assertEqual(c['evaluation_target']['setup_counts'],group(r['window_accounting']['evaluation_window'],strategy,direction)['setup_counts'])
        pilot=audit['existing_private_pilot_preflight']
        self.assertEqual(pilot['status'],'BLOCKED');self.assertFalse(pilot['strategy_log_produced'])
        self.assertIsNone(pilot['historical_metrics']);self.assertEqual(pilot['historical_comparisons'],'NOT_RUN')

    def test_v1_manifest_keeps_unscoped_compatibility(self):
        from test_historical_replay import write_fixture
        r=self.run_manifest(write_fixture(self.root,count=30));validate_strategy_dataset_report(r)
        self.assertEqual(r['window_accounting']['warmup']['timestamps'],0)
        self.assertEqual(r['window_accounting']['evaluation_window']['timestamps'],30)
    def test_repeatability_and_manifest_prefix_equivalence_without_resetting_warmup(self):
        for reversal in (False,True):
            path=scoped_fixture(self.root,reversal=reversal,total_minutes=35)
            full=self.run_manifest(path);again=self.run_manifest(path)
            self.assertEqual(full,again)
            cutoff=25 if not reversal else 30
            prefix_root=self.root/'prefix';prefix_root.mkdir(exist_ok=True)
            prefix=self.run_manifest(scoped_fixture(prefix_root,reversal=reversal,prefix_end=cutoff,total_minutes=35))
            entries=prefix['strategy_replay_log']['entries']
            self.assertEqual(entries,full['strategy_replay_log']['entries'][:len(entries)])
            self.assertEqual(prefix['window_accounting']['warmup'],full['window_accounting']['warmup'])
            for p,f in zip(prefix['window_accounting']['evaluation_window']['groups'],full['window_accounting']['evaluation_window']['groups']):
                self.assertEqual(p['setup_ids']['carried_in_active'],f['setup_ids']['carried_in_active'])
    def test_exact_boundary_qualification_and_blocked_evaluation_are_accounted_causally(self):
        from test_strategy_replay import observation_fixture,contract,ledger
        base=observation_fixture();l=ledger();l.record(contract(base))
        blocked=replace(contract(base,1),data_quality={'valid':False,'status':'BLOCKED','diagnostics':[]})
        l.record(blocked);l.record(contract(base,2,opposing=True))
        accounting=window_accounting(l.to_dict(),{'start':base.analysis_at,'end':(datetime.fromisoformat(base.analysis_at)+timedelta(minutes=2)).isoformat()})
        for strategy in ('M5_TREND_M1_CONFIRMATION','SWEEP_M1_STRUCTURE_CHANGE'):
            w=group(accounting['warmup'],strategy,'BULLISH');e=group(accounting['evaluation_window'],strategy,'BULLISH')
            self.assertEqual(w['setup_counts']['first_qualified'],1)
            self.assertEqual(e['setup_counts']['carried_in_active'],1)
            self.assertEqual(e['setup_counts']['first_qualified'],0)
            self.assertEqual(e['setup_counts']['invalidated_qualified'],1)
            self.assertEqual(e['snapshot_outcomes']['BLOCKED_DATA'],1)

    def test_missing_dataset_has_unmeasured_metrics_and_no_comparison(self):
        for path in (None,self.root/'absent.json'):
            r=self.run_manifest(path);validate_strategy_dataset_report(r)
            self.assertEqual(r['historical_validation'],'PENDING');self.assertEqual(r['historical_comparisons'],'NOT_RUN')
            self.assertIsNone(r['window_accounting']);self.assertIsNone(r['historical_metrics'])
    def test_wrapper_rejects_tampered_accounting_and_historical_claims(self):
        r=self.run_manifest(scoped_fixture(self.root))
        bad=deepcopy(r);bad['window_accounting']['evaluation_window']['timestamps']+=1
        with self.assertRaises(ValueError):validate_strategy_dataset_report(bad)
        bad=deepcopy(r);bad['historical_validation']='DATASET_PIPELINE_CHECKS_PASSED';bad['historical_metrics']=bad['window_accounting']['evaluation_window']
        with self.assertRaises(ValueError):validate_strategy_dataset_report(bad)
    def test_cli_pending_atomic_failure_and_no_overwrite(self):
        out=self.root/'report.json'
        with redirect_stdout(StringIO()):self.assertEqual(main(['--report-path',str(out)]),3)
        r=json.loads(out.read_text());validate_strategy_dataset_report(r)
        before=out.read_bytes()
        with redirect_stdout(StringIO()):self.assertEqual(main(['--report-path',str(out)]),1)
        self.assertEqual(out.read_bytes(),before)
    def test_cli_publication_failure_retains_incomplete_failure_report(self):
        path=scoped_fixture(self.root);out=self.root/'failure.json'
        with patch('iat.evidence.os.replace',side_effect=OSError('SYNTHETIC_PUBLICATION_FAILURE')),redirect_stdout(StringIO()):
            self.assertEqual(main(['--manifest',str(path),'--report-path',str(out)]),1)
        r=json.loads(out.read_text());self.assertEqual(r['status'],'FAIL')
        self.assertEqual(r['reason_codes'],['RUN_INCOMPLETE']);self.assertIsNone(r['strategy_replay_log'])
        self.assertIsNone(r['historical_metrics']);validate_strategy_dataset_report(r)

    def test_cli_synthetic_roundtrip_keeps_all_guards(self):
        path=scoped_fixture(self.root);out=self.root/'private-report.json'
        with redirect_stdout(StringIO()):self.assertEqual(main(['--manifest',str(path),'--report-path',str(out)]),2)
        r=json.loads(out.read_text());validate_strategy_dataset_report(r)
        self.assertFalse(r['safety']['execution_allowed']);self.assertEqual(r['safety']['signal'],'WAIT')
        self.assertEqual(r['exness'],'BLOCKED');self.assertEqual(r['historical_validation'],'PENDING')
