"""SYNTHETIC geometry only; no real Exness data, evidence or finality is manufactured."""
from copy import deepcopy
from contextlib import redirect_stdout
from datetime import datetime,timedelta
from hashlib import sha256
from io import StringIO
from pathlib import Path
import csv,json,tempfile,unittest
from iat.historical_session_boundaries import boundary_research,package_boundary_research
from iat.session_config import compile_session_config
from iat.quality import assess_candles
from iat.chart_benchmark import read_json
from iat.pilot_preparation import prepare_pilot,file_fingerprint
from diagnostics.historical_session_boundaries import main
from test_session_v2 import synthetic_v2,window
from test_qualification_assistant import export_fixture,save

START='2026-11-12T19:00:00Z'
END='2026-11-12T23:10:00Z'


def session_fixture(*,verified=True,reopen='23:00:00'):
    c=synthetic_v2()
    schedule={'quotes':[window('00:00:00','21:58:00',0),window(reopen,'00:00:00',1)],
        'phases':[window('00:00:00','21:58:00',0,'FULL_TRADING'),window('21:58:00',reopen,0,'CLOSED'),window(reopen,'00:00:00',1,'FULL_TRADING')]}
    c['weekdays']={day:deepcopy(schedule) for day in c['weekdays']}
    if not verified:
        for k in ('quote_schedule_verified','trade_schedule_verified','holidays_verified','maintenance_verified'):c['verification'][k]=False
        c['candle_finality']['verified']=False
    return c


def observations(config,start=START,end=END):
    calendar=compile_session_config(config);a,b=datetime.fromisoformat(start.replace('Z','+00:00')),datetime.fromisoformat(end.replace('Z','+00:00'))
    return {tf:[{'timestamp':t.isoformat(),'open':100.,'high':101.,'low':99.,'close':100.} for t in calendar.expected_intervals(a,b,timedelta(minutes=m))]
            for tf,m in (('M1',1),('M5',5))}


def boundary_row(report,opening='2026-11-12T21:55:00+00:00'):
    return next(r for r in report['m5_intervals'] if r['geometry']['scheduled_open_utc']==opening)


class HistoricalBoundaryTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def run_case(self,config=None,rows=None,start=START,end=END):
        config=session_fixture() if config is None else config
        rows=observations(config,start,end) if rows is None else rows
        return boundary_research(rows,compile_session_config(config),start,end,observation_origin='SYNTHETIC_ONLY')
    def test_normal_complete_frames_use_five_m1_without_qualifying(self):
        c=synthetic_v2();r=self.run_case(c)
        self.assertEqual(r['comparison_counts']['FIVE_M1_MATCH'],50)
        self.assertEqual(r['frames']['M5']['classifications']['FULL_SESSION_BAR'],50)
        self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED');self.assertFalse(r['ordinary_inputs_emitted'])
        self.assertEqual(r['historical_validation'],'PENDING');self.assertEqual(r['historical_comparisons'],'NOT_RUN')
    def test_2158_close_and_2155_native_m5_are_geometry_not_finality(self):
        r=self.run_case();bar=boundary_row(r)
        self.assertEqual(bar['geometry']['classification'],'PARTIAL_SESSION_CLOSE')
        self.assertEqual(bar['geometry']['market_open_seconds'],180)
        self.assertEqual(bar['geometry']['scheduled_end_utc'],'2026-11-12T22:00:00+00:00')
        self.assertEqual([s['timestamp_utc'][11:16] for s in bar['m1_slots'] if s['assessment']=='CONFIGURED_OFF_QUOTE_ABSENCE'],['21:58','21:59'])
        self.assertEqual(bar['five_m1_comparison'],'NOT_COMPARED_PARTIAL_OR_UNKNOWN_SESSION')
        self.assertEqual(bar['partial_finality'],'UNESTABLISHED');self.assertIsNone(bar['ohlc_differences']);self.assertFalse(bar['ordinary_eligible'])
        self.assertEqual(r['frames']['M1']['missing_full_under_verified_declarations'],0)
        self.assertEqual(r['frames']['M5']['classifications']['PARTIAL_SESSION_CLOSE'],1)
    def test_ordinary_gate_still_rejects_partial_even_with_full_bar_finality(self):
        c=session_fixture();cal=compile_session_config(c);rows=observations(c);end=datetime.fromisoformat(END.replace('Z','+00:00'))
        quality=assess_candles(rows['M5'],'M5',end,session_calendar=cal,observed_finality=True).to_dict()
        self.assertFalse(quality['valid']);self.assertIn('PARTIAL_SESSION_CANDLE',[d['code'] for d in quality['diagnostics']])
        self.assertFalse(cal.classify_bar(datetime.fromisoformat('2026-11-12T21:55:00+00:00'),'M5',research=True,observed_finalized=True,as_of=end)['eligible_for_strategy'])
    def test_candidate_calendar_does_not_legitimize_missing_minutes(self):
        c=session_fixture(verified=False);r=self.run_case(c);bar=boundary_row(r)
        self.assertEqual(bar['geometry']['classification'],'PARTIAL_SESSION_CLOSE')
        self.assertEqual(bar['geometry']['ordinary_classification'],'UNKNOWN_SESSION')
        self.assertFalse(bar['geometry']['schedule_verified'])
        self.assertEqual(r['m1_slot_absence_counts']['MISSING_UNESTABLISHED_UNVERIFIED_CALENDAR'],2)
        self.assertNotIn('CONFIGURED_OFF_QUOTE_ABSENCE',r['m1_slot_absence_counts'])
        self.assertIsNone(r['frames']['M1']['missing_full_under_verified_declarations'])
    def test_missing_full_session_m1_is_unexpected_only_with_verified_declarations(self):
        for verified in (True,False):
            c=session_fixture(verified=verified);rows=observations(c)
            rows['M1']=[r for r in rows['M1'] if r['timestamp']!='2026-11-12T21:56:00+00:00']
            r=self.run_case(c,rows)
            if verified:self.assertEqual(r['m1_slot_absence_counts']['UNEXPECTED_MISSING_FULL_M1'],1)
            else:self.assertNotIn('UNEXPECTED_MISSING_FULL_M1',r['m1_slot_absence_counts'])
    def test_partial_open_and_crosses_break_reuse_exact_engine_labels(self):
        c=session_fixture(reopen='23:01:00');r=self.run_case(c)
        bar=boundary_row(r,'2026-11-12T23:00:00+00:00')
        self.assertEqual(bar['geometry']['classification'],'PARTIAL_SESSION_OPEN');self.assertEqual(bar['geometry']['market_open_seconds'],240)
        c=session_fixture();c['maintenance']=[{'start':'2026-11-12T21:56:00','end':'2026-11-12T21:57:00'}]
        r=self.run_case(c);self.assertEqual(boundary_row(r)['geometry']['classification'],'CROSSES_SESSION_BREAK')
    def test_unknown_and_close_only_are_distinct_from_full_trading(self):
        c=session_fixture();c['verification']['trade_schedule_verified']=False
        for schedule in c['weekdays'].values():
            schedule['phases'][-1:]=[window('23:00:00','23:01:00',0,'UNKNOWN'),window('23:01:00','23:03:00',0,'CLOSE_ONLY'),window('23:03:00','00:00:00',1,'FULL_TRADING')]
        r=self.run_case(c);self.assertGreater(r['frames']['M1']['phase_bar_counts']['UNKNOWN'],0)
        self.assertGreater(r['frames']['M1']['phase_bar_counts']['CLOSE_ONLY'],0);self.assertGreater(r['frames']['M1']['phase_bar_counts']['FULL_TRADING'],0)
        self.assertTrue(all(not g['ordinary_eligible'] for g in r['bar_geometry']['M1']))
    def test_close_only_missing_quote_is_not_missing_ordinary_trading_input(self):
        c=session_fixture()
        for schedule in c['weekdays'].values():schedule['phases'][-1:]=[window('23:00:00','23:05:00',0,'CLOSE_ONLY'),window('23:05:00','00:00:00',1,'FULL_TRADING')]
        rows=observations(c);rows['M1']=[r for r in rows['M1'] if r['timestamp']!='2026-11-12T23:01:00+00:00']
        r=self.run_case(c,rows)
        self.assertEqual(r['m1_slot_absence_counts']['MISSING_QUOTE_OBSERVATION_RESTRICTED_PHASE'],1)
        self.assertNotIn('UNEXPECTED_MISSING_FULL_M1',r['m1_slot_absence_counts'])
    def test_duplicate_out_of_order_and_conflicting_ohlc_are_not_hidden(self):
        c=session_fixture();rows=observations(c);rows['M1'].append(dict(rows['M1'][0]));r=self.run_case(c,rows)
        self.assertIn('TIMESTAMP_DUPLICATE',r['reason_codes']);self.assertIn('TIMESTAMP_OUT_OF_ORDER',r['reason_codes'])
        self.assertNotIn('FIVE_M1_MATCH',r['comparison_counts'])
        rows=observations(c);rows['M5'][0]['high']=105.;r=self.run_case(c,rows)
        self.assertEqual(r['comparison_counts']['FIVE_M1_MISMATCH'],1)
    def test_finality_unknown_does_not_invalidate_known_quote_geometry_or_become_confirmed(self):
        c=session_fixture();c['candle_finality']['verified']=False;r=self.run_case(c)
        self.assertEqual(boundary_row(r)['geometry']['classification'],'PARTIAL_SESSION_CLOSE')
        self.assertEqual(r['m1_slot_absence_counts']['CONFIGURED_OFF_QUOTE_ABSENCE'],2)
        self.assertTrue(all(x['broker_finality']=='UNESTABLISHED' for records in r['bar_geometry'].values() for x in records))
        self.assertIn('CANDLE_FINALITY_UNCERTAIN',r['calendar_state']['reason_codes'])
    def test_expiry_missing_holiday_and_maintenance_evidence_prevent_verified_absence_claims(self):
        for defect in ('expired','holidays_verified','maintenance_verified'):
            c=session_fixture()
            if defect=='expired':c['verification']['expires_at']='2026-11-12T22:00:00Z'
            else:c['verification'][defect]=False
            r=self.run_case(c)
            self.assertIsNone(r['frames']['M1']['missing_full_under_verified_declarations'])
            self.assertNotIn('CONFIGURED_OFF_QUOTE_ABSENCE',r['m1_slot_absence_counts'])
            if defect=='expired':self.assertIn('CALENDAR_EXPIRED',r['reason_codes'])
    def test_outside_coverage_and_outside_session_are_not_invented_quotes(self):
        c=session_fixture();rows=observations(c);rows['M1'].append({'timestamp':'2026-11-12T22:30:00+00:00','open':100.,'high':101.,'low':99.,'close':100.})
        r=self.run_case(c,rows);self.assertEqual(r['frames']['M1']['classifications']['OUTSIDE_SESSION'],1)
        c['coverage']['start']='2026-11-13';r=self.run_case(c,rows)
        self.assertGreater(r['frames']['M1']['classifications']['UNKNOWN_SESSION'],0)
    def test_candidate_profile_2155_geometry_is_conditional_and_profile_bytes_unchanged(self):
        path=Path('config/profiles/exness-xauusd-v2.candidate.json');before=path.read_bytes();cal=compile_session_config(json.loads(before))
        c=session_fixture();r=boundary_research(observations(c),cal,START,END,observation_origin='SYNTHETIC_ONLY')
        self.assertEqual(boundary_row(r)['geometry']['market_open_seconds'],180);self.assertFalse(boundary_row(r)['geometry']['schedule_verified'])
        self.assertEqual(path.read_bytes(),before);self.assertEqual(r['qualification'],'DATA_NOT_QUALIFIED')

    def export_source(self,config=None):
        c=session_fixture() if config is None else config;rows=observations(c)
        spec=export_fixture(self.root);s=read_json(spec)
        start=START.replace('Z','+00:00');end=END.replace('Z','+00:00');evaluate='2026-11-12T20:30:00+00:00'
        s.update(utc_range={'start':start,'end':end},evaluation={'start':evaluate,'end':end},warmup={tf:{'start':start,'end':evaluate} for tf in rows})
        for tf,bars in rows.items():
            path=self.root/s['frames'][tf]['file']
            with path.open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=['Time','Open','High','Low','Close','Ticks','Done'],lineterminator='\n');w.writeheader()
                for bar in bars:w.writerow({'Time':bar['timestamp'],'Open':bar['open'],'High':bar['high'],'Low':bar['low'],'Close':bar['close'],'Ticks':10,'Done':'true'})
        save(self.root/'calendar.json',c);s['calendar']['sha256']=sha256((self.root/'calendar.json').read_bytes()).hexdigest();save(spec,s)
        return spec,s,rows

    def test_preparation_sidecar_survives_ordinary_partial_bar_failure(self):
        spec,s,rows=self.export_source();sources={tf:self.root/s['frames'][tf]['file'] for tf in rows}
        before={tf:file_fingerprint(p) for tf,p in sources.items()}
        result=prepare_pilot(spec,sources['M1'],sources['M5'],self.root/'out',start=START,end=END,evaluation_start=s['evaluation']['start'])
        self.assertEqual(read_json(self.root/'out'/'alignment-audit.json')['status'],'BLOCKED')
        research=read_json(self.root/'out'/'session-boundary-research.json')
        self.assertEqual(boundary_row(research)['geometry']['classification'],'PARTIAL_SESSION_CLOSE')
        self.assertIn('session-boundary-research.json',result['files']);self.assertEqual(result['readiness']['qualification'],'DATA_NOT_QUALIFIED')
        self.assertEqual({tf:file_fingerprint(p) for tf,p in sources.items()},before)

    def test_explicit_new_window_avoids_partial_without_deleting_any_source_records(self):
        spec,s,rows=self.export_source();sources={tf:self.root/s['frames'][tf]['file'] for tf in rows};before={tf:p.read_bytes() for tf,p in sources.items()}
        result=prepare_pilot(spec,sources['M1'],sources['M5'],self.root/'bounded',start=START,end='2026-11-12T21:55:00Z',evaluation_start=s['evaluation']['start'])
        self.assertEqual(read_json(self.root/'bounded'/'alignment-audit.json')['status'],'PASS')
        self.assertEqual(result['readiness']['qualification'],'DATA_NOT_QUALIFIED')
        research=read_json(self.root/'bounded'/'session-boundary-research.json');self.assertEqual(research['frames']['M5']['classifications']['PARTIAL_SESSION_CLOSE'],0)
        self.assertEqual({tf:p.read_bytes() for tf,p in sources.items()},before)
        inspection=read_json(self.root/'bounded'/'source-inspection.json')
        self.assertGreater(inspection['sources']['M5']['row_count'],inspection['sources']['M5']['selected_row_count'])

    def actual_headers(self):
        config=session_fixture(verified=False);rows=observations(config);save(self.root/'research-calendar.json',config)
        for tf,bars in rows.items():
            with (self.root/(tf+'.csv')).open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=['timestamp_utc','open','high','low','close','tick_volume','spread','real_volume'],lineterminator='\n');writer.writeheader()
                for bar in bars:writer.writerow({'timestamp_utc':bar['timestamp'],**{k:bar[k] for k in ('open','high','low','close')},'tick_volume':10,'spread':20,'real_volume':0})
        return config

    def cli_args(self,out):
        return ['--m1',str(self.root/'M1.csv'),'--m5',str(self.root/'M5.csv'),'--calendar',str(self.root/'research-calendar.json'),
            '--timestamp-column','timestamp_utc','--start-utc',START,'--end-utc',END,'--report-path',str(out)]

    def test_readonly_cli_handles_reported_header_without_faking_finality_or_source_authorization(self):
        self.actual_headers();before={tf:(self.root/(tf+'.csv')).read_bytes() for tf in ('M1','M5')};path=self.root/'report.json'
        with redirect_stdout(StringIO()):self.assertEqual(main(self.cli_args(path)),3)
        report=read_json(path);self.assertEqual(report['file_observations']['price_basis'],'UNVERIFIED')
        self.assertEqual(report['file_observations']['source_permissions'],'UNVERIFIED')
        self.assertEqual(boundary_row(report)['partial_finality'],'UNESTABLISHED');self.assertEqual(report['qualification'],'DATA_NOT_QUALIFIED')
        self.assertEqual({tf:(self.root/(tf+'.csv')).read_bytes() for tf in ('M1','M5')},before)
        with redirect_stdout(StringIO()):self.assertEqual(main(self.cli_args(path)),3)
        self.assertEqual(read_json(path),report)

    def test_invalid_csv_observation_does_not_become_a_verified_missing_bar_claim(self):
        c=self.actual_headers();c['verification'].update(quote_schedule_verified=True,trade_schedule_verified=True,holidays_verified=True,maintenance_verified=True);save(self.root/'research-calendar.json',c)
        text=(self.root/'M1.csv').read_text();(self.root/'M1.csv').write_text(text.replace('2026-11-12T21:56:00+00:00','INVALID_TIMESTAMP'))
        with redirect_stdout(StringIO()):main(self.cli_args(self.root/'invalid.json'))
        report=read_json(self.root/'invalid.json');self.assertIn('CSV_OBSERVATION_INVALID',report['reason_codes'])
        self.assertIsNone(report['frames']['M1']['missing_full_under_verified_declarations'])
        self.assertNotIn('UNEXPECTED_MISSING_FULL_M1',report['m1_slot_absence_counts'])

    def test_operator_worksheet_does_not_masquerade_as_a_valid_import(self):
        from iat.qualification_assistant import validate_import
        path=Path('config/examples/historical-session-boundary.operator-worksheet.json');data=read_json(path)
        self.assertEqual(data['price_basis'],'UNKNOWN');self.assertIsNone(data['authorized_local_use_evidence'])
        self.assertIsNone(data['finality']['document']);self.assertFalse(data['execution_allowed'])
        result=validate_import(path);self.assertEqual(result['status'],'DATA_NOT_QUALIFIED');self.assertFalse(result['candidate_available'])

    def test_three_separate_partial_closes_remain_visible_in_bounded_samples(self):
        # Generic SYNTHETIC calendar; these counts are not the operator's reported dataset.
        c=session_fixture();r=self.run_case(c,start='2026-11-11T00:00:00Z',end='2026-11-14T00:00:00Z')
        partial=[b for b in r['m5_intervals'] if b['geometry']['classification']=='PARTIAL_SESSION_CLOSE']
        self.assertEqual(len(partial),3)
        self.assertEqual({b['geometry']['scheduled_open_utc'][8:10] for b in partial},{'11','12','13'})
        self.assertEqual(r['m1_slot_absence_counts']['CONFIGURED_OFF_QUOTE_ABSENCE'],6)
        self.assertLessEqual(len(r['m5_intervals']),64)

    def test_repeated_research_is_identical_and_partial_end_is_not_finality(self):
        self.assertEqual(self.run_case(),self.run_case())
        c=session_fixture();rows=observations(c)
        # A scheduled M5 can overhang this research cutoff; it is retained and never eligible.
        short={tf:[r for r in bars if r['timestamp']<'2026-11-12T21:58:00+00:00'] for tf,bars in rows.items()}
        r=self.run_case(c,short,end='2026-11-12T21:58:00Z')
        b=boundary_row(r);self.assertFalse(b['geometry']['scheduled_interval_elapsed_asof'])
        self.assertEqual(b['partial_finality'],'UNESTABLISHED');self.assertFalse(b['ordinary_eligible'])

    def test_checked_in_synthetic_audit_is_reproducible(self):
        root=Path('docs/research_audits/historical-session-boundary-synthetic-v1')
        for label,verified in (('verified-declarations',True),('unverified-candidate',False)):
            report=self.run_case(session_fixture(verified=verified))
            self.assertEqual(read_json(root/'audit.json')['cases'][label]['sha256'],report['sha256'])
            self.assertEqual(report['provenance'],'SYNTHETIC_ONLY')
            self.assertEqual(report['qualification'],'DATA_NOT_QUALIFIED')
        self.assertFalse(read_json(root/'audit.json')['real_csv_inspected'])
