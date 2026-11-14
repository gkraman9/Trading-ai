"""Full-path SYNTHETIC manifests only; no provider credentials or real source claims."""
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timedelta
from hashlib import sha256
from io import StringIO
from pathlib import Path
import csv,json,tempfile,unittest
from unittest.mock import patch
from iat.journal_dataset_replay import run_journal_manifest,validate_journal_dataset_report
from iat.intelligence.reasoning_journal import replay_reasoning_journal,journal_prefix
from iat.intelligence.strategy_replay import digest
from iat.replay_dataset import load_dataset
from diagnostics.journal_dataset_replay import main
from test_reasoning_journal import journal_fixture
from test_context_components import CONFIG
from test_context_engine import P7
from test_strategy_dataset_replay import scoped_fixture
from test_historical_replay import rewrite,recalc


def manifest_fixture(root,case='regime_change',*,total=45,prefix_end=None):
    """Omitted synthetic M1 parents supply M5 warm-up; all overlap is aggregated."""
    a,b,origin=journal_fixture('opposing_choch' if case=='regime_change' else 'tie' if case=='tie' else 'persistent_trend')
    while len(a)<total:
        at=datetime.fromisoformat(a[-1]['timestamp'])+timedelta(minutes=1);v=a[-1]['close']
        a.append(dict(timestamp=at.isoformat(),open=v,high=v+.5,low=v-.5,close=v))
    b=[c for c in b if datetime.fromisoformat(c['timestamp'])<datetime.fromisoformat(a[0]['timestamp'])]
    if case=='tie':b[-1].update(open=95,high=95.5,low=94.5,close=95)
    else:
        for c in b:
            for key in ('open','high','low','close'):c[key]-=20
    parents=[]
    for c in b:parents.extend(dict(c,timestamp=(datetime.fromisoformat(c['timestamp'])+timedelta(minutes=i)).isoformat()) for i in range(5))
    for j in range(0,len(a)-4,5):
        cs=a[j:j+5];b.append(dict(timestamp=cs[0]['timestamp'],open=cs[0]['open'],high=max(c['high'] for c in cs),
                                 low=min(c['low'] for c in cs),close=cs[-1]['close']))
    lineage=digest(parents+a)
    end=datetime.fromisoformat(a[0]['timestamp'])+timedelta(minutes=prefix_end or total)
    a=[r for r in a if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=1)<=end]
    b=[r for r in b if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=5)<=end]
    if case=='coverage_gap':a.pop(23)
    frames={}
    for tf,rows in (('M1',a),('M5',b)):
        path=root/(tf.lower()+'.csv')
        with path.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['timestamp','open','high','low','close'],lineterminator='\n');w.writeheader();w.writerows(rows)
        frames[tf]={'file':path.name,'sha256':sha256(path.read_bytes()).hexdigest()}
    start=datetime.fromisoformat(a[0]['timestamp'])+timedelta(minutes=20)
    manifest={'version':2,'symbol':'XAUUSD','dataset_kind':'SYNTHETIC_FIXTURE',
        'source':{'name':'SYNTHETIC journal fixture','reference':'synthetic:journal-dataset-unit','curation_id':'synthetic-journal',
                  'retrieved_at_utc':'2026-11-14T00:00:00Z','independent_review':'PENDING'},
        'utc_range':{'start':b[0]['timestamp'],'end':end.isoformat()},'frames':frames,'calendar':None,'finality_attested':True,
        'evaluation':{'start':start.isoformat(),'end':end.isoformat()},
        'warmup':{tf:{'start':rows[0]['timestamp'],'end':start.isoformat()} for tf,rows in (('M1',a),('M5',b))},
        'lineage':{'feed_id':'SYNTHETIC_JOURNAL','price_basis':'BID','timestamp_convention':'INTERVAL_OPEN_UTC',
                   'm5_origin':'AGGREGATED_FROM_M1','raw_sha256':lineage},
        'evidence_review':{k:{'status':'PENDING','reference':'synthetic:mock-evidence','reason_code':'SYNTHETIC_ONLY'}
                           for k in ('usage','instrument','timestamp','price_basis','calendar','finality')}}
    path=root/'manifest.json';path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
    return path,origin


