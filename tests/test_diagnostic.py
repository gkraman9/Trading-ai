"""Mocked Windows diagnostic lifecycle. Never starts a real terminal."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from diagnostics import mt5_readonly_check as diagnostic
from iat.mt5_data import get_candle_snapshot
from test_api import NOW, rates
from test_session_config import fixture


class DemoAdapter:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, mode=0):
        self.mode = mode
        self.stopped = False
        self.requests = []

    def initialize(self):
        return True

    def shutdown(self):
        self.stopped = True

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode)

    def symbol_info(self, symbol):
        return SimpleNamespace(visible=True)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.requests.append((symbol, timeframe, start, count))
        return rates([100] * count, period=60 if timeframe == 1 else 300)


class DiagnosticTests(unittest.TestCase):
    def test_missing_config_stops_before_terminal_import(self):
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(diagnostic.main(), 2)

    def test_invalid_config_stops_before_terminal_import(self):
        with patch.dict(os.environ, {'IAT_SESSION_CONFIG': '/missing-fixture.json'}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(diagnostic.main(), 2)

    def run_diagnostic(self, adapter):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calendar.json'
            config = fixture()
            # M5 history spans 500 minutes; use an explicit continuous test day.
            config['weekdays']['thu'] = [{'open': '00:00', 'close': '00:00', 'close_day_offset': 1}]
            path.write_text(json.dumps(config))
            output = io.StringIO()
            with patch.dict(os.environ, {'IAT_SESSION_CONFIG': str(path)}), \
                    patch.dict('sys.modules', {'MetaTrader5': adapter}), \
                    patch.object(diagnostic, 'get_candle_snapshot',
                                 side_effect=lambda **kw: get_candle_snapshot(now=NOW, **kw)), \
                    contextlib.redirect_stdout(output):
                result = diagnostic.main()
            return result, output.getvalue()

    def test_demo_diagnostic_checks_both_timeframes_and_shuts_down(self):
        adapter = DemoAdapter()
        result, output = self.run_diagnostic(adapter)
        self.assertEqual(result, 0)
        body = json.loads(output)
        self.assertEqual(body['status'], 'PASS')
        self.assertEqual(len(adapter.requests), 2)
        self.assertTrue(adapter.stopped)
        for value in body['timeframes'].values():
            self.assertEqual(value['signal'], 'WAIT')
            self.assertIs(value['execution_allowed'], False)
            self.assertTrue(value['quality']['valid'])

    def test_non_demo_account_never_fetches(self):
        adapter = DemoAdapter(mode=2)
        result, _ = self.run_diagnostic(adapter)
        self.assertEqual(result, 2)
        self.assertEqual(adapter.requests, [])
        self.assertTrue(adapter.stopped)
