"""Offline tests: no MT5 installation, broker connection or credentials needed."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from iat.mt5_data import MarketDataError, get_closed_candles

NOW = datetime(2026, 11, 12, 10, 30, 30, tzinfo=timezone.utc)

class FakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    def __init__(self, rates, connected=True):
        self.rates = rates
        self.connected = connected
        self.request = None
    def terminal_info(self):
        return SimpleNamespace(connected=self.connected)
    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.request = (symbol, timeframe, start, count)
        return self.rates

def make_rates(period=60, count=3, last_open=None):
    last_open = last_open or datetime(2026, 11, 12, 10, 29, tzinfo=timezone.utc)
    return [{"time": int((last_open - timedelta(seconds=period * (count - i - 1))).timestamp()),
             "open": 100 + i, "high": 102 + i, "low": 99 + i, "close": 101 + i}
            for i in range(count)]

class MT5DataTests(unittest.TestCase):
    def test_closed_m1_only(self):
        provider = FakeMT5(make_rates())
        rows = get_closed_candles(mt5=provider, now=NOW, count=3)
        self.assertEqual(provider.request, ("XAUUSD", 1, 1, 3))
        self.assertEqual(len(rows), 3)
    def test_closed_m5_only(self):
        provider = FakeMT5(make_rates(period=300, last_open=datetime(2026, 11, 12, 10, 25, tzinfo=timezone.utc)))
        get_closed_candles(mt5=provider, now=NOW, timeframe="M5", count=3)
        self.assertEqual(provider.request, ("XAUUSD", 5, 1, 3))
    def test_reject_unclosed(self):
        provider = FakeMT5(make_rates(last_open=datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc)))
        with self.assertRaises(MarketDataError):
            get_closed_candles(mt5=provider, now=NOW, count=3)
    def test_reject_stale(self):
        provider = FakeMT5(make_rates(last_open=datetime(2026, 11, 12, 10, 20, tzinfo=timezone.utc)))
        with self.assertRaisesRegex(MarketDataError, "stale"):
            get_closed_candles(mt5=provider, now=NOW, count=3)
    def test_reject_disconnected(self):
        with self.assertRaisesRegex(MarketDataError, "not connected"):
            get_closed_candles(mt5=FakeMT5(make_rates(), connected=False), now=NOW, count=3)
    def test_reject_duplicate(self):
        rates = make_rates()
        rates[1]["time"] = rates[0]["time"]
        with self.assertRaises(MarketDataError):
            get_closed_candles(mt5=FakeMT5(rates), now=NOW, count=3)
    def test_reject_bad_ohlc(self):
        rates = make_rates()
        rates[0]["high"] = 1
        with self.assertRaises(MarketDataError):
            get_closed_candles(mt5=FakeMT5(rates), now=NOW, count=3)
    def test_reject_missing_rates(self):
        with self.assertRaisesRegex(MarketDataError, "Incomplete"):
            get_closed_candles(mt5=FakeMT5(None), now=NOW, count=3)
    def test_reject_unsupported_timeframe(self):
        with self.assertRaises(ValueError):
            get_closed_candles(mt5=FakeMT5([]), now=NOW, timeframe="H1")
    def test_reject_naive_now(self):
        with self.assertRaises(ValueError):
            get_closed_candles(mt5=FakeMT5([]), now=NOW.replace(tzinfo=None))
    def test_reject_nonpositive_count(self):
        with self.assertRaises(ValueError):
            get_closed_candles(mt5=FakeMT5([]), now=NOW, count=0)

if __name__ == "__main__":
    unittest.main()
