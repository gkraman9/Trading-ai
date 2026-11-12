import unittest
from iat.analysis import analyze, validate_candles

def candles(closes):
    return [
        {"timestamp": f"2026-01-01T00:{i:02d}:00Z",
         "open": c, "high": c + 1, "low": c - 1, "close": c}
        for i, c in enumerate(closes)
    ]

class AnalysisTests(unittest.TestCase):
    def test_bullish_does_not_trade(self):
        result = analyze("XAUUSD", "M5", candles([100, 101, 102]))
        self.assertEqual(result["market_state"], "BULLISH")
        self.assertEqual(result["signal"], "WAIT")
        self.assertFalse(result["execution_allowed"])

    def test_bearish(self):
        self.assertEqual(analyze("XAUUSD", "M5", candles([102, 101, 100]))["market_state"], "BEARISH")

    def test_range(self):
        self.assertEqual(analyze("XAUUSD", "M5", candles([100, 102, 101]))["market_state"], "RANGE")

    def test_reject_duplicate_timestamp(self):
        rows = candles([100, 101, 102])
        rows[2]["timestamp"] = rows[1]["timestamp"]
        with self.assertRaises(ValueError):
            validate_candles(rows)

    def test_reject_invalid_high(self):
        rows = candles([100, 101, 102])
        rows[0]["high"] = 50
        with self.assertRaises(ValueError):
            validate_candles(rows)

    def test_reject_short_data(self):
        with self.assertRaises(ValueError):
            validate_candles(candles([100, 101]))

    def test_reject_naive_timestamp(self):
        rows = candles([100, 101, 102])
        rows[0]["timestamp"] = "2026-01-01T00:00:00"
        with self.assertRaises(ValueError):
            validate_candles(rows)

if __name__ == "__main__":
    unittest.main()
