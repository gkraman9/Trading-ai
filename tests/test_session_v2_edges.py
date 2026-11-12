"""Temporal/compatibility regressions use synthetic fixtures and mocked MT5."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from iat.session_config import compile_session_config, load_session_config, SessionConfigError
from iat.session_v2 import SessionCalendarV2
from iat.mt5_data import MarketDataError, get_candle_snapshot
from iat.broker_sessions import compare_broker_sessions
from iat.sessions import SessionValidationError
from main import create_app
from test_api import NOW, ReadOnlyMT5, rates
from test_session_v2 import synthetic_v2, window, bounded_day
from test_exness_profile import ForbiddenMT5

ROOT = Path(__file__).resolve().parents[1]


class V2EdgeTests(unittest.TestCase):
    def test_dst_full_days_have_23_or_25_real_hours(self):
        for start, end, offset, hours in (('2026-03-08','2026-03-09','-04:00',23),
                                          ('2026-11-01','2026-11-02','-05:00',25)):
            config = synthetic_v2()
            config['timezone'] = 'America/New_York'
            config['coverage'] = {'start': start, 'end': end}
            config['verification']['expires_at'] = end + 'T00:00:00' + offset
            config['verification']['provenance'][0]['captured_at'] = '2026-01-01T00:00:00Z'
            calendar = compile_session_config(config)
            for duration in (timedelta(minutes=1), timedelta(minutes=5)):
                expected = list(calendar.expected_opens(calendar.coverage_start, calendar.coverage_end, duration))
                self.assertEqual(len(expected), hours * 3600 / duration.total_seconds())
                self.assertEqual(len(expected), len(set(expected)))

    def test_dst_invalid_local_phase_boundaries_rejected(self):
        for start, end, opening, code in (('2026-03-08','2026-03-09','02:30:00','TIMEZONE_NONEXISTENT'),
                                          ('2026-11-01','2026-11-02','01:30:00','TIMEZONE_AMBIGUOUS')):
            config = synthetic_v2()
            config.update(timezone='America/New_York', coverage={'start':start,'end':end})
            config['verification']['expires_at'] = end + 'T06:00:00Z'
            # Expiry must stay within coverage; choose its exact UTC endpoint.
            config['verification']['expires_at'] = end + ('T04:00:00Z' if start.endswith('03-08') else 'T05:00:00Z')
            config['verification']['provenance'][0]['captured_at'] = '2026-01-01T00:00:00Z'
            config['weekdays']['sun'] = bounded_day(opening, '04:00:00')
            with self.assertRaises(SessionConfigError) as raised:
                compile_session_config(config)
            self.assertEqual(raised.exception.code, code)

    def test_overnight_transitions_cover_midnight_without_false_gap(self):
        config = synthetic_v2()
        for day in config['weekdays']:
            config['weekdays'][day] = {'quotes':[window('22:00:00','02:00:00',1)],
              'phases':[window('22:00:00','02:00:00',1,'FULL_TRADING'),window('02:00:00','22:00:00',0,'CLOSED')]}
        calendar = compile_session_config(config)
        result = calendar.classify_bar(datetime(2026,11,12,23,55,tzinfo=timezone.utc),'M5', observed_finalized=True, as_of=datetime(2026,11,13,1,tzinfo=timezone.utc))
        self.assertEqual(result['classification'], 'FULL_SESSION_BAR')
        self.assertTrue(result['eligible_for_strategy'])
        self.assertEqual(calendar.phase_at(datetime(2026,11,13,1,tzinfo=timezone.utc)), 'FULL_TRADING')

    def test_explicit_exception_day_replaces_overnight_carry(self):
        config = synthetic_v2()
        config['exceptions']['2026-11-12'] = {'quotes':[], 'phases':[window(state='CLOSED')]}
        calendar = compile_session_config(config)
        self.assertEqual(calendar.phase_at(NOW), 'CLOSED')
        self.assertFalse(any(a <= NOW < b for a,b in calendar.windows))

    def test_maintenance_priority_over_exception_and_closure(self):
        config = synthetic_v2()
        config['exceptions']['2026-11-12'] = bounded_day('08:00:00','17:00:00')
        config['closures'] = [{'start':'2026-11-12T10:00:00','end':'2026-11-12T11:00:00'}]
        config['maintenance'] = [{'start':'2026-11-12T10:15:00','end':'2026-11-12T10:45:00'}]
        calendar = compile_session_config(config)
        phase = next(p for p in calendar.phases if p.start <= NOW < p.end)
        self.assertEqual((phase.state,phase.origin), ('CLOSED','MAINTENANCE'))

    def test_conflicting_holiday_and_override_rejected(self):
        config = synthetic_v2()
        config['holidays'] = ['2026-11-12']
        config['exceptions'] = {'2026-11-12': bounded_day()}
        with self.assertRaises(SessionConfigError):
            compile_session_config(config)

    def test_gap_across_known_lunch_closure_is_not_missing(self):
        config = synthetic_v2()
        config['maintenance'] = [{'start':'2026-11-12T12:00:00','end':'2026-11-12T13:00:00'}]
        calendar = compile_session_config(config)
        openings = [datetime(2026,11,12,h,m,tzinfo=timezone.utc) for h,m in ((11,55),(13,0),(13,5))]
        calendar.validate_history(openings,datetime(2026,11,12,13,10,tzinfo=timezone.utc),
                                  timedelta(minutes=5),0, observed_finality=True)
        with self.assertRaises(SessionValidationError) as raised:
            calendar.validate_history([openings[0],openings[2],openings[2]+timedelta(minutes=5)],
                                       datetime(2026,11,12,13,20,tzinfo=timezone.utc),timedelta(minutes=5),0, observed_finality=True)
        self.assertEqual(raised.exception.code, 'UNEXPECTED_MISSING_BARS')

    def test_full_quote_bar_crossing_restricted_phase_is_not_strategy_input(self):
        config = synthetic_v2()
        config['weekdays']['thu']['phases'] = [window('00:00:00','10:02:00',0,'FULL_TRADING'),
                                               window('10:02:00','00:00:00',1,'CLOSE_ONLY')]
        calendar = compile_session_config(config)
        result = calendar.classify_bar(datetime(2026,11,12,10,tzinfo=timezone.utc),'M5', observed_finalized=True)
        self.assertEqual(result['classification'], 'FULL_SESSION_BAR')
        self.assertFalse(result['eligible_for_strategy'])
        self.assertIs(result['broker_open_positions'],False)
        self.assertIs(result['broker_close_positions'],True)
        self.assertIs(result['iat_execution_allowed'],False)

    def test_known_quotes_do_not_infer_unknown_broker_permission(self):
        config = synthetic_v2()
        config['verification']['trade_schedule_verified'] = False
        config['weekdays']['thu']['phases'] = []
        calendar = compile_session_config(config)
        state = calendar.permissions_at(NOW)
        self.assertIs(state['market_data_expected'],True)
        self.assertIsNone(state['broker_open_positions'])
        self.assertIs(state['iat_execution_allowed'],False)

    def test_partial_bar_never_gets_finality_from_elapsed_contract(self):
        config = synthetic_v2()
        config['weekdays']['thu'] = bounded_day()
        result = compile_session_config(config).classify_bar(datetime(2026,11,12,21,55,tzinfo=timezone.utc),
                                                            'M5',observed_finalized=True)
        self.assertEqual(result['broker_finality'], 'UNESTABLISHED')

    def test_v2_provider_duplicate_missing_stale_and_clock_regression(self):
        for defect,code in (('duplicate','TIMESTAMP_DUPLICATE'),('missing','UNEXPECTED_MISSING_BARS'),
                            ('stale','DATA_STALE'),('clock','CLOCK_MOVED_BACKWARD')):
            data = rates([100]*100)
            if defect == 'duplicate': data[1]['time'] = data[0]['time']
            if defect == 'missing': data[0]['time'] -= 60
            if defect == 'stale':
                for row in data: row['time'] -= 3600
            options = {'clock':Mock(side_effect=[NOW,NOW-timedelta(seconds=1)])} if defect=='clock' else {'now':NOW}
            with self.subTest(defect=defect),self.assertRaises(MarketDataError) as raised:
                get_candle_snapshot(mt5=ReadOnlyMT5(data),count=100,session_calendar=compile_session_config(synthetic_v2()),**options)
            self.assertEqual(raised.exception.code,code)

    def test_api_preserves_existing_fields_and_adds_v2_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'v2.json';path.write_text(json.dumps(synthetic_v2()))
            app=create_app(session_config_path=path,mt5=ReadOnlyMT5(rates([100]*100)),clock=lambda:NOW)
            response=app.test_client().get('/analyze?symbol=XAUUSD&timeframe=1m')
            self.assertEqual(response.status_code,200)
            body=response.get_json()
            self.assertEqual(body['signal'],'WAIT');self.assertIs(body['execution_allowed'],False)
            self.assertEqual(body['timeframe'],'1m')
            self.assertTrue(body['quality']['valid'])
            self.assertEqual(body['session_v2']['last_bar']['classification'],'FULL_SESSION_BAR')
            self.assertFalse(body['session_v2']['permissions']['iat_execution_allowed'])

    def test_v2_expired_api_returns_wait_and_explanation(self):
        config=synthetic_v2();config['verification']['expires_at']='2026-11-12T09:00:00Z'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'v2.json';path.write_text(json.dumps(config))
            response=create_app(session_config_path=path,mt5=ForbiddenMT5(),clock=lambda:NOW).test_client().get('/analyze?symbol=XAUUSD&timeframe=M1')
            body=response.get_json();self.assertEqual(response.status_code,503)
            self.assertEqual(body['quality']['diagnostics'][0]['code'],'CALENDAR_EXPIRED')
            self.assertIsNone(body['session_v2']['permissions']['broker_open_positions'])
            self.assertIs(body['execution_allowed'],False)

    def test_exness_v2_keeps_exact_quotes_seconds_unknown_and_holds(self):
        path=ROOT/'config/profiles/exness-xauusd-v2.candidate.json'
        config=json.loads(path.read_text());calendar=load_session_config(path)
        self.assertTrue(calendar.assurance_codes)
        self.assertFalse(calendar.finality_verified)
        self.assertEqual(config['weekdays']['sun']['quotes'][0]['open'],'23:01:00')
        self.assertEqual(config['weekdays']['thu']['quotes'][0]['close'],'21:58:00')
        self.assertEqual(calendar.phase_at(datetime(2026,11,8,23,1,15,tzinfo=timezone.utc)),'UNKNOWN')
        self.assertEqual(calendar.phase_at(datetime(2026,11,8,23,1,30,tzinfo=timezone.utc)),'CLOSE_ONLY')
        self.assertEqual(calendar.phase_at(datetime(2026,11,12,23,0,tzinfo=timezone.utc)),'UNKNOWN')
        self.assertEqual(calendar.phase_at(datetime(2026,11,12,23,0,30,tzinfo=timezone.utc)),'CLOSE_ONLY')
        self.assertEqual(calendar.classify_bar(datetime(2026,11,12,21,55,tzinfo=timezone.utc),'M5',research=True)['classification'],'PARTIAL_SESSION_CLOSE')
        with self.assertRaises(SessionValidationError): calendar.validate_request('XAUUSD',NOW,timedelta(minutes=1))

    def test_classifier_needs_current_asof_for_ordinary_eligibility(self):
        calendar=compile_session_config(synthetic_v2())
        opened=datetime(2026,11,12,10,tzinfo=timezone.utc)
        self.assertFalse(calendar.classify_bar(opened,'M1',observed_finalized=True)['eligible_for_strategy'])
        self.assertFalse(calendar.classify_bar(opened,'M1',observed_finalized=True,as_of=opened)['eligible_for_strategy'])
        self.assertFalse(calendar.classify_bar(opened,'M1',observed_finalized=True,as_of=calendar.expires_at)['eligible_for_strategy'])
        self.assertTrue(calendar.classify_bar(opened,'M1',observed_finalized=True,as_of=NOW)['eligible_for_strategy'])

    def test_unknown_coverage_does_not_claim_zero_market_open_seconds(self):
        calendar=compile_session_config(synthetic_v2())
        result=calendar.classify_bar(datetime(2027,1,1,tzinfo=timezone.utc),'M5')
        self.assertIsNone(result['market_open_seconds'])
        self.assertEqual(result['classification'],'UNKNOWN_SESSION')

    def test_unsupported_duration_rejected_and_missing_verified_phase_coverage_rejected(self):
        calendar=compile_session_config(synthetic_v2())
        with self.assertRaises(SessionValidationError):calendar.validate_request('XAUUSD',NOW,timedelta(minutes=2))
        config=synthetic_v2();config['weekdays']['thu']['phases']=[]
        with self.assertRaises(SessionConfigError) as raised:compile_session_config(config)
        self.assertEqual(raised.exception.code,'SESSION_PHASE_UNKNOWN')

    def test_later_exception_overrides_previous_overnight_exception(self):
        config=synthetic_v2()
        config['exceptions']['2026-11-12']={'quotes':[window('22:00:00','02:00:00',1)],
           'phases':[window('00:00:00','22:00:00',0,'CLOSED'),window('22:00:00','02:00:00',1,'FULL_TRADING')]}
        config['exceptions']['2026-11-13']={'quotes':[],'phases':[window(state='CLOSED')]}
        calendar=compile_session_config(config)
        self.assertEqual(calendar.phase_at(datetime(2026,11,13,1,tzinfo=timezone.utc)),'CLOSED')
        self.assertEqual(calendar.phase_at(datetime(2026,11,12,23,tzinfo=timezone.utc)),'FULL_TRADING')

    def test_expired_phase_metadata_cannot_match_as_current(self):
        config=synthetic_v2();metadata_config=copy.deepcopy(config)
        metadata_config['verification']['expires_at']='2026-11-12T10:00:00Z'
        payload={'version':2,'kind':'PHASES_V2','symbol':'XAUUSD','collected_at_utc':'2026-11-12T09:00:00Z','calendar':metadata_config}
        result=compare_broker_sessions(object(),config,compile_session_config(config),payload,now=NOW)
        self.assertEqual(result['comparison'],'INVALID')

    def test_schema_and_synthetic_example_load(self):
        self.assertIsInstance(load_session_config(ROOT/'config/examples/session-v2.synthetic.json'),SessionCalendarV2)
        schema=json.loads((ROOT/'config/session-calendar-v2.schema.json').read_text())
        self.assertEqual(schema['properties']['version']['const'],2)

    def test_v2_phase_metadata_comparison_and_coarse_uncertainty(self):
        config=synthetic_v2();calendar=compile_session_config(config)
        metadata={'version':2,'kind':'PHASES_V2','symbol':'XAUUSD','collected_at_utc':NOW.isoformat(),'calendar':copy.deepcopy(config)}
        result=compare_broker_sessions(object(),config,calendar,metadata,now=NOW)
        self.assertEqual(result['comparison'],'MATCH')
        metadata['calendar']['weekdays']['thu']['phases']=[window(state='CLOSE_ONLY')]
        result=compare_broker_sessions(object(),config,calendar,metadata,now=NOW)
        self.assertEqual(result['comparison'],'MISMATCH')
        coarse={'version':1,'kind':'DATED','symbol':'XAUUSD','collected_at_utc':NOW.isoformat(),
                'coverage_start':calendar.coverage_start.isoformat(),'coverage_end':calendar.coverage_end.isoformat(),
                'complete':True,'windows':[{'start':a.isoformat(),'end':b.isoformat()} for a,b in calendar.windows]}
        result=compare_broker_sessions(object(),config,calendar,coarse,now=NOW)
        self.assertEqual(result['comparison'],'UNCERTAIN')
        self.assertIn('BROKER_PHASE_METADATA_UNVERIFIED',result['codes'])
