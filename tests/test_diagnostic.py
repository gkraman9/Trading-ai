"""Mocked demo evidence only. No real account, credential or terminal access."""
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from diagnostics import mt5_readonly_check as diagnostic
from iat.session_config import compile_session_config
from test_api import NOW, rates
from test_session_config import fixture

SECRET = 'PRIVATE_SERVER_ACCOUNT_PASSWORD_314159'


def demo_config():
    config = fixture()
    config['symbol'] = 'XAUUSD.' + SECRET
    for key in ('mon', 'tue', 'wed', 'thu', 'fri'):
        config['weekdays'][key] = [{'open': '00:00', 'close': '00:00', 'close_day_offset': 1}]
    return config


class DemoAdapter:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, mode=0):
        self.mode = mode
        self.stopped = False
        self.initialized = False
        self.requests = []
        self.connected = True
        self.trade_allowed = False
        self.tradeapi_disabled = True
        self.visible = True
        self.currency_base = 'XAU'
        self.currency_profit = 'USD'
        self.digits = 2
        self.transform = lambda value, timeframe: value
        self.config = demo_config()

    def initialize(self):
        self.initialized = True
        return True

    def shutdown(self):
        self.stopped = True

    def terminal_info(self):
        return SimpleNamespace(connected=self.connected, trade_allowed=self.trade_allowed,
                               tradeapi_disabled=self.tradeapi_disabled, server=SECRET, path=SECRET)

    def account_info(self):
        mode = self.mode
        class Account:
            trade_mode = mode
            def __getattr__(self, name):
                raise AssertionError('Forbidden account field access')
        return Account()

    def symbol_info(self, symbol):
        return SimpleNamespace(visible=self.visible, currency_base=self.currency_base,
                               currency_profit=self.currency_profit, digits=self.digits,
                               description=SECRET, path=SECRET)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.requests.append((symbol, timeframe, start, count))
        return self.transform(rates([100] * count, period=60 if timeframe == 1 else 300), timeframe)

    def iat_session_metadata(self, symbol, start, end):
        calendar = compile_session_config(self.config)
        return {'version': 1, 'kind': 'DATED', 'symbol': symbol, 'complete': True,
                'collected_at_utc': NOW.isoformat(),
                'coverage_start': start.isoformat(), 'coverage_end': end.isoformat(),
                'windows': [{'start': a.isoformat(), 'end': b.isoformat()} for a, b in calendar.windows]}

    def __getattr__(self, name):
        if any(part in name for part in ('order', 'login', 'password', 'token', 'server')):
            raise AssertionError('Forbidden execution or credential method access')
        raise AttributeError(name)