def run_fixture(root,case='regime_change',*,total=45,prefix_end=None,eval_end=25,cutoff=None):
    path,origin=manifest_fixture(root,case,total=total,prefix_end=prefix_end)
    start=datetime.fromisoformat(json.loads(path.read_text())['evaluation']['start'])-timedelta(minutes=20)
    report=run_journal_manifest(path,config=CONFIG,intelligence_config=P7,
        evaluation_end=(start+timedelta(minutes=eval_end)).isoformat() if eval_end else None,
        observation_cutoff=(start+timedelta(minutes=cutoff)).isoformat() if cutoff else None)
    return report,path,origin


class JournalDatasetTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_manifest_gate_and_warmup_evaluation_tail_are_separate(self):
        r,path,origin=run_fixture(self.root);validate_journal_dataset_report(r)
        cohorts=r['accounting']['cohorts']
        self.assertEqual(cohorts['warmup']['assessment_count'],20)
        self.assertEqual(cohorts['evaluation']['assessment_count'],5)
        self.assertEqual(cohorts['observation_tail']['assessment_count'],20)
        self.assertTrue(cohorts['state_at_evaluation_start']['pending_warmup_reviews'])
        self.assertEqual(r['scope']['outcome_observation_cutoff_utc'],'2026-11-12T08:45:00+00:00')
        self.assertEqual(r['historical_validation'],'PENDING');self.assertIsNone(r['historical_metrics'])
        ds=load_dataset(path)
        previous=replay_reasoning_journal('XAUUSD',ds.rows['M1'],ds.rows['M5'],config=CONFIG,intelligence_config=P7,
                     provenance=ds.provenance,calendar=ds.calendar,observed_finality=ds.finality_attested)
        self.assertEqual(previous,r['reasoning_journal'])
    def test_regime_change_is_recorded_without_rewriting_original(self):
        r,path,origin=run_fixture(self.root);j=r['reasoning_journal']
        old=next(a for a in j['assessments'] if a['timestamp_utc']==origin.isoformat())
        self.assertEqual(old['adaptive_report']['regime']['directional'],'TREND_UP')
        revision=next(c for c in j['assessment_revisions'] if c['timestamp_utc']>origin.isoformat() and 'FRESH_OPPOSING_M1_CHOCH' in c['reason_codes'])
        self.assertEqual(revision['changes']['regime']['after'],'TRANSITION')
        reviews=[o for o in j['outcome_reviews'] if o['assessment_id']==old['assessment_id'] and o['horizon_minutes']==5]
        self.assertEqual(reviews[-1]['status'],'CONTRADICTED')
        self.assertEqual(reviews[-1]['assessment_sha256'],old['adaptive_report']['sha256'])
    def test_ties_preserve_members_and_unresolved_denominators(self):
        r,path,origin=run_fixture(self.root,'tie')
        for h in r['accounting']['cohorts']['evaluation']['horizons']:
            tied=[g for g in h['by_original_regime_and_leader_status'] if g['leader_status']=='TIED']
            self.assertTrue(tied)
            for g in tied:
                self.assertEqual(g['resolved_review_denominator'],0)
                self.assertEqual(g['outcomes']['UNRESOLVED'],g['all_assessment_denominator'])
                self.assertIn('ORIGINAL_SCENARIO_TIE',g['unresolved_reason_counts'])
                self.assertGreater(sum(s['original_leader_memberships']['denominator'] for s in g['scenario_reviews']),g['all_assessment_denominator'])
    def test_incomplete_input_horizon_retained_and_cutoff_explicit(self):
        r,path,origin=run_fixture(self.root,total=30,eval_end=None)
        self.assertEqual(r['scope']['outcome_observation_cutoff_utc'],'2026-11-12T08:30:00+00:00')
        h15=next(h for h in r['accounting']['cohorts']['evaluation']['horizons'] if h['horizon_minutes']==15)
        self.assertEqual(h15['total']['all_assessment_denominator'],10)
        self.assertEqual(h15['total']['incomplete_horizons'],10)
        self.assertEqual(h15['total']['outcomes']['UNRESOLVED'],10)
        self.assertEqual(h15['total']['unresolved_reason_counts']['HORIZON_INCOMPLETE'],10)
    def test_gap_preflight_rejection_has_no_journal_or_measured_metrics(self):
        path,_=manifest_fixture(self.root,'coverage_gap')
        with patch('iat.journal_dataset_replay.replay_reasoning_journal') as replay:
            r=run_journal_manifest(path,config=CONFIG,intelligence_config=P7);replay.assert_not_called()
        self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['reasoning_journal']);self.assertIsNone(r['accounting'])
        self.assertIsNone(r['historical_metrics']);self.assertEqual(r['historical_comparisons'],'NOT_RUN')
        self.assertFalse(r['preflight']['frames']['M1']['valid'])
    def test_observation_tail_finishes_reviews_but_never_adds_eval_assessments(self):
        full,path,origin=run_fixture(self.root)
        cut=run_journal_manifest(path,config=CONFIG,intelligence_config=P7,evaluation_end='2026-11-12T08:25:00Z',observation_cutoff='2026-11-12T08:30:00Z')
        self.assertEqual(full['accounting']['cohorts']['evaluation']['assessment_count'],cut['accounting']['cohorts']['evaluation']['assessment_count'])
        original=[a for a in full['reasoning_journal']['assessments'] if '2026-11-12T08:20:00+00:00' < a['timestamp_utc']<='2026-11-12T08:25:00+00:00']
        old=[a for a in cut['reasoning_journal']['assessments'] if a['assessment_id'] in {v['assessment_id'] for v in original}]
        self.assertEqual(original,old)
        f=full['accounting']['cohorts']['evaluation']['horizons'][1]['total'];c=cut['accounting']['cohorts']['evaluation']['horizons'][1]['total']
        self.assertEqual(f['incomplete_horizons'],0);self.assertEqual(c['incomplete_horizons'],5)
    def test_denominators_and_group_sums_include_all_original_states(self):
        r,path,origin=run_fixture(self.root,eval_end=35)
        for phase in ('warmup','evaluation','observation_tail'):
            c=r['accounting']['cohorts'][phase]
            for h in c['horizons']:
                total=h['total'];groups=h['by_original_regime_and_leader_status']
                self.assertEqual(sum(total['outcomes'].values()),c['assessment_count'])
                self.assertEqual(total['resolved_review_denominator'],total['outcomes']['SUPPORTED']+total['outcomes']['CONTRADICTED'])
                self.assertEqual(sum(g['all_assessment_denominator'] for g in groups),c['assessment_count'])
                for status in ('SUPPORTED','CONTRADICTED','UNRESOLVED'):
                    self.assertEqual(sum(g['outcomes'][status] for g in groups),total['outcomes'][status])
    def test_full_run_repeatability_and_common_cutoff_manifest_prefix(self):
        full,path,origin=run_fixture(self.root)
        self.assertEqual(full,run_journal_manifest(path,config=CONFIG,intelligence_config=P7,evaluation_end='2026-11-12T08:25:00Z'))
        pdir=self.root/'prefix';pdir.mkdir();prefix,_,_=run_fixture(pdir,total=45,prefix_end=30)
        bounded=run_journal_manifest(path,config=CONFIG,intelligence_config=P7,evaluation_end='2026-11-12T08:25:00Z',observation_cutoff='2026-11-12T08:30:00Z')
        self.assertEqual(prefix['reasoning_journal'],bounded['reasoning_journal'])
        self.assertEqual(prefix['accounting']['cohorts'],bounded['accounting']['cohorts'])
        self.assertEqual(prefix['scope']['evaluation'],bounded['scope']['evaluation'])
        self.assertEqual(prefix['dataset']['lineage'],bounded['dataset']['lineage'])
        self.assertNotEqual(prefix['dataset']['manifest_sha256'],bounded['dataset']['manifest_sha256'])
        self.assertEqual(prefix['reasoning_journal'],journal_prefix(full['reasoning_journal'],datetime.fromisoformat('2026-11-12T08:30:00+00:00')))
    def test_source_label_checksums_finality_and_coverage_cannot_be_bypassed(self):
        path,_=manifest_fixture(self.root)
        rewrite(path,lambda m:(m.update(dataset_kind='INDEPENDENT_HISTORICAL',finality_attested=False),m['source'].update(reference='https://example.org/SYNTHETIC-MOCK')))
        with patch('iat.journal_dataset_replay.replay_reasoning_journal') as replay:
            r=run_journal_manifest(path,config=CONFIG,intelligence_config=P7);replay.assert_not_called()
        self.assertIn('INDEPENDENT_REVIEW_PENDING',r['reason_codes']);self.assertIn('EVIDENCE_CALENDAR_PENDING',r['reason_codes'])
        self.assertIn('CANDLE_FINALITY_UNCERTAIN',r['reason_codes']);self.assertIsNone(r['historical_metrics'])
        with self.assertRaises(TypeError):run_journal_manifest(path,provenance='HISTORICAL_RESEARCH')
    def test_unsafe_scopes_are_rejected_without_analysis(self):
        path,_=manifest_fixture(self.root)
        for end,cutoff in (('2026-11-12T08:20:00Z',None),('2026-11-12T08:26:00Z',None),('2026-11-12T08:30:00Z','2026-11-12T08:25:00Z'),
                           (None,'2026-11-12T09:00:00Z'),(None,'2026-11-12T08:44:30Z')):
            with self.subTest(end=end,cutoff=cutoff),patch('iat.journal_dataset_replay.replay_reasoning_journal') as replay:
                r=run_journal_manifest(path,evaluation_end=end,observation_cutoff=cutoff);replay.assert_not_called()
                self.assertIn('JOURNAL_SCOPE_INVALID',r['reason_codes'])
    def test_selected_historical_coverage_cannot_borrow_observation_tail(self):
        from test_evaluation_window import v2_fixture
        path=v2_fixture(self.root,count=120,evaluation_minutes=60,historical=True,calendar=True)
        with patch('iat.journal_dataset_replay.replay_reasoning_journal') as replay:
            r=run_journal_manifest(path,config=CONFIG,intelligence_config=P7,evaluation_end='2026-11-12T09:05:00Z')
            replay.assert_not_called()
        self.assertTrue(r['preflight']['alignment']['evaluation']['coverage_sufficient'])
        self.assertEqual(r['evaluation_coverage']['comparable_m5_bars'],1)
        self.assertIn('EVALUATION_COVERAGE_INSUFFICIENT',r['reason_codes'])
        self.assertIsNone(r['historical_metrics'])
    def test_checksum_malformed_ohlc_and_consistency_fail_before_journal(self):
        for defect in ('checksum','ohlc','consistency','unclosed'):
            path,_=manifest_fixture(self.root);csv_path=self.root/'m1.csv'
            if defect=='checksum':csv_path.write_bytes(csv_path.read_bytes()+b'\n')
            else:
                with csv_path.open(newline='') as f:rows=list(csv.DictReader(f))
                if defect=='ohlc':rows[10]['high']='0'
                elif defect=='unclosed':rows.append(dict(rows[-1],timestamp=json.loads(path.read_text())['utc_range']['end']))
                else:rows[10]['high']=str(float(rows[10]['high'])+500)
                with csv_path.open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=['timestamp','open','high','low','close']);w.writeheader();w.writerows(rows)
                recalc(path,'M1')
            with self.subTest(defect=defect),patch('iat.journal_dataset_replay.replay_reasoning_journal') as replay:
                r=run_journal_manifest(path,config=CONFIG,intelligence_config=P7);replay.assert_not_called()
                self.assertIn(r['status'],('FAIL','BLOCKED'));self.assertIsNone(r['accounting'])
                self.assertIsNone(r['historical_metrics']);validate_journal_dataset_report(r)
    def test_unverified_calendar_still_blocks_before_journal(self):
        path,_=manifest_fixture(self.root);cal=self.root/'sessions.json'
        cal.write_bytes(Path('config/profiles/exness-xauusd-v2.candidate.json').read_bytes())
        rewrite(path,lambda m:m.update(calendar={'file':cal.name,'sha256':sha256(cal.read_bytes()).hexdigest()}))
        with patch('iat.journal_dataset_replay.replay_reasoning_journal') as replay:
            r=run_journal_manifest(path,config=CONFIG,intelligence_config=P7);replay.assert_not_called()
        self.assertEqual(r['status'],'BLOCKED');self.assertIsNone(r['historical_metrics'])
    def test_validator_rejects_edited_group_counts_scope_and_historical_claims(self):
        r,path,origin=run_fixture(self.root)
        for defect in ('counts','scope','claim'):
            bad=deepcopy(r)
            if defect=='counts':bad['accounting']['cohorts']['evaluation']['horizons'][0]['total']['resolved_review_denominator']+=1
            elif defect=='scope':bad['scope']['outcome_observation_cutoff_utc']='2099-01-01T00:00:00Z'
            else:bad['historical_validation']='DATASET_PIPELINE_CHECKS_PASSED';bad['historical_metrics']=bad['accounting']['cohorts']['evaluation']
            with self.subTest(defect=defect),self.assertRaises(ValueError):validate_journal_dataset_report(bad)
    def test_v1_manifest_no_inferred_warmup_and_legacy_logs_are_unchanged(self):
        from test_historical_replay import write_fixture
        from iat.strategy_dataset_replay import run_strategy_manifest
        from iat.intelligence.decision_log import DecisionLog
        path=write_fixture(self.root,count=30)
        before=run_strategy_manifest(path,config=CONFIG,intelligence_config=P7)
        r=run_journal_manifest(path,config=CONFIG,intelligence_config=P7)
        self.assertEqual(r['accounting']['cohorts']['warmup']['assessment_count'],0)
        self.assertEqual(r['accounting']['cohorts']['evaluation']['assessment_count'],30)
        self.assertEqual(before,run_strategy_manifest(path,config=CONFIG,intelligence_config=P7))
        self.assertEqual(before['strategy_replay_log']['log_version'],1)
        self.assertEqual(DecisionLog(1,{},()).to_dict()['log_version'],1)
    def test_atomic_cli_publication_failure_keeps_incomplete_failure(self):
        path,_=manifest_fixture(self.root,total=30);out=self.root/'failure.json'
        with patch('iat.evidence.os.replace',side_effect=OSError('SYNTHETIC_FAILURE')),redirect_stdout(StringIO()):
            self.assertEqual(main(['--manifest',str(path),'--report-path',str(out)]),1)
        report=json.loads(out.read_text());self.assertEqual(report['reason_codes'],['RUN_INCOMPLETE'])
        self.assertEqual(report['status'],'FAIL');self.assertIsNone(report['reasoning_journal'])
        self.assertIsNone(report['historical_metrics']);validate_journal_dataset_report(report)

    def test_cli_pending_and_overwrite_protection(self):
        path=self.root/'private report.json'
        with redirect_stdout(StringIO()):self.assertEqual(main(['--report-path',str(path)]),3)
        r=json.loads(path.read_text());validate_journal_dataset_report(r);self.assertIsNone(r['historical_metrics'])
        before=path.read_bytes()
        with redirect_stdout(StringIO()):self.assertEqual(main(['--report-path',str(path)]),1)
        self.assertEqual(before,path.read_bytes())

    def test_published_synthetic_audit_matches_recomputed_evaluation(self):
        audit=json.loads(Path('docs/research_audits/journal-dataset-evaluation-synthetic-v1.json').read_text())
        self.assertEqual(audit['historical_validation'],'PENDING')
        self.assertIsNone(audit['historical_metrics'])
        for case in ('persistent_trend','regime_change','tie','incomplete','coverage_gap'):
            folder=self.root/case;folder.mkdir()
            r,_,_=run_fixture(folder,case,total=30 if case=='incomplete' else 45,eval_end=None if case=='incomplete' else 25)
            expected=audit['cases'][case]
            with self.subTest(case=case):
                self.assertEqual(r['status'],expected['status'])
                self.assertEqual(r['dataset']['manifest_sha256'],expected['manifest_sha256'])
                self.assertEqual(r['configuration_hashes'],expected['configuration_hashes'])
                self.assertEqual(r['reasoning_journal']['sha256'] if r['reasoning_journal'] else None,expected['journal_sha256'])
                if r['accounting']:self.assertEqual(r['accounting']['cohorts']['evaluation'],expected['evaluation'])
