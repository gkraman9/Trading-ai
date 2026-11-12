"""Synthetic offline fixtures test validation only; never serve as market data."""
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from iat.mt5_data import MarketDataError, get_closed_candles
from iat.sessions import SessionCalendar, SessionValidationError
from test_mt5_data import FakeMT5

UTC = timezone.utc
BASE = datetime(2026, 11, 12, 10, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


def at(minutes):
    return BASE + minutes * MINUTE


def calendar(windows=((0, 10), (20, 60)), symbol='XAUUSD'):
    return SessionCalendar(symbol, at(-60), at(120),
                           tuple((at(a), at(b)) for a, b in windows))


def provider(opens):
    return FakeMT5([{'time': int(opened.timestamp()), 'open': 100,
                     'high': 102, 'low': 99, 'close': 101} for opened in opens])


class SessionTests(unittest.TestCase):
    def fetch(self, opens, now, sessions=None, timeframe='M1', delay=2):
        return get_closed_candles(mt5=provider(opens), count=len(opens), now=now,
                                  timeframe=timeframe, session_calendar=sessions,
                                  max_delay_bars=delay)

    def test_direct_history_validation_rejects_unordered_or_naive_data(self):
        for opens in ([at(2), at(1), at(3)], [at(1), at(1), at(2)],
                      [at(0).replace(tzinfo=None)], None):
            with self.subTest(opens=opens), self.assertRaises(SessionValidationError):
                calendar().validate_history(opens, at(5), MINUTE, 2)

    def test_direct_history_validation_rejects_empty_or_future_data(self):
        for opens in ([], [at(1), at(2), at(3)]):
            with self.subTest(opens=opens), self.assertRaises(SessionValidationError):
                calendar().validate_history(opens, at(3), MINUTE, 2)

    def test_direct_history_validation_checks_request_and_tolerance(self):
        for now, delay in ((at(15), 2), (at(4), -1), (at(4), True)):
            with self.subTest(now=now, delay=delay), self.assertRaises(SessionValidationError):
                calendar().validate_history([at(0), at(1), at(2)], now, MINUTE, delay)

    def test_invalid_duration_uses_session_validation_error(self):
        for duration in (timedelta(0), -MINUTE, timedelta(microseconds=1), None):
            with self.subTest(duration=duration), self.assertRaises(SessionValidationError):
                calendar().validate_request('XAUUSD', at(5), duration)

    def test_malformed_window_container_uses_session_validation_error(self):
        for windows in (None, [None], [(at(0),)], [123]):
            with self.subTest(windows=windows), self.assertRaises(SessionValidationError):
                SessionCalendar('XAUUSD', at(-60), at(120), windows)

    def test_continuous_history_without_calendar(self):
        self.assertEqual(len(self.fetch([at(0), at(1), at(2)], at(3))), 3)

    def test_gap_without_calendar_is_rejected(self):
        with self.assertRaisesRegex(MarketDataError, 'gap'):
            self.fetch([at(0), at(2), at(3)], at(4))

    def test_in_session_missing_candle_is_rejected(self):
        with self.assertRaisesRegex(MarketDataError, 'Missing candle'):
            self.fetch([at(0), at(2), at(3)], at(4), calendar())

    def test_verified_break_is_not_a_gap(self):
        self.assertEqual(len(self.fetch([at(8), at(9), at(20)], at(21), calendar(), delay=0)), 3)

    def test_missing_candle_after_break_is_rejected(self):
        with self.assertRaisesRegex(MarketDataError, 'Missing candle'):
            self.fetch([at(8), at(9), at(21)], at(22), calendar())

    def test_candle_inside_break_is_rejected(self):
        with self.assertRaisesRegex(MarketDataError, 'outside a market session'):
            self.fetch([at(9), at(15), at(20)], at(21), calendar())

    def test_session_open_inclusive_close_exclusive(self):
        sessions = calendar()
        sessions.validate_request('XAUUSD', at(0), MINUTE)
        for now in (at(10), at(19), at(60)):
            with self.subTest(now=now), self.assertRaisesRegex(SessionValidationError, 'closed'):
                sessions.validate_request('XAUUSD', now, MINUTE)

    def test_closed_session_does_not_contact_mt5(self):
        fake = provider([at(7), at(8), at(9)])
        with self.assertRaisesRegex(MarketDataError, 'closed'):
            get_closed_candles(mt5=fake, now=at(15), count=3, session_calendar=calendar())
        self.assertIsNone(fake.request)

    def test_expired_future_or_wrong_symbol_calendar(self):
        for now, symbol in ((at(120), 'XAUUSD'), (at(-61), 'XAUUSD'), (at(5), 'OTHER')):
            with self.subTest(now=now, symbol=symbol), self.assertRaises(SessionValidationError):
                calendar().validate_request(symbol, now, MINUTE)

    def test_history_outside_coverage(self):
        sessions = SessionCalendar('XAUUSD', at(1), at(10), ((at(1), at(10)),))
        with self.assertRaisesRegex(MarketDataError, 'coverage'):
            self.fetch([at(0), at(1), at(2)], at(3), sessions)

    def test_freshness_counts_only_closed_session_bars(self):
        opens = [at(7), at(8), at(9)]
        # At reopening no new candle is yet closed; two minutes later two are.
        for now in (at(20), at(21), at(22)):
            with self.subTest(now=now):
                self.assertEqual(len(self.fetch(opens, now, calendar())), 3)
        with self.assertRaisesRegex(MarketDataError, 'stale'):
            self.fetch(opens, at(23), calendar())

    def test_m5_break_and_gap(self):
        self.assertEqual(len(self.fetch([at(0), at(5), at(20)], at(25), calendar(), 'M5')), 3)
        with self.assertRaisesRegex(MarketDataError, 'Missing candle'):
            self.fetch([at(0), at(5), at(25)], at(30), calendar(), 'M5')

    def test_partial_m5_session_boundary_is_unknown(self):
        with self.assertRaisesRegex(MarketDataError, 'align'):
            self.fetch([at(0), at(5), at(20)], at(25), calendar(((0, 11), (20, 60))), 'M5')

    def test_invalid_calendar_definitions(self):
        cases = (((at(10), at(0)),), ((at(0), at(15)), (at(10), at(30))),
                 ((at(20), at(30)), (at(0), at(10))), ((at(-61), at(0)),),
                 ((at(0), at(121)),))
        for windows in cases:
            with self.subTest(windows=windows), self.assertRaises(SessionValidationError):
                SessionCalendar('XAUUSD', at(-60), at(120), windows)
        with self.assertRaises(SessionValidationError):
            SessionCalendar('XAUUSD', BASE.replace(tzinfo=None), at(120), ())
        with self.assertRaises(SessionValidationError):
            SessionCalendar('XAUUSD', at(120), at(120), ())

    def test_empty_calendar_confirms_holiday_closure(self):
        with self.assertRaisesRegex(SessionValidationError, 'closed'):
            calendar(()).validate_request('XAUUSD', at(30), MINUTE)

    def test_weekend_closure_and_reopening(self):
        friday = datetime(2026, 11, 13, 20, tzinfo=UTC)
        monday = datetime(2026, 11, 16, 0, tzinfo=UTC)
        sessions = SessionCalendar('XAUUSD', friday, monday + timedelta(days=1),
                                   ((friday, friday + 3 * MINUTE),
                                    (monday, monday + timedelta(hours=1))))
        opens = [friday + MINUTE, friday + 2 * MINUTE, monday]
        self.assertEqual(len(self.fetch(opens, monday + MINUTE, sessions, delay=0)), 3)
        with self.assertRaisesRegex(SessionValidationError, 'closed'):
            sessions.validate_request('XAUUSD', friday + timedelta(days=1), MINUTE)

    def test_timezone_conversion_across_dst_uses_explicit_windows(self):
        zone = ZoneInfo('America/New_York')
        before = datetime(2026, 10, 30, 9, tzinfo=zone)
        after = datetime(2026, 11, 2, 9, tzinfo=zone)
        sessions = SessionCalendar('XAUUSD', before, after + timedelta(hours=1),
                                   ((before, before + timedelta(hours=1)),
                                    (after, after + timedelta(hours=1))))
        self.assertEqual(sessions.windows[0][0].hour, 13)
        self.assertEqual(sessions.windows[1][0].hour, 14)
        sessions.validate_request('XAUUSD', after, MINUTE)


if __name__ == '__main__':
    unittest.main()
