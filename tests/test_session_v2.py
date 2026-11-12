"""Synthetic fixtures exercise the engine; no fixture is broker verification."""
import copy
from datetime import datetime, timedelta, timezone
import unittest

from iat.session_config import compile_session_config, SessionConfigError
from iat.sessions import SessionValidationError
from iat.quality import assess_candles
from iat.mt5_data import get_candle_snapshot, MarketDataError
from test_api import NOW, ReadOnlyMT5, rates


def window(a='00:00:00', b='00:00:00', offset=1, state=None):
    value = {'open': a, 'close': b, 'close_day_offset': offset}
    if state is not None:
        value['state'] = state
    return value


def synthetic_v2():
    return {'version': 2, 'symbol': 'XAUUSD', 'timezone': 'UTC',
            'coverage': {'start': '2026-11-06', 'end': '2026-11-16'},
            'verification': {'quote_schedule_verified': True, 'trade_schedule_verified': True,
                             'holidays_verified': True, 'maintenance_verified': True,
                             'expires_at': '2026-11-16T00:00:00Z',
                             'provenance': [{'id': 'fixture', 'kind': 'SYNTHETIC_TEST',
                                             'reference': 'SYNTHETIC OFFLINE ONLY', 'captured_at': '2026-11-05T00:00:00Z'}]},
            'candle_finality': {'policy': 'MT5_POSITION_1_ELAPSED', 'verified': True},
            'weekdays': {day: {'quotes': [window()], 'phases': [window(state='FULL_TRADING')]}
                         for day in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')},
            'holidays': [], 'exceptions': {}, 'maintenance': [], 'closures': [], 'assurance_holds': []}


def bounded_day(a='09:00:30', b='21:58:00'):
    return {'quotes': [window(a, b, 0)], 'phases': [window('00:00:00', a, 0, 'CLOSED'),
             window(a, b, 0, 'FULL_TRADING'), window(b, '00:00:00', 1, 'CLOSED')]}


class V2Tests(unittest.TestCase):
    def at(self, clock):
        return datetime.fromisoformat('2026-11-12T' + clock + '+00:00')

    def classify(self, schedule, moment, timeframe='M1', **options):
        config = synthetic_v2()
        config['weekdays']['thu'] = schedule
        return compile_session_config(config).classify_bar(self.at(moment), timeframe, **options)

    def test_valid_version_load_and_permissions(self):
        calendar = compile_session_config(synthetic_v2())
        self.assertEqual(calendar.version, 2)
        permissions = calendar.permissions_at(NOW)
        self.assertTrue(permissions['broker_open_positions'])
        self.assertFalse(permissions['iat_execution_allowed'])

    def test_full_bar_finality_is_separate_from_time_geometry(self):
        calendar = compile_session_config(synthetic_v2())
        unknown = calendar.classify_bar(self.at('10:00:00'), 'M5')
        self.assertEqual(unknown['classification'], 'FULL_SESSION_BAR')
        self.assertEqual(unknown['broker_finality'], 'UNESTABLISHED')
        self.assertFalse(unknown['eligible_for_strategy'])
        known = calendar.classify_bar(self.at('10:00:00'), 'M5', observed_finalized=True, as_of=NOW)
        self.assertTrue(known['eligible_for_strategy'])
        self.assertFalse(known['iat_execution_allowed'])

    def test_partial_m1_open_and_close(self):
        schedule = bounded_day('09:00:30', '21:58:30')
        for clock, label, seconds in (('09:00:00', 'PARTIAL_SESSION_OPEN', 30),
                                       ('21:58:00', 'PARTIAL_SESSION_CLOSE', 30)):
            result = self.classify(schedule, clock, observed_finalized=True)
            self.assertEqual(result['classification'], label)
            self.assertEqual(result['market_open_seconds'], seconds)
            self.assertFalse(result['eligible_for_strategy'])

    def test_partial_m5_open_and_close_without_rounding(self):
        schedule = bounded_day('23:01:00', '23:58:00')
        self.assertEqual(self.classify(schedule, '23:00:00', 'M5')['classification'], 'PARTIAL_SESSION_OPEN')
        result = self.classify(bounded_day(), '21:55:00', 'M5', observed_finalized=True)
        self.assertEqual(result['classification'], 'PARTIAL_SESSION_CLOSE')
        self.assertEqual(result['market_open_seconds'], 180)
        self.assertEqual(result['scheduled_end_utc'], '2026-11-12T22:00:00+00:00')
        self.assertEqual(result['market_open_portions'][0]['end'], '2026-11-12T21:58:00+00:00')

    def test_crosses_maintenance_break(self):
        config = synthetic_v2()
        config['maintenance'] = [{'start': '2026-11-12T10:01:30', 'end': '2026-11-12T10:02:30'}]
        calendar = compile_session_config(config)
        result = calendar.classify_bar(self.at('10:00:00'), 'M5')
        self.assertEqual(result['classification'], 'CROSSES_SESSION_BREAK')
        self.assertEqual(result['market_open_seconds'], 240)
        self.assertEqual(calendar.phase_at(self.at('10:02:00')), 'CLOSED')

    def test_outside_and_unknown_coverage(self):
        result = self.classify(bounded_day(), '08:00:00')
        self.assertEqual(result['classification'], 'OUTSIDE_SESSION')
        calendar = compile_session_config(synthetic_v2())
        result = calendar.classify_bar(datetime(2026, 11, 20, tzinfo=timezone.utc), 'M1')
        self.assertEqual(result['classification'], 'UNKNOWN_SESSION')
        self.assertFalse(result['eligible_for_strategy'])

    def test_close_only_and_quote_only_do_not_enable_orders(self):
        for state, opening, closing in (('CLOSE_ONLY', False, True), ('QUOTE_ONLY', False, False), ('CLOSED', False, False)):
            config = synthetic_v2()
            config['weekdays']['thu'] = {'quotes': [] if state == 'CLOSED' else [window()],
                                         'phases': [window(state=state)]}
            calendar = compile_session_config(config)
            permissions = calendar.permissions_at(NOW)
            self.assertIs(permissions['broker_open_positions'], opening)
            self.assertIs(permissions['broker_close_positions'], closing)
            self.assertIs(permissions['iat_execution_allowed'], False)
            self.assertFalse(calendar.classify_bar(self.at('10:00:00'), 'M1', observed_finalized=True)['eligible_for_strategy'])

    def test_unknown_trade_phase_never_inferred_from_quotes(self):
        config = synthetic_v2()
        config['verification']['trade_schedule_verified'] = False
        config['weekdays']['thu']['phases'] = []
        calendar = compile_session_config(config)
        self.assertEqual(calendar.phase_at(NOW), 'UNKNOWN')
        self.assertIsNone(calendar.permissions_at(NOW)['broker_open_positions'])
        self.assertEqual(calendar.classify_bar(self.at('10:00:00'), 'M1')['classification'], 'UNKNOWN_SESSION')

    def test_overlapping_quote_or_trade_definitions_rejected(self):
        for kind in ('quotes', 'phases'):
            config = synthetic_v2()
            config['weekdays']['thu'][kind] *= 2
            with self.assertRaises(SessionConfigError) as raised:
                compile_session_config(config)
            self.assertEqual(raised.exception.code, 'PHASE_CONFLICT')

    def test_contradictory_quote_closed_and_trade_without_quotes_rejected(self):
        for quotes, state in (([window()], 'CLOSED'), ([], 'FULL_TRADING')):
            config = synthetic_v2()
            config['weekdays']['thu'] = {'quotes': quotes, 'phases': [window(state=state)]}
            with self.assertRaises(SessionConfigError) as raised:
                compile_session_config(config)
            self.assertEqual(raised.exception.code, 'PHASE_CONFLICT')

    def test_schema_strictness_and_unsupported_versions(self):
        for changes in ({'version': True}, {'version': 3}, {'unexpected': 1}, {'timezone': 'Wrong/Timezone'}):
            with self.subTest(changes=changes), self.assertRaises(SessionConfigError):
                compile_session_config(dict(synthetic_v2(), **changes))
        config = synthetic_v2()
        config['weekdays']['thu']['quotes'][0]['open'] = '00:00'
        with self.assertRaises(SessionConfigError):
            compile_session_config(config)

    def test_missing_evidence_and_unknown_holidays_block(self):
        config = synthetic_v2()
        config['verification']['holidays_verified'] = False
        calendar = compile_session_config(config)
        self.assertIn('HOLIDAY_COVERAGE_UNKNOWN', calendar.assurance_codes)
        with self.assertRaises(SessionValidationError):
            calendar.validate_request('XAUUSD', NOW, timedelta(minutes=1))
        config['verification']['provenance'] = []
        with self.assertRaises(SessionConfigError):
            compile_session_config(config)

    def test_expiry_and_dated_coverage(self):
        config = synthetic_v2()
        config['verification']['expires_at'] = '2026-11-12T10:00:00Z'
        calendar = compile_session_config(config)
        with self.assertRaises(SessionValidationError) as raised:
            calendar.validate_request('XAUUSD', NOW, timedelta(minutes=1))
        self.assertEqual(raised.exception.code, 'CALENDAR_EXPIRED')

    def test_holidays_close_overnight_carry_and_exception_overrides_day(self):
        config = synthetic_v2()
        config['holidays'] = ['2026-11-12']
        calendar = compile_session_config(config)
        self.assertEqual(calendar.phase_at(NOW), 'CLOSED')
        self.assertEqual(calendar.classify_bar(self.at('10:00:00'), 'M1')['classification'], 'OUTSIDE_SESSION')
        config['holidays'] = []
        config['exceptions'] = {'2026-11-12': bounded_day('10:00:00', '11:00:00')}
        calendar = compile_session_config(config)
        self.assertEqual(calendar.phase_at(self.at('09:00:00')), 'CLOSED')
        self.assertEqual(calendar.phase_at(NOW), 'FULL_TRADING')

    def test_provider_full_history_with_declared_finality(self):
        result = get_candle_snapshot(mt5=ReadOnlyMT5(rates([100] * 100)), count=100, now=NOW,
                                     session_calendar=compile_session_config(synthetic_v2()))
        self.assertTrue(result.quality.valid)
        self.assertEqual(len(result.candles), 100)

    def test_ohlc_alone_does_not_establish_finality(self):
        rows = [{'timestamp': '2026-11-12T10:%02d:00Z' % n, 'open':100,'high':102,'low':99,'close':101}
                for n in (27,28,29)]
        report = assess_candles(rows, 'M1', NOW, session_calendar=compile_session_config(synthetic_v2()))
        self.assertFalse(report.valid)
        self.assertEqual(report.diagnostics[0].code, 'CANDLE_FINALITY_UNCERTAIN')

    def test_partial_history_is_rejected_not_filtered(self):
        config = synthetic_v2()
        config['maintenance'] = [{'start':'2026-11-12T10:27:30','end':'2026-11-12T10:28:00'}]
        with self.assertRaises(MarketDataError) as raised:
            get_candle_snapshot(mt5=ReadOnlyMT5(rates([100] * 100)), count=100, now=NOW,
                                session_calendar=compile_session_config(config))
        self.assertEqual(raised.exception.code, 'PARTIAL_SESSION_CANDLE')
