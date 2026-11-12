"""Illustrative schedules only: no fixture represents verified broker hours."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from iat.session_config import SessionConfigError, compile_session_config, load_session_config
from iat.sessions import SessionValidationError


def window(opened='08:00', closed='12:00', offset=0):
    return {'open': opened, 'close': closed, 'close_day_offset': offset}


def fixture():
    return {
        'version': 1, 'symbol': 'XAUUSD', 'timezone': 'UTC',
        'coverage': {'start': '2026-11-09', 'end': '2026-11-16'},
        'verification': {'source': 'OFFLINE TEST FIXTURE ONLY', 'verified_at': '2026-11-01T00:00:00Z'},
        'weekdays': {key: [window(), window('13:00', '17:00')] if key not in ('sat', 'sun') else []
                     for key in ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')},
        'holidays': [], 'exceptions': {}, 'closures': [],
    }


class ConfigTests(unittest.TestCase):
    def assert_open(self, calendar, value):
        calendar.validate_request('XAUUSD', datetime.fromisoformat(value), timedelta(minutes=1))

    def assert_closed(self, calendar, value):
        with self.assertRaisesRegex(SessionValidationError, 'closed'):
            self.assert_open(calendar, value)

    def test_weekdays_breaks_and_weekends(self):
        calendar = compile_session_config(fixture())
        self.assert_open(calendar, '2026-11-12T10:00:00+00:00')
        for value in ('2026-11-12T12:30:00+00:00', '2026-11-14T10:00:00+00:00',
                      '2026-11-15T10:00:00+00:00'):
            self.assert_closed(calendar, value)

    def test_holiday_removes_all_sessions(self):
        config = fixture()
        config['holidays'] = ['2026-11-12']
        self.assert_closed(compile_session_config(config), '2026-11-12T10:00:00+00:00')

    def test_exception_overrides_daily_schedule(self):
        config = fixture()
        config['exceptions'] = {'2026-11-12': [window('10:00', '11:00')],
                                '2026-11-14': [window('08:00', '10:00')]}
        calendar = compile_session_config(config)
        self.assert_closed(calendar, '2026-11-12T09:00:00+00:00')
        self.assert_open(calendar, '2026-11-12T10:30:00+00:00')
        self.assert_open(calendar, '2026-11-14T09:00:00+00:00')

    def test_empty_exception_closes_start_day(self):
        config = fixture()
        config['exceptions'] = {'2026-11-12': []}
        self.assert_closed(compile_session_config(config), '2026-11-12T10:00:00+00:00')

    def test_exceptional_partial_and_multiday_closures(self):
        config = fixture()
        config['closures'] = [{'start': '2026-11-12T09:00', 'end': '2026-11-12T10:00'},
                              {'start': '2026-11-12T16:00', 'end': '2026-11-13T10:00'}]
        calendar = compile_session_config(config)
        self.assert_closed(calendar, '2026-11-12T09:30:00+00:00')
        self.assert_closed(calendar, '2026-11-13T09:00:00+00:00')
        self.assert_open(calendar, '2026-11-13T10:00:00+00:00')

    def test_overnight_and_holiday_carry_in(self):
        config = fixture()
        config['weekdays'] = {key: [window('22:00', '06:00', 1)] for key in config['weekdays']}
        config['holidays'] = ['2026-11-12']
        calendar = compile_session_config(config)
        self.assert_open(calendar, '2026-11-09T01:00:00+00:00')
        self.assert_closed(calendar, '2026-11-12T01:00:00+00:00')
        self.assert_closed(calendar, '2026-11-12T23:00:00+00:00')
        self.assert_open(calendar, '2026-11-13T01:00:00+00:00')

    def dst_config(self, start, end, opening='00:00', closing='04:00'):
        config = fixture()
        config.update(timezone='America/New_York', coverage={'start': start, 'end': end})
        config['weekdays'] = {key: [window(opening, closing)] for key in config['weekdays']}
        return config

    def test_utc_ohlc_continuity_across_both_dst_transitions(self):
        from iat.quality import assess_candles
        for start, end in (('2026-03-08', '2026-03-09'), ('2026-11-01', '2026-11-02')):
            calendar = compile_session_config(self.dst_config(start, end))
            opened, closed = calendar.windows[0]
            for timeframe, duration in (('M1', timedelta(minutes=1)), ('M5', timedelta(minutes=5))):
                now = closed - timedelta(seconds=30)
                data = [{'timestamp': value.isoformat(), 'open': 100, 'high': 102,
                         'low': 99, 'close': 101}
                        for value in calendar.expected_opens(opened, now - duration, duration)]
                with self.subTest(start=start, timeframe=timeframe):
                    self.assertTrue(assess_candles(data, timeframe, now, session_calendar=calendar,
                                                  max_delay_bars=0).valid)

    def test_spring_transition_continuous_session(self):
        calendar = compile_session_config(self.dst_config('2026-03-08', '2026-03-09'))
        self.assertEqual(calendar.windows[0][1] - calendar.windows[0][0], timedelta(hours=3))

    def test_fall_transition_continuous_session(self):
        calendar = compile_session_config(self.dst_config('2026-11-01', '2026-11-02'))
        self.assertEqual(calendar.windows[0][1] - calendar.windows[0][0], timedelta(hours=5))

    def test_irrelevant_previous_day_dst_boundary_is_not_compiled(self):
        calendar = compile_session_config(self.dst_config('2026-11-02', '2026-11-03', '01:30', '04:00'))
        self.assertEqual(len(calendar.windows), 1)

    def test_nonexistent_spring_boundary_rejected(self):
        with self.assertRaises(SessionConfigError) as raised:
            compile_session_config(self.dst_config('2026-03-08', '2026-03-09', '02:30', '04:00'))
        self.assertEqual(raised.exception.code, 'SESSION_TIME_NONEXISTENT')

    def test_ambiguous_fall_boundary_rejected(self):
        with self.assertRaises(SessionConfigError) as raised:
            compile_session_config(self.dst_config('2026-11-01', '2026-11-02', '01:30', '04:00'))
        self.assertEqual(raised.exception.code, 'SESSION_TIME_AMBIGUOUS')

    def test_invalid_top_level_types_versions_and_unknown_fields(self):
        for change in ({'version': True}, {'version': 2}, {'timezone': 'Invalid/Zone'},
                       {'timezone': 1}, {'symbol': ''}, {'symbol': 'XAU USD'}, {'unknown': 1},
                       {'holidays': None}, {'exceptions': []}, {'closures': {}}):
            with self.subTest(change=change), self.assertRaises(SessionConfigError):
                compile_session_config(dict(fixture(), **change))
        for config in (None, [], {}, {'version': 1}):
            with self.subTest(config=config), self.assertRaises(SessionConfigError):
                compile_session_config(config)

    def test_required_fields_and_nested_unknown_fields(self):
        for key in fixture():
            config = fixture()
            del config[key]
            with self.subTest(missing=key), self.assertRaises(SessionConfigError):
                compile_session_config(config)
        for key in ('coverage', 'verification', 'weekdays'):
            config = fixture()
            config[key]['unknown'] = 1
            with self.subTest(unknown=key), self.assertRaises(SessionConfigError):
                compile_session_config(config)

    def test_bad_coverage(self):
        for coverage in ({'start': '2026-11-16', 'end': '2026-11-09'},
                         {'start': '2026-11-09', 'end': '2026-11-09'},
                         {'start': '2026-11-09', 'end': '2028-11-09'},
                         {'start': '2026-99-09', 'end': '2026-11-16'}):
            with self.subTest(coverage=coverage), self.assertRaises(SessionConfigError):
                compile_session_config(dict(fixture(), coverage=coverage))

    def test_verification_metadata_required_and_aware(self):
        for metadata in ({'source': '', 'verified_at': '2026-11-01T00:00:00Z'},
                         {'source': 'fixture', 'verified_at': '2026-11-01T00:00:00'},
                         {'source': 'fixture', 'verified_at': 1}):
            with self.subTest(metadata=metadata), self.assertRaises(SessionConfigError):
                compile_session_config(dict(fixture(), verification=metadata))

    def test_invalid_windows_and_overlap(self):
        for specs in ([window('12:00', '08:00')], [window(offset=True)],
                      [window('25:00', '12:00')], [window('08:00', '09:00', 1)],
                      [dict(window(), unknown=1)], [window(), window('10:00', '14:00')],
                      [window()] * 9, None):
            config = fixture()
            config['weekdays']['mon'] = specs
            with self.subTest(specs=specs), self.assertRaises(SessionConfigError):
                compile_session_config(config)

    def test_conflicting_duplicate_and_out_of_range_dates(self):
        for changes in ({'holidays': ['2026-11-12', '2026-11-12']},
                        {'holidays': ['2026-11-12'], 'exceptions': {'2026-11-12': []}},
                        {'holidays': ['2026-11-30']}, {'exceptions': {'2026-11-30': []}}):
            with self.subTest(changes=changes), self.assertRaises(SessionConfigError):
                compile_session_config(dict(fixture(), **changes))

    def test_invalid_closures(self):
        for closure in ({'start': '2026-11-12T10:00', 'end': '2026-11-12T09:00'},
                        {'start': '2026-11-08T10:00', 'end': '2026-11-12T09:00'},
                        {'start': '2026-11-12T10:00Z', 'end': '2026-11-12T11:00'}, {}):
            with self.subTest(closure=closure), self.assertRaises(SessionConfigError):
                compile_session_config(dict(fixture(), closures=[closure]))

    def test_file_loader_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            path.write_text(json.dumps(fixture()))
            self.assertEqual(load_session_config(path).symbol, 'XAUUSD')
            for raw in ('{"version":1,"version":1}', '{"value":NaN}', '[', '\ud800'):
                path.write_bytes(raw.encode('utf-8', errors='surrogatepass'))
                with self.subTest(raw=repr(raw)), self.assertRaises(SessionConfigError):
                    load_session_config(path)
            path.write_bytes(b' ' * (1024 * 1024 + 1))
            with self.assertRaises(SessionConfigError):
                load_session_config(path)
            with self.assertRaises(SessionConfigError):
                load_session_config(Path(directory) / 'missing.json')
