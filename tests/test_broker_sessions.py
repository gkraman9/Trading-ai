"""Broker metadata adapters are mocked; no real broker hours are claimed."""
import copy
import unittest
from types import SimpleNamespace
from datetime import timedelta

from iat.broker_sessions import compare_broker_sessions
from iat.session_config import compile_session_config
from test_api import NOW
from test_diagnostic import DemoAdapter, SECRET, demo_config


class BrokerSessionTests(unittest.TestCase):
    def compare(self, config=None, document=None, override=False):
        config = demo_config() if config is None else config
        adapter = DemoAdapter()
        adapter.config = config
        calendar = compile_session_config(config)
        result = compare_broker_sessions(adapter, config, calendar, document, now=NOW) if override else compare_broker_sessions(adapter, config, calendar, now=NOW)
        self.assertNotIn(SECRET, str(result))
        return result

    def dated(self):
        config = demo_config()
        calendar = compile_session_config(config)
        return DemoAdapter().iat_session_metadata(calendar.symbol, calendar.coverage_start, calendar.coverage_end)

    def weekly(self, config=None):
        config = demo_config() if config is None else config
        return {'version': 1, 'kind': 'WEEKLY', 'symbol': config['symbol'],
                'collected_at_utc': NOW.isoformat(), 'timezone': config['timezone'], 'weekdays': copy.deepcopy(config['weekdays'])}

    def test_matching_dated_metadata(self):
        result = self.compare()
        self.assertEqual(result['comparison'], 'MATCH')
        self.assertTrue(result['dated_exceptions_covered'])
        self.assertEqual(result['mismatch_intervals'], 0)

    def test_standard_python_api_has_no_invented_schedule(self):
        config = demo_config()
        calendar = compile_session_config(config)
        result = compare_broker_sessions(SimpleNamespace(), config, calendar)
        self.assertEqual(result['codes'], ['BROKER_SESSIONS_UNAVAILABLE'])
        self.assertIsNone(result['mismatch_intervals'])

    def test_weekly_matches_but_cannot_verify_dated_exceptions(self):
        result = self.compare(document=self.weekly(), override=True)
        self.assertEqual(result['comparison'], 'UNCERTAIN')
        self.assertIn('BROKER_EXCEPTIONS_UNVERIFIED', result['codes'])
        self.assertFalse(result['dated_exceptions_covered'])

    def test_weekly_difference_is_a_mismatch(self):
        document = self.weekly()
        document['weekdays']['thu'] = []
        result = self.compare(document=document, override=True)
        self.assertEqual(result['comparison'], 'MISMATCH')
        self.assertGreater(result['mismatch_intervals'], 0)

    def test_timezone_difference_not_silently_assumed(self):
        config = demo_config()
        for key in config['weekdays']:
            config['weekdays'][key] = [{'open': '08:00', 'close': '17:00', 'close_day_offset': 0}]
        document = self.weekly(config)
        document['timezone'] = 'America/New_York'
        result = self.compare(config, document, True)
        self.assertEqual(result['comparison'], 'MISMATCH')

    def test_holidays_overrides_and_closures_remain_uncertain_in_weekly_metadata(self):
        config = demo_config()
        config['holidays'] = ['2026-11-12']
        config['exceptions'] = {'2026-11-13': []}
        config['closures'] = [{'start': '2026-11-11T10:00', 'end': '2026-11-11T11:00'}]
        result = self.compare(config, self.weekly(config), True)
        self.assertEqual(result['comparison'], 'UNCERTAIN')
        self.assertFalse(result['dated_exceptions_covered'])

    def test_dated_holiday_difference_is_detected(self):
        config = demo_config()
        config['holidays'] = ['2026-11-12']
        result = self.compare(config, self.dated(), True)
        self.assertEqual(result['comparison'], 'MISMATCH')

    def test_overnight_and_split_break_schedule(self):
        config = demo_config()
        config['weekdays']['mon'] = [{'open': '20:00', 'close': '23:00', 'close_day_offset': 0},
                                    {'open': '23:30', 'close': '01:00', 'close_day_offset': 1}]
        config['weekdays']['tue'] = []
        result = self.compare(config, self.weekly(config), True)
        self.assertEqual(result['mismatch_intervals'], 0)

    def test_dst_ambiguity_is_not_resolved_by_guessing(self):
        config = demo_config()
        config['coverage'] = {'start': '2026-11-01', 'end': '2026-11-03'}
        document = self.weekly(config)
        document['timezone'] = 'America/New_York'
        document['weekdays']['sun'] = [{'open': '01:30', 'close': '04:00', 'close_day_offset': 0}]
        result = self.compare(config, document, True)
        self.assertEqual(result['codes'], ['BROKER_METADATA_INVALID'])

    def test_incomplete_coverage_or_wrong_symbol_is_invalid(self):
        for field, value in (('complete', False), ('symbol', 'OTHER'),
                             ('coverage_start', '2026-11-12T00:00:00Z')):
            document = self.dated()
            document[field] = value
            with self.subTest(field=field):
                self.assertEqual(self.compare(document=document, override=True)['comparison'], 'INVALID')

    def test_old_or_future_export_is_not_treated_as_current_evidence(self):
        for value in (NOW - timedelta(days=2), NOW + timedelta(seconds=1)):
            document = self.dated()
            document['collected_at_utc'] = value.isoformat()
            result = self.compare(document=document, override=True)
            self.assertEqual(result['codes'], ['BROKER_METADATA_STALE'])
            self.assertEqual(result['comparison'], 'INVALID')

    def test_malformed_metadata_never_leaks_raw_values(self):
        for document in (None, [], {'server': SECRET}, dict(self.dated(), server=SECRET),
                         dict(self.weekly(), timezone=SECRET), dict(self.dated(), windows=[{'start': SECRET}])):
            with self.subTest(kind=type(document).__name__):
                result = self.compare(document=document, override=True)
                self.assertEqual(result['codes'], ['BROKER_METADATA_INVALID'])

    def test_unordered_or_overlapping_dated_windows_are_rejected(self):
        document = self.dated()
        document['windows'] = document['windows'] * 2
        self.assertEqual(self.compare(document=document, override=True)['comparison'], 'INVALID')
