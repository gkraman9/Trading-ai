"""Offline HTTP tests through the real closed-candle validation pipeline."""
import importlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from main import create_app
from iat.sessions import SessionCalendar
from decision import get_signal
from reasoning import explain

NOW = datetime(2026, 11, 12, 10, 30, 30, tzinfo=timezone.utc)


def rates(closes, period=60, last_open=None):
    last_open = last_open or NOW.replace(second=0) - timedelta(seconds=period)
    return [{"time": int((last_open - timedelta(seconds=period * (len(closes) - i - 1))).timestamp()),
             "open": c, "high": c + 1, "low": c - 1, "close": c}
            for i, c in enumerate(closes)]


class ReadOnlyMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5

    def __init__(self, data, connected=True):
        self.data = data
        self.connected = connected
        self.calls = []

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected)

    def copy_rates_from_pos(self, *args):
        self.calls.append(args)
        return self.data
    # No login, initialize, or order methods: attempted use fails the tests.


class APITests(unittest.TestCase):
    def client(self, provider):
        start = NOW - timedelta(days=1, seconds=30)
        end = NOW + timedelta(days=1, seconds=-30)
        calendars = {symbol: SessionCalendar(symbol, start, end, ((start, end),))
                     for symbol in ("XAUUSD", "XAUUSDm")}
        return create_app(mt5=provider, clock=lambda: NOW,
                          session_calendars=calendars).test_client()

    def assert_safe(self, response, status):
        self.assertEqual(response.status_code, status)
        body = response.get_json()
        self.assertEqual(body["signal"], "WAIT")
        self.assertIs(body["execution_allowed"], False)
        self.assertEqual(body["mode"], "READ_ONLY_SHADOW")
        self.assertIsInstance(body["reasoning"], list)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        if status != 200:
            self.assertEqual(body["market_state"], "UNKNOWN")
            self.assertIsNone(body["last_closed_candle"])
        return body

    def test_provider_ohlc_changes_market_state_but_never_signal(self):
        cases = ((list(range(100, 200)), "BULLISH"),
                 (list(range(200, 100, -1)), "BEARISH"),
                 ([100] * 100, "RANGE"))
        for closes, state in cases:
            with self.subTest(state=state):
                provider = ReadOnlyMT5(rates(closes))
                response = self.client(provider).get('/analyze?symbol=XAUUSDm&timeframe=M1')
                body = self.assert_safe(response, 200)
                self.assertEqual(body["market_state"], state)
                self.assertEqual(body["symbol"], "XAUUSDm")
                self.assertEqual(body["timeframe"], "M1")
                self.assertEqual(body["data_source"], "MT5")
                self.assertEqual(body["last_closed_candle"], "2026-11-12T10:29:00+00:00")
                self.assertEqual(provider.calls, [("XAUUSDm", 1, 1, 100)])

    def test_m5_alias_preserves_existing_timeframe_field(self):
        provider = ReadOnlyMT5(rates([100] * 100, period=300))
        body = self.assert_safe(self.client(provider).get('/analyze?symbol=XAUUSD&timeframe=5m'), 200)
        self.assertEqual(body["timeframe"], "5m")
        self.assertEqual(body["data_timeframe"], "M5")
        self.assertEqual(provider.calls, [("XAUUSD", 5, 1, 100)])

    def test_invalid_requests_do_not_fetch(self):
        provider = ReadOnlyMT5([])
        for query in ('', '?symbol=XAUUSD', '?timeframe=M1',
                      '?symbol=&timeframe=M1', '?symbol=XAUUSD&timeframe=H1',
                      '?symbol=XAU%20USD&timeframe=M1',
                      '?symbol=XAUUSD&symbol=OTHER&timeframe=M1',
                      '?symbol=XAUUSD&timeframe=M1&timeframe=M5'):
            with self.subTest(query=query):
                body = self.assert_safe(self.client(provider).get('/analyze' + query), 400)
                self.assertEqual(body['error'], 'INVALID_REQUEST')
        self.assertEqual(provider.calls, [])

    def test_reject_bad_market_data(self):
        valid = rates([100] * 100)
        invalid_ohlc = rates([100] * 100)
        invalid_ohlc[0]['high'] = 1
        duplicate = rates([100] * 100)
        duplicate[1]['time'] = duplicate[0]['time']
        nan = rates([100] * 100)
        nan[0]['close'] = float('nan')
        for data in (None, [], valid[:99], valid[::-1], invalid_ohlc, duplicate, nan,
                     rates([100] * 100, last_open=NOW.replace(minute=20, second=0)),
                     rates([100] * 100, last_open=NOW.replace(second=0))):
            with self.subTest(data_type=type(data).__name__):
                body = self.assert_safe(self.client(ReadOnlyMT5(data)).get(
                    '/analyze?symbol=XAUUSD&timeframe=M1'), 503)
                self.assertEqual(body['error'], 'MARKET_DATA_UNAVAILABLE')

    def test_disconnected_terminal(self):
        provider = ReadOnlyMT5([], connected=False)
        self.assert_safe(self.client(provider).get('/analyze?symbol=XAUUSD&timeframe=M1'), 503)
        self.assertEqual(provider.calls, [])

    def test_missing_mt5_package_has_no_fallback(self):
        with patch.dict(sys.modules, {'MetaTrader5': None}):
            self.assert_safe(self.client(None).get('/analyze?symbol=XAUUSD&timeframe=M1'), 503)

    def test_provider_details_are_not_exposed(self):
        class Broken(ReadOnlyMT5):
            def terminal_info(self):
                raise RuntimeError('private-provider-detail')
        response = self.client(Broken([])).get('/analyze?symbol=XAUUSD&timeframe=M1')
        self.assert_safe(response, 503)
        self.assertNotIn('private-provider-detail', response.get_data(as_text=True))

    def test_unexpected_adapter_failure_is_safe(self):
        # Malformed adapter return shape, rather than MT5's normal array.
        self.assert_safe(self.client(ReadOnlyMT5(123)).get(
            '/analyze?symbol=XAUUSD&timeframe=M1'), 503)

    def test_home_and_import_do_not_access_terminal(self):
        class ForbiddenMT5:
            def __getattr__(self, name):
                raise AssertionError('Unexpected MT5 access: ' + name)
        with patch.dict(sys.modules, {'MetaTrader5': ForbiddenMT5()}):
            import main
            importlib.reload(main)
            self.assertEqual(main.app.test_client().get('/').get_json()['status'], 'OK')

    def test_data_becoming_stale_during_fetch_is_rejected(self):
        from unittest.mock import Mock
        clock = Mock(side_effect=[NOW, NOW + timedelta(minutes=10)])
        start, end = NOW.replace(hour=0, minute=0, second=0), NOW.replace(hour=23, minute=0, second=0)
        calendar = SessionCalendar('XAUUSD', start, end, ((start, end),))
        app = create_app(mt5=ReadOnlyMT5(rates([100] * 100)), clock=clock,
                         session_calendars={'XAUUSD': calendar})
        self.assert_safe(app.test_client().get('/analyze?symbol=XAUUSD&timeframe=M1'), 503)

    def test_session_closing_during_fetch_is_rejected(self):
        from unittest.mock import Mock
        start, end = NOW.replace(hour=0, minute=0, second=0), NOW.replace(minute=31, second=0)
        calendar = SessionCalendar('XAUUSD', start, end + timedelta(hours=1), ((start, end),))
        app = create_app(mt5=ReadOnlyMT5(rates([100] * 100)),
                         clock=Mock(side_effect=[NOW, end]),
                         session_calendars={'XAUUSD': calendar})
        self.assert_safe(app.test_client().get('/analyze?symbol=XAUUSD&timeframe=M1'), 503)

    def test_query_parameters_cannot_enable_execution(self):
        response = self.client(ReadOnlyMT5(rates([100] * 100))).get(
            '/analyze?symbol=XAUUSD&timeframe=M1&execution_allowed=true&signal=BUY')
        self.assert_safe(response, 200)

    def test_unknown_session_calendar_withholds_analysis_without_fetching(self):
        provider = ReadOnlyMT5([])
        app = create_app(mt5=provider, clock=lambda: NOW)
        body = self.assert_safe(app.test_client().get('/analyze?symbol=XAUUSD&timeframe=M1'), 503)
        self.assertEqual(body['error'], 'SESSION_CALENDAR_UNAVAILABLE')
        self.assertEqual(provider.calls, [])

    def test_closed_or_expired_session_withholds_analysis(self):
        provider = ReadOnlyMT5([])
        start = NOW.replace(hour=0, minute=0, second=0)
        end = start + timedelta(days=1)
        calendars = (SessionCalendar('XAUUSD', start, end, ()),
                     SessionCalendar('XAUUSD', start - timedelta(days=1), start, ()))
        for calendar in calendars:
            with self.subTest(calendar=calendar):
                app = create_app(mt5=provider, clock=lambda: NOW,
                                 session_calendars={'XAUUSD': calendar})
                self.assert_safe(app.test_client().get('/analyze?symbol=XAUUSD&timeframe=M1'), 503)
        self.assertEqual(provider.calls, [])

    def test_http_rejects_missing_candle_without_filling_prices(self):
        data = rates([100] * 101)
        del data[50]
        self.assert_safe(self.client(ReadOnlyMT5(data)).get('/analyze?symbol=XAUUSD&timeframe=M1'), 503)

    def test_legacy_helpers_never_fabricate_observations(self):
        self.assertEqual(get_signal('XAUUSD', 'M1'), 'WAIT')
        reasons = explain('XAUUSD', 'M1')
        self.assertIn('No validated market data', reasons[0])
        self.assertFalse(any('bullish' in reason.lower() or 'higher highs' in reason.lower()
                             for reason in reasons))


if __name__ == '__main__':
    unittest.main()