class DiagnosticTests(unittest.TestCase):
    def run_report(self, adapter=None, config=None, **kwargs):
        adapter = DemoAdapter() if adapter is None else adapter
        config = demo_config() if config is None else config
        adapter.config = config
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calendar.json'
            path.write_text(json.dumps(config))
            package = kwargs.pop('package', '5.0.5370')
            clock = kwargs.pop('clock', lambda: NOW)
            with patch.object(diagnostic, 'package_version', return_value=package):
                report = diagnostic.validate_demo(path, mt5=adapter, clock=clock, **kwargs)
        self.assertNotIn(SECRET, json.dumps(report))
        self.assertEqual(report['safety']['signal'], 'WAIT')
        self.assertIs(report['safety']['execution_allowed'], False)
        diagnostic.validate_report(report)
        return report, adapter

    def codes(self, report):
        return [item['code'] for item in report['diagnostics']]

    def test_demo_diagnostic_checks_both_timeframes_and_shuts_down(self):
        report, adapter = self.run_report()
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(len(adapter.requests), 2)
        self.assertTrue(adapter.stopped)
        for value in report['timeframes'].values():
            self.assertEqual(value['status'], 'PASS')
            self.assertEqual(value['validated_closed_count'], 100)
            self.assertEqual(value['unexpected_gap_count'], 0)
            self.assertGreaterEqual(value['age_seconds'], 0)
        self.assertFalse(report['safety']['independent_broker_certification'])

    def test_missing_config_stops_before_terminal_import(self):
        adapter = DemoAdapter()
        report = diagnostic.validate_demo(None, mt5=adapter, clock=lambda: NOW)
        self.assertEqual(report['status'], 'FAIL')
        self.assertFalse(adapter.initialized)
        self.assertIn('CONFIG_INVALID', self.codes(report))

    def test_invalid_config_stops_before_terminal_import(self):
        adapter = DemoAdapter()
        report = diagnostic.validate_demo('/missing-calendar-fixture.json', mt5=adapter, clock=lambda: NOW)
        self.assertEqual(report['status'], 'FAIL')
        self.assertFalse(adapter.initialized)

    def test_non_demo_account_never_fetches(self):
        for mode in (2, -1, None, False):
            with self.subTest(mode=mode):
                report, adapter = self.run_report(DemoAdapter(mode=mode))
                self.assertEqual(report['status'], 'FAIL')
                self.assertIn('DEMO_ACCOUNT_REQUIRED', self.codes(report))
                self.assertEqual(adapter.requests, [])
                self.assertTrue(adapter.stopped)

    def test_disconnected_terminal_never_fetches(self):
        adapter = DemoAdapter()
        adapter.connected = False
        report, _ = self.run_report(adapter)
        self.assertIn('TERMINAL_DISCONNECTED', self.codes(report))
        self.assertEqual(adapter.requests, [])

    def test_unsafe_or_unknown_execution_flags_block_data_access(self):
        for field, value, code in (('trade_allowed', True, 'AUTOTRADING_NOT_DISABLED'),
                                   ('trade_allowed', None, 'AUTOTRADING_NOT_DISABLED'),
                                   ('tradeapi_disabled', False, 'EXTERNAL_API_NOT_DISABLED')):
            adapter = DemoAdapter()
            setattr(adapter, field, value)
            report, _ = self.run_report(adapter)
            self.assertIn(code, self.codes(report))
            self.assertEqual(adapter.requests, [])

    def test_missing_symbol(self):
        adapter = DemoAdapter()
        adapter.visible = False
        report, _ = self.run_report(adapter)
        self.assertIn('SYMBOL_NOT_VISIBLE', self.codes(report))
        self.assertEqual(adapter.requests, [])

    def test_asset_mismatch_and_malformed_symbol_metadata(self):
        for field, value, code in (('currency_base', 'EUR', 'SYMBOL_ASSET_MISMATCH'),
                                   ('digits', SECRET, 'SYMBOL_METADATA_INVALID')):
            adapter = DemoAdapter()
            setattr(adapter, field, value)
            report, _ = self.run_report(adapter)
            self.assertIn(code, self.codes(report))
            self.assertEqual(adapter.requests, [])

    def test_missing_asset_metadata_warns(self):
        adapter = DemoAdapter()
        adapter.currency_base = None
        report, _ = self.run_report(adapter)
        self.assertEqual(report['status'], 'WARN')
        self.assertIn('SYMBOL_ASSET_UNVERIFIED', self.codes(report))

    def test_stale_candles(self):
        adapter = DemoAdapter()
        def stale(data, timeframe):
            for row in data:
                row['time'] -= 3600
            return data
        adapter.transform = stale
        report, _ = self.run_report(adapter)
        self.assertEqual(report['status'], 'FAIL')
        self.assertIn('DATA_STALE', self.codes(report))
        self.assertIsNone(report['timeframes']['M1']['unexpected_gap_count'])

    def test_incomplete_history(self):
        adapter = DemoAdapter()
        adapter.transform = lambda values, timeframe: values[:-1]
        report, _ = self.run_report(adapter)
        self.assertIn('HISTORY_INCOMPLETE', self.codes(report))
        self.assertEqual(len(adapter.requests), 2)

    def test_gaps_and_duplicates_and_malformed_ohlc(self):
        for kind, code in (('gap', 'CANDLES_MISSING'), ('duplicate', 'TIMESTAMP_DUPLICATE'),
                           ('ohlc', 'OHLC_MALFORMED')):
            adapter = DemoAdapter()
            def transform(values, timeframe):
                if kind == 'gap':
                    values[0]['time'] -= 60 if timeframe == 1 else 300
                elif kind == 'duplicate':
                    values[1]['time'] = values[0]['time']
                else:
                    values[0]['low'] = float('nan')
                return values
            adapter.transform = transform
            report, _ = self.run_report(adapter)
            self.assertIn(code, self.codes(report))
            self.assertEqual(report['status'], 'FAIL')

    def test_closed_session_warns_without_claiming_data_success(self):
        config = demo_config()
        config['holidays'] = ['2026-11-12']
        report, adapter = self.run_report(config=config)
        self.assertIn('SESSION_CLOSED', self.codes(report))
        self.assertEqual(report['status'], 'WARN')
        self.assertEqual(adapter.requests, [])
        self.assertIsNone(report['timeframes']['M1']['validated_closed_count'])

    def test_standard_package_metadata_unavailable_warns(self):
        adapter = DemoAdapter()
        adapter.iat_session_metadata = None
        report, _ = self.run_report(adapter)
        self.assertEqual(report['status'], 'WARN')
        self.assertIn('BROKER_SESSIONS_UNAVAILABLE', self.codes(report))

    def test_malformed_or_mismatched_broker_metadata_fails(self):
        for kind in ('malformed', 'mismatch'):
            adapter = DemoAdapter()
            original = adapter.iat_session_metadata
            def collect(*args):
                metadata = original(*args)
                if kind == 'malformed':
                    metadata['server'] = SECRET
                else:
                    metadata['windows'] = []
                return metadata
            adapter.iat_session_metadata = collect
            report, _ = self.run_report(adapter)
            self.assertEqual(report['status'], 'FAIL')
            self.assertIn('BROKER_METADATA_INVALID' if kind == 'malformed' else 'BROKER_SESSION_MISMATCH', self.codes(report))

    def test_initialization_failure_is_sanitized_and_shutdown_attempted(self):
        adapter = DemoAdapter()
        def broken():
            raise RuntimeError(SECRET)
        adapter.initialize = broken
        report, _ = self.run_report(adapter)
        self.assertIn('INITIALIZATION_FAILED', self.codes(report))
        self.assertTrue(adapter.stopped)

    def test_provider_exception_is_sanitized(self):
        adapter = DemoAdapter()
        adapter.transform = lambda values, timeframe: (_ for _ in ()).throw(RuntimeError(SECRET))
        report, _ = self.run_report(adapter)
        self.assertIn('PROVIDER_FAILURE', self.codes(report))

    def test_shutdown_failure_prevents_success(self):
        adapter = DemoAdapter()
        def broken():
            raise RuntimeError(SECRET)
        adapter.shutdown = broken
        report, _ = self.run_report(adapter)
        self.assertEqual(report['status'], 'FAIL')
        self.assertIn('SHUTDOWN_FAILED', self.codes(report))
        self.assertFalse(report['safety']['shutdown_completed'])

    def test_missing_package_version_warns(self):
        report, _ = self.run_report(package=None)
        self.assertEqual(report['status'], 'WARN')
        self.assertIn('VERSION_UNAVAILABLE', self.codes(report))

    def test_explicit_terminal_path_is_passed_without_login_arguments_or_report_leak(self):
        adapter = DemoAdapter()
        arguments = []
        def initialize(*args, **kwargs):
            arguments.append((args, kwargs))
            return True
        adapter.initialize = initialize
        report, _ = self.run_report(adapter, terminal_path=SECRET)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(arguments, [((SECRET,), {})])

    def test_initialize_false_never_fetches(self):
        adapter = DemoAdapter()
        adapter.initialize = lambda: False
        report, _ = self.run_report(adapter)
        self.assertEqual(report['status'], 'FAIL')
        self.assertEqual(adapter.requests, [])
        self.assertTrue(adapter.stopped)

    def test_interrupt_leaves_failure_and_shutdown(self):
        adapter = DemoAdapter()
        def interrupt(values, timeframe):
            raise KeyboardInterrupt()
        adapter.transform = interrupt
        report, _ = self.run_report(adapter)
        self.assertIn('INTERRUPTED', self.codes(report))
        self.assertEqual(report['status'], 'FAIL')
        self.assertTrue(adapter.stopped)

    def test_clock_regression_is_reported_without_success(self):
        count = [0]
        def clock():
            count[0] += 1
            return NOW if count[0] <= 3 else NOW - timedelta(seconds=1)
        report, _ = self.run_report(clock=clock)
        self.assertEqual(report['status'], 'FAIL')
        self.assertIn('CLOCK_MOVED_BACKWARD', self.codes(report))

    def test_partial_timeframe_failure_does_not_create_overall_pass(self):
        adapter = DemoAdapter()
        adapter.transform = lambda values, timeframe: values if timeframe == 1 else None
        report, _ = self.run_report(adapter)
        self.assertEqual(report['timeframes']['M1']['status'], 'PASS')
        self.assertEqual(report['timeframes']['M5']['status'], 'FAIL')
        self.assertEqual(report['status'], 'FAIL')

    def test_version_strings_are_allowlisted(self):
        with patch.object(diagnostic, 'version', return_value=SECRET):
            self.assertIsNone(diagnostic.package_version())
        with patch.object(diagnostic, 'version', return_value='5.0.5370'):
            self.assertEqual(diagnostic.package_version(), '5.0.5370')

    def test_python_provider_output_and_errors_are_not_printed(self):
        adapter = DemoAdapter()
        original = adapter.initialize
        def noisy():
            print(SECRET)
            return original()
        adapter.initialize = noisy
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.run_report(adapter)
        self.assertNotIn(SECRET, output.getvalue())

    def test_report_input_cannot_inject_raw_fields(self):
        initial = diagnostic.new_report()
        initial['account_password'] = SECRET
        report, _ = self.run_report(report=initial)
        self.assertNotIn('account_password', report)

    def test_cli_argument_errors_do_not_echo_values(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(diagnostic.main(['--password', SECRET]), 1)
        self.assertNotIn(SECRET, output.getvalue())
