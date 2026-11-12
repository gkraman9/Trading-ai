"""Quality diagnostics from offline fixtures, with no price-data fallback."""
import unittest
from datetime import timedelta

from iat.mt5_data import MarketDataError, get_candle_snapshot
from iat.quality import ClockGuard, ClockValidationError, assess_candles
from iat.sessions import SessionCalendar
from test_mt5_data import FakeMT5, NOW, make_rates


def rows():
    return [{'timestamp': '2026-11-12T10:%02d:00+00:00' % minute,
             'open': 100, 'high': 102, 'low': 99, 'close': 101} for minute in (27, 28, 29)]


def calendar():
    start, end = NOW.replace(hour=0, minute=0, second=0), NOW.replace(hour=23, minute=0, second=0)
    return SessionCalendar('XAUUSD', start, end, ((start, end),))


class QualityTests(unittest.TestCase):
    def report(self, data=None, **options):
        return assess_candles(rows() if data is None else data, 'M1', NOW,
                               session_calendar=calendar(), **options)

    def assert_code(self, report, code, severity='ERROR', valid=False):
        self.assertIs(report.valid, valid)
        self.assertIn((code, severity), [(d.code, d.severity) for d in report.diagnostics])
        encoded = report.to_dict()
        self.assertEqual(set(encoded), {'valid', 'diagnostics'})
        for diagnostic in encoded['diagnostics']:
            self.assertEqual(set(diagnostic), {'code', 'severity', 'message'})

    def test_clock_guard_recovers_only_when_time_catches_up(self):
        from unittest.mock import Mock
        guard = ClockGuard(Mock(side_effect=[NOW, NOW - timedelta(seconds=1), NOW]))
        self.assertEqual(guard(), NOW)
        with self.assertRaises(ClockValidationError) as raised:
            guard()
        self.assertEqual(raised.exception.report.diagnostics[0].code, 'CLOCK_MOVED_BACKWARD')
        self.assertEqual(guard(), NOW)

    def test_clock_guard_rejects_missing_or_naive_time(self):
        for source in (lambda: NOW.replace(tzinfo=None), lambda: None):
            with self.assertRaises(ClockValidationError) as raised:
                ClockGuard(source)()
            self.assertEqual(raised.exception.report.diagnostics[0].code, 'CLOCK_UNAVAILABLE')

    def test_m5_validation_and_alignment(self):
        data = rows()
        for row, minute in zip(data, (15, 20, 25)):
            row['timestamp'] = '2026-11-12T10:%02d:00Z' % minute
        self.assert_code(assess_candles(data, 'M5', NOW, session_calendar=calendar()), 'DATA_VALID', 'INFO', True)
        data[0]['timestamp'] = '2026-11-12T10:16:00Z'
        self.assert_code(assess_candles(data, 'M5', NOW, session_calendar=calendar()), 'TIMEFRAME_MISALIGNED')

    def test_valid(self):
        self.assert_code(self.report(), 'DATA_VALID', 'INFO', True)

    def test_duplicate(self):
        data = rows()
        data[1]['timestamp'] = data[0]['timestamp']
        self.assert_code(self.report(data), 'TIMESTAMP_DUPLICATE')

    def test_out_of_order(self):
        self.assert_code(self.report(rows()[::-1]), 'TIMESTAMP_OUT_OF_ORDER')

    def test_malformed_ohlc(self):
        for value in (float('nan'), float('inf'), True, -1, 1000):
            data = rows()
            data[0]['low'] = value
            with self.subTest(value=value):
                self.assert_code(self.report(data), 'OHLC_MALFORMED')

    def test_malformed_timestamp(self):
        for value in ('bad', '2026-11-12T10:27:00', None):
            data = rows()
            data[0]['timestamp'] = value
            with self.subTest(value=value):
                self.assert_code(self.report(data), 'TIMESTAMP_MALFORMED')

    def test_alignment(self):
        data = rows()
        data[0]['timestamp'] = '2026-11-12T10:27:01Z'
        self.assert_code(self.report(data), 'TIMEFRAME_MISALIGNED')

    def test_forming_and_future_bars(self):
        for value in ('2026-11-12T10:30:00Z', '2026-11-12T10:31:00Z'):
            data = rows()
            data[-1]['timestamp'] = value
            with self.subTest(value=value):
                self.assert_code(self.report(data), 'BAR_UNCLOSED')

    def test_missing_bar(self):
        data = rows()
        data[0]['timestamp'] = '2026-11-12T10:26:00Z'
        self.assert_code(self.report(data), 'CANDLES_MISSING')

    def test_stale(self):
        self.assert_code(assess_candles(rows(), 'M1', NOW + timedelta(minutes=4),
                         session_calendar=calendar()), 'DATA_STALE')

    def test_backward_clock(self):
        self.assert_code(self.report(request_time=NOW + timedelta(seconds=1)), 'CLOCK_MOVED_BACKWARD')

    def test_recent_missing_within_tolerance_warns(self):
        report = assess_candles(rows(), 'M1', NOW + timedelta(minutes=1), session_calendar=calendar())
        self.assert_code(report, 'RECENT_BARS_MISSING', 'WARNING', True)

    def test_closed_and_unknown_coverage(self):
        for sessions, code in ((SessionCalendar('XAUUSD', calendar().coverage_start,
                                calendar().coverage_end, ()), 'SESSION_CLOSED'),
                               (SessionCalendar('XAUUSD', NOW + timedelta(hours=1),
                                NOW + timedelta(hours=2), ()), 'SESSION_COVERAGE_UNKNOWN')):
            self.assert_code(assess_candles(rows(), 'M1', NOW, session_calendar=sessions), code,
                             'INFO' if code == 'SESSION_CLOSED' else 'ERROR')

    def test_valid_session_closure_has_information_diagnostic(self):
        data = rows()
        data[0]['timestamp'] = '2026-11-12T10:25:00Z'
        data[1]['timestamp'] = '2026-11-12T10:26:00Z'
        sessions = SessionCalendar('XAUUSD', calendar().coverage_start, calendar().coverage_end,
                   ((calendar().coverage_start, NOW.replace(minute=27, second=0)),
                    (NOW.replace(minute=29, second=0), calendar().coverage_end)))
        self.assert_code(assess_candles(data, 'M1', NOW, session_calendar=sessions),
                         'SESSION_CLOSURE_SKIPPED', 'INFO', True)

    def test_bar_inside_closure(self):
        sessions = SessionCalendar('XAUUSD', calendar().coverage_start, calendar().coverage_end,
                   ((calendar().coverage_start, NOW.replace(minute=28, second=0)),
                    (NOW.replace(minute=29, second=0), calendar().coverage_end)))
        self.assert_code(assess_candles(rows(), 'M1', NOW, session_calendar=sessions), 'BAR_OUTSIDE_SESSION')

    def test_unverified_gap(self):
        data = rows()
        data[0]['timestamp'] = '2026-11-12T10:26:00Z'
        self.assert_code(assess_candles(data, 'M1', NOW), 'GAP_UNVERIFIED')

    def test_bad_count_policy_or_unknown_shape_fail_closed(self):
        self.assert_code(self.report([]), 'HISTORY_INCOMPLETE')
        self.assert_code(self.report(expected_count=100), 'HISTORY_INCOMPLETE')
        self.assert_code(self.report(max_delay_bars=True), 'QUALITY_POLICY_INVALID')
        self.assert_code(self.report(123), 'QUALITY_UNESTABLISHED')

    def test_unexpected_container_errors_have_sanitized_diagnostics(self):
        class BrokenContainer:
            def __len__(self):
                raise OSError('private-container-error')
        with self.assertRaises(MarketDataError) as raised:
            get_candle_snapshot(mt5=FakeMT5(BrokenContainer()), now=NOW, count=3)
        self.assertEqual(raised.exception.code, 'HISTORY_MALFORMED')
        self.assertNotIn('private-container-error', str(raised.exception.report.to_dict()))

    def test_unexpected_row_errors_have_sanitized_diagnostics(self):
        class BrokenRow:
            def __getitem__(self, key):
                raise RuntimeError('private-row-error')
        with self.assertRaises(MarketDataError) as raised:
            get_candle_snapshot(mt5=FakeMT5([BrokenRow()] * 3), now=NOW, count=3)
        self.assertEqual(raised.exception.code, 'TIMESTAMP_MALFORMED')
        self.assertNotIn('private-row-error', str(raised.exception.report.to_dict()))

    def test_provider_diagnostic_codes(self):
        for fake, code in ((FakeMT5(None), 'HISTORY_INCOMPLETE'),
                           (FakeMT5([], connected=False), 'PROVIDER_DISCONNECTED'),
                           (FakeMT5(123), 'HISTORY_MALFORMED')):
            with self.subTest(code=code), self.assertRaises(MarketDataError) as raised:
                get_candle_snapshot(mt5=fake, now=NOW, count=3)
            self.assertEqual(raised.exception.code, code)

    def test_adapter_exception_cannot_leak_domain_error_message(self):
        class Broken(FakeMT5):
            def copy_rates_from_pos(self, *args):
                raise MarketDataError('private-provider-details')
        with self.assertRaises(MarketDataError) as raised:
            get_candle_snapshot(mt5=Broken([]), now=NOW, count=3)
        self.assertEqual(raised.exception.code, 'PROVIDER_FAILURE')
        self.assertNotIn('private-provider-details', str(raised.exception.report.to_dict()))

    def test_raw_provider_timestamp_and_price_codes(self):
        for field, value, code in (('time', 1.5, 'TIMESTAMP_MALFORMED'),
                                   ('time', make_rates()[0]['time'] + 1, 'TIMEFRAME_MISALIGNED'),
                                   ('low', True, 'OHLC_MALFORMED')):
            data = make_rates()
            data[0][field] = value
            with self.subTest(field=field, code=code), self.assertRaises(MarketDataError) as raised:
                get_candle_snapshot(mt5=FakeMT5(data), now=NOW, count=3)
            self.assertEqual(raised.exception.code, code)

    def test_snapshot_retains_report_and_original_values(self):
        snapshot = get_candle_snapshot(mt5=FakeMT5(make_rates()), now=NOW, count=3,
                                       session_calendar=calendar())
        self.assertTrue(snapshot.quality.valid)
        self.assertEqual(snapshot.candles[0]['close'], 101)
