"""Synthetic archive fixtures only; no actual user CSV or native-feed qualification."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime,timedelta
from hashlib import sha256
from io import StringIO
from pathlib import Path
import csv,json,tempfile,unittest
from unittest.mock import patch
from iat.pilot_preparation import prepare_pilot,handoff_review,stream_archive,file_fingerprint
from iat.chart_benchmark import read_json,write_new,packet_at
from iat.replay_dataset import load_dataset
from iat.intelligence.strategy_replay import digest
from diagnostics.prepare_real_data_pilot import main
from test_qualification_assistant import export_fixture,modify_csv,save


def inputs(root):
    spec=export_fixture(root);s=read_json(spec)
    return spec,root/s['frames']['M1']['file'],root/s['frames']['M5']['file'],s


def prepare(root,output='output',*,missing_m1=False,dry=False,spec_override=True):
    spec,m1,m5,s=inputs(root)
    result=prepare_pilot(spec if spec_override else None,None if missing_m1 else m1,m5,root/output,
        start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'],dry_run=dry)
    return result,spec,m1,m5


class PilotPreparationTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_native_m1_missing_never_inferred_from_spec_or_m5(self):
        result,_,m1,_=prepare(self.root,missing_m1=True)
        self.assertTrue(m1.exists()) # Explicit omission must not auto-discover even this file.
        self.assertIn('MISSING_NATIVE_M1',result['readiness']['reason_codes'])
        self.assertFalse((self.root/'output'/'candidate-package').exists())
        self.assertEqual(read_json(self.root/'output'/'alignment-audit.json')['status'],'NOT_RUN')
    def test_selected_pair_reuses_unchanged_alignment_and_pending_gate(self):
        r,_,_,_=prepare(self.root);out=self.root/'output'
        audit=read_json(out/'alignment-audit.json');self.assertEqual(audit['status'],'PASS')
        self.assertEqual(audit['m1_to_native_m5_comparison']['evaluation']['comparable_m5_bars'],12)
        self.assertEqual(audit['aggregation_role'],'DIAGNOSTIC_ONLY_NATIVE_M5_NEVER_REPLACED')
        self.assertEqual(r['readiness']['qualification'],'DATA_NOT_QUALIFIED');self.assertFalse(r['readiness']['review_packets_created'])
        self.assertEqual(read_json(out/'candidate-package'/'candidate-manifest.json')['lineage']['m5_origin'],'NATIVE_SAME_FEED')
        self.assertTrue((out/'original-import-spec.json').exists())
    def test_dry_run_creates_only_reports_no_selected_or_normalized_data(self):
        r,_,_,_=prepare(self.root,dry=True);out=self.root/'output'
        self.assertIn('DRY_RUN_NO_NORMALIZATION',r['readiness']['reason_codes'])
        self.assertFalse((out/'selection').exists());self.assertFalse((out/'candidate-package').exists())
    def test_metadata_free_inspection_does_not_infer_date_basis_feed(self):
        r,_,_,_=prepare(self.root,dry=True,spec_override=False)
        report=read_json(self.root/'output'/'source-inspection.json')['sources']['M5']
        self.assertEqual(report['row_count'],30);self.assertIsNone(report['timestamp_range'])
        self.assertEqual(report['status'],'INSPECTED_METADATA_UNVERIFIED');self.assertIn('IMPORT_METADATA_REQUIRED',r['readiness']['reason_codes'])
    def test_feed_mismatch_and_derived_m5_block_and_keep_lineage(self):
        spec,m1,m5,s=inputs(self.root);s['frames']['M5'].update(feed_id='OTHER',origin='AGGREGATED_FROM_M1');save(spec,s)
        r=prepare_pilot(spec,m1,m5,self.root/'output',start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        self.assertIn('SELECTED_WINDOW_MECHANICAL_CHECKS_FAILED',r['readiness']['reason_codes'])
        report=read_json(self.root/'output'/'candidate-package'/'report.json');codes={i['code'] for i in report['issues']}
        self.assertTrue({'FEED_MISMATCH','NATIVE_M1_M5_REQUIRED'}<=codes)
    def test_duplicates_nonadjacent_and_incomplete_bars_block_archive(self):
        for defect in ('duplicate','incomplete','naive'):
            folder=self.root/defect;folder.mkdir();spec,m1,m5,s=inputs(folder)
            if defect=='duplicate':modify_csv(spec,'M5',lambda rows:rows.append(dict(rows[0])))
            elif defect=='incomplete':modify_csv(spec,'M5',lambda rows:rows[-1].update(Done='false'))
            else:modify_csv(spec,'M5',lambda rows:rows[1].update(Time='2026-11-12T08:05:00'))
            r=prepare_pilot(spec,m1,m5,folder/'out',start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
            codes=read_json(folder/'out'/'source-inspection.json')['sources']['M5']['errors']
            expected={'duplicate':'TIMESTAMP_DUPLICATE','incomplete':'BAR_NOT_COMPLETE','naive':'UTC_TIMESTAMP_OR_RECORD_INVALID'}[defect]
            self.assertIn(expected,codes);self.assertIn('M5_ARCHIVE_INTEGRITY_NOT_ESTABLISHED',r['readiness']['reason_codes'])
            self.assertFalse((folder/'out'/'candidate-package').exists())
    def test_gaps_are_diagnosed_in_selected_session_scope_not_globally_assumed(self):
        spec,m1,m5,s=inputs(self.root);modify_csv(spec,'M1',lambda rows:rows.pop(5))
        prepare_pilot(spec,m1,m5,self.root/'output',start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        inspected=read_json(self.root/'output'/'source-inspection.json')['sources']['M1'];self.assertEqual(inspected['raw_gap_count'],1)
        audit=read_json(self.root/'output'/'alignment-audit.json');self.assertEqual(audit['status'],'BLOCKED')
        self.assertIn('UNEXPECTED_MISSING_BARS',{d['code'] for d in audit['frames']['M1']['diagnostics']})
    def test_corrected_bars_cannot_be_fixed_by_aggregating_m1(self):
        spec,m1,m5,s=inputs(self.root);s['frames']['M5']['corrections'].update(status='PROVIDER_CORRECTED',reference='synthetic:mock-revision',previous_source_sha256='0'*64);save(spec,s)
        modify_csv(spec,'M5',lambda rows:rows[20].update(High='105'))
        before=file_fingerprint(m5)
        prepare_pilot(spec,m1,m5,self.root/'output',start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        audit=read_json(self.root/'output'/'alignment-audit.json');self.assertGreater(audit['m1_to_native_m5_comparison']['mismatch_count'],0)
        self.assertEqual(file_fingerprint(m5),before)
    def test_dst_ambiguous_calendar_remains_blocked(self):
        spec,m1,m5,s=inputs(self.root);cal=read_json(self.root/'calendar.json');cal['timezone']='America/New_York'
        cal['weekdays']['sun']['quotes']=[{'open':'01:30:00','close':'02:00:00','close_day_offset':0}]
        # This coverage includes a DST fold, so that naive session boundary cannot be guessed.
        cal['coverage']={'start':'2026-10-31','end':'2026-11-16'}
        save(self.root/'calendar.json',cal);s['calendar']['sha256']=sha256((self.root/'calendar.json').read_bytes()).hexdigest();save(spec,s)
        r=prepare_pilot(spec,m1,m5,self.root/'output',start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        self.assertIn('SELECTED_WINDOW_MECHANICAL_CHECKS_FAILED',r['readiness']['reason_codes'])
    def test_large_40610_row_csv_over_old_byte_limit_is_streamed(self):
        spec,m1,m5,s=inputs(self.root);start=datetime.fromisoformat(s['utc_range']['start'])
        # Synthetic long archive has its own generated dates; it is NOT the user's reported file.
        s['source']['retrieved_at_utc']=(start+timedelta(days=160)).isoformat();s['frames']['M5']['ignored_columns']=['Padding']
        named=self.root/'XAUUSD_M5_IAT_normalized.csv';s['frames']['M5']['file']=named.name;save(spec,s)
        with named.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['Time','Open','High','Low','Close','Ticks','Done','Padding'],lineterminator='\n');w.writeheader()
            for i in range(40610):w.writerow({'Time':(start+timedelta(minutes=5*i)).isoformat(),'Open':100,'High':101,'Low':99,'Close':100,'Ticks':10,'Done':'true','Padding':'SYNTHETIC ONLY '*12})
        before=file_fingerprint(named);self.assertGreater(before['byte_count'],4*1024*1024)
        result=prepare_pilot(spec,m1,named,self.root/'output',start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        scan=read_json(self.root/'output'/'source-inspection.json')['sources']['M5']
        self.assertEqual(scan['row_count'],40610);self.assertEqual(scan['selected_row_count'],30);self.assertEqual(scan['status'],'PASS')
        self.assertEqual(read_json(self.root/'output'/'alignment-audit.json')['status'],'PASS')
        self.assertEqual(file_fingerprint(named),before);self.assertEqual(result['readiness']['qualification'],'DATA_NOT_QUALIFIED')
    def test_repeatability_hashes_and_originals_unchanged(self):
        spec,m1,m5,s=inputs(self.root);before={p.name:file_fingerprint(p) for p in self.root.iterdir() if p.is_file()}
        opts=dict(start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        a=prepare_pilot(spec,m1,m5,self.root/'a',**opts);b=prepare_pilot(spec,m1,m5,self.root/'b',**opts)
        self.assertEqual(a,b)
        for name,fingerprint in before.items():self.assertEqual(file_fingerprint(self.root/name),fingerprint)
    def test_future_append_changes_archive_binding_not_prior_selection_or_packet(self):
        spec,m1,m5,s=inputs(self.root);opts=dict(start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        a=prepare_pilot(spec,m1,m5,self.root/'a',**opts)
        for tf in ('M1','M5'):
            def append(rows,tf=tf):
                row=dict(rows[-1]);row['Time']=(datetime.fromisoformat(row['Time'])+timedelta(minutes=1 if tf=='M1' else 5)).isoformat();rows.append(row)
            modify_csv(spec,tf,append)
        b=prepare_pilot(spec,m1,m5,self.root/'b',**opts)
        self.assertNotEqual(a['archive_binding_id'],b['archive_binding_id']);self.assertEqual(a['selected_dataset_id'],b['selected_dataset_id'])
        at='2026-11-12T09:33:00Z'
        one=packet_at(load_dataset(self.root/'a'/'candidate-package'/'candidate-manifest.json'),at)
        two=packet_at(load_dataset(self.root/'b'/'candidate-package'/'candidate-manifest.json'),at)
        self.assertEqual(one,two);self.assertEqual(one['frames']['M5'][-1]['timestamp'],'2026-11-12T09:25:00+00:00')
        self.assertNotIn('adaptive_report',json.dumps(one));self.assertEqual(a['readiness']['status'],'BLOCKED')
    def test_missing_approval_and_frozen_source_change_never_create_packets(self):
        spec,m1,m5,s=inputs(self.root);s['dataset_kind']='INDEPENDENT_HISTORICAL';s['source']['reference']='https://example.org/SYNTHETIC-MOCK';save(spec,s)
        prep=self.root/'prep';prepare_pilot(spec,m1,m5,prep,start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        with patch('iat.pilot_preparation.generate_pilot') as generator:
            r=handoff_review(prep,None,None,None,self.root/'handoff');generator.assert_not_called()
        self.assertIn('INDEPENDENT_APPROVAL_REQUIRED',r['reason_codes']);self.assertFalse((self.root/'handoff'/'reviewer-packets').exists())
        with m5.open('a') as f:f.write('\n')
        r=handoff_review(prep,None,None,None,self.root/'changed');self.assertIn('FROZEN_SOURCE_CHANGED',r['reason_codes'])
    def test_invalid_windows_and_no_overwrite(self):
        r,spec,m1,m5=prepare(self.root);s=read_json(spec)
        with self.assertRaises(FileExistsError):prepare_pilot(spec,m1,m5,self.root/'output',start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        with self.assertRaises(ValueError):prepare_pilot(spec,m1,m5,self.root/'bad',start='2026-11-12T08:01:00Z',end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
    def test_cli_inspection_without_m1_is_successfully_blocked(self):
        spec,_,m5,s=inputs(self.root)
        with redirect_stdout(StringIO()):result=main(['inspect','--spec',str(spec),'--m5',str(m5),'--start-utc',s['utc_range']['start'],'--end-utc',s['utc_range']['end'],'--evaluation-start-utc',s['evaluation']['start'],'--output-directory',str(self.root/'out')])
        self.assertEqual(result,3);self.assertTrue((self.root/'out'/'preparation-manifest.json').exists())

    def test_explicit_lack_of_local_authorization_prevents_source_reads(self):
        spec,m1,m5,s=inputs(self.root);s['authorized_local_use']=False;save(spec,s)
        with patch('iat.pilot_preparation.stream_archive') as scan:
            r=prepare_pilot(spec,m1,m5,self.root/'out',start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start']);scan.assert_not_called()
        self.assertIn('LOCAL_USE_AUTHORIZATION_REQUIRED',r['readiness']['reason_codes'])

    def test_qualified_handoff_delegates_closed_only_generation_after_plan_is_written(self):
        # MOCK ONLY: no fixture supplies genuine source qualification or human reviews.
        spec,m1,m5,s=inputs(self.root);s['dataset_kind']='INDEPENDENT_HISTORICAL';s['source']['reference']='https://example.org/SYNTHETIC-MOCK-NOT-REAL';save(spec,s)
        prep=self.root/'prep';prepare_pilot(spec,m1,m5,prep,start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        manifest=prep/'candidate-package'/'candidate-manifest.json';record=self.root/'mock-review.json';planfile=self.root/'mock-plan.json'
        write_new(record,{'mock':'SYNTHETIC ONLY'});write_new(planfile,{'mock':'SYNTHETIC ONLY'})
        stamp='2026-11-12T09:33:00+00:00';packet=packet_at(load_dataset(manifest),stamp)
        plan={'sha256':'0'*64,'reviewer_codes':['mock-a','mock-b'],'qualified_interval':s['utc_range'],'timestamps':[stamp]}
        dest=self.root/'handoff'
        def generate(*args):
            self.assertTrue((dest/'private'/'plan.json').exists())
            return {'benchmark':{'packets':[packet]}}
        with patch('iat.pilot_preparation.assess_candidate',return_value={'status':'HUMAN_APPROVAL_RECORDED_PRECHECKS_PASSED'}),patch('iat.pilot_preparation.register_plan',return_value=(plan,{})),patch('iat.pilot_preparation.generate_pilot',side_effect=generate) as engine:
            r=handoff_review(prep,manifest,record,planfile,dest);engine.assert_called_once()
        self.assertEqual(r['status'],'READY_OPERATOR_ATTESTED');self.assertTrue(r['review_packets_created'])
        self.assertEqual(r['evaluation_timestamps'],[stamp]);self.assertEqual(r['historical_validation'],'PENDING')
        public=read_json(dest/'reviewer-packets'/(packet['packet_id']+'.json'))
        self.assertEqual(public['frames']['M5'][-1]['timestamp'],'2026-11-12T09:25:00+00:00')
        self.assertNotIn('adaptive_report',json.dumps(public))

    def test_handoff_rejects_changed_preparation_artifacts_before_assessment(self):
        spec,m1,m5,s=inputs(self.root);s['dataset_kind']='INDEPENDENT_HISTORICAL';s['source']['reference']='https://example.org/SYNTHETIC-MOCK';save(spec,s)
        prep=self.root/'prep';prepare_pilot(spec,m1,m5,prep,start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        (prep/'alignment-audit.json').write_text('{}')
        with patch('iat.pilot_preparation.assess_candidate') as assess:
            r=handoff_review(prep,None,None,None,self.root/'out');assess.assert_not_called()
        self.assertEqual(r['status'],'BLOCKED');self.assertFalse((self.root/'out'/'reviewer-packets').exists())

    def test_committed_alignment_and_readiness_are_synthetic_and_reproducible(self):
        spec,m1,m5,s=inputs(self.root);prepare_pilot(spec,m1,m5,self.root/'out',start=s['utc_range']['start'],end=s['utc_range']['end'],evaluation_start=s['evaluation']['start'])
        published=Path('docs/research_audits/pilot-preparation-synthetic-v1')
        for name in ('source-inspection.json','alignment-audit.json','evidence-checklist.json','review-readiness.json'):
            self.assertEqual(read_json(self.root/'out'/name),read_json(published/name))
        audit=read_json(published/'audit.json');self.assertFalse(audit['actual_user_m5_file_inspected']);self.assertFalse(audit['real_independent_reviews_performed'])
        self.assertTrue(audit['repeat_preparation_identical'])

    def test_oversized_physical_line_fails_closed_with_bounded_read(self):
        file=self.root/'oversized.csv';file.write_text('a\n'+'x'*(1024*1024+1)+'\n')
        result=stream_archive(file);self.assertEqual(result['status'],'BLOCKED');self.assertIn('CSV_LINE_LIMIT',result['errors'])
