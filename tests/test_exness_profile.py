"""User-transcribed boundary regressions, not independent broker validation."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from diagnostics import install_exness_calendar, mt5_readonly_check
from iat.calendar_assurance import EXNESS_HOLDS, EXNESS_SOURCE
from iat.exness_profile import BUNDLED_DIRECTORY, PROFILE, inspect_profile, install_profile, read_profile
from iat.mt5_data import MarketDataError, get_closed_candles
from iat.session_config import compile_session_config, load_session_bundle, load_session_config
from iat.sessions import SessionValidationError
from main import create_app

NOW = datetime(2026, 11, 12, 12, 30, tzinfo=timezone.utc)


class ForbiddenMT5:
    def __getattr__(self, name):
        raise AssertionError('No terminal metadata or credential access is authorized in blocked preflight')


class ExnessProfileTests(unittest.TestCase):
    def candidate(self):
        return BUNDLED_DIRECTORY / (PROFILE + '.json')

    def test_strict_v1_schema_and_review_checksum(self):
        raw, config, calendar, review = read_profile()
        self.assertEqual(set(config), {'version', 'symbol', 'timezone', 'coverage', 'verification',
                                       'weekdays', 'holidays', 'exceptions', 'closures'})
        self.assertEqual(config['version'], 1)
        self.assertEqual(config['symbol'], 'XAUUSD')
        self.assertEqual(config['timezone'], 'UTC')
        self.assertEqual(hashlib.sha256(raw).hexdigest(), review['config_sha256'])
        self.assertEqual(calendar.assurance_codes, EXNESS_HOLDS)
        self.assertFalse(review['broker_certified'])

    def test_screenshot_boundaries_are_preserved_exactly(self):
        _, config, _, _ = read_profile()
        for key in ('mon', 'tue', 'wed', 'thu'):
            self.assertEqual(config['weekdays'][key], [
                {'open': '00:00', 'close': '21:58', 'close_day_offset': 0},
                {'open': '23:00', 'close': '00:00', 'close_day_offset': 1}])
        self.assertEqual(config['weekdays']['sun'], [{'open': '23:01', 'close': '00:00', 'close_day_offset': 1}])
        self.assertEqual(config['weekdays']['fri'], [{'open': '00:00', 'close': '21:58', 'close_day_offset': 0}])
        self.assertEqual(config['weekdays']['sat'], [])

    def test_sunday_weekday_break_friday_close_and_saturday_metadata(self):
        _, _, calendar, _ = read_profile()
        # Structural metadata inspection only; no assurance holds are removed.
        for value, expected in (
                ('2026-11-08T23:00:00+00:00', False), ('2026-11-08T23:01:00+00:00', True),
                ('2026-11-09T21:57:00+00:00', True), ('2026-11-09T21:58:00+00:00', False),
                ('2026-11-09T22:59:00+00:00', False), ('2026-11-09T23:00:00+00:00', True),
                ('2026-11-13T21:58:00+00:00', False), ('2026-11-14T12:00:00+00:00', False)):
            moment = datetime.fromisoformat(value)
            with self.subTest(value=value):
                self.assertEqual(any(a <= moment < b for a, b in calendar.windows), expected)

    def test_m5_off_grid_boundaries_remain_unsupported(self):
        assessment = inspect_profile(now=NOW)
        self.assertEqual(assessment['timeframe_compatibility']['M5'], 'SESSION_ALIGNMENT_INVALID')
        self.assertIn('SESSION_ALIGNMENT_INVALID', assessment['reason_codes'])
        _, config, _, _ = read_profile()
        # A generic synthetic structural test must fail M5 even without a hold.
        config['verification']['source'] = 'OFFLINE STRUCTURAL TEST ONLY'
        calendar = compile_session_config(config)
        with self.assertRaises(SessionValidationError) as raised:
            calendar.validate_request('XAUUSD', NOW, timedelta(minutes=5))
        self.assertEqual(raised.exception.code, 'SESSION_ALIGNMENT_INVALID')

    def test_coverage_includes_preceding_friday_for_100_potential_m5_slots(self):
        assessment = inspect_profile(now=datetime(2026, 11, 9, 0, 5, tzinfo=timezone.utc))
        self.assertEqual(assessment['coverage_start_utc'], '2026-11-06T00:00:00+00:00')
        self.assertTrue(assessment['coverage_has_100_potential_m5_slots'])
        self.assertGreaterEqual(assessment['potential_m5_grid_slots_before_test'], 100)
        self.assertFalse(assessment['runtime_ready'])

    def test_current_profile_is_never_declared_certified_or_ready(self):
        assessment = inspect_profile(now=NOW)
        self.assertTrue(assessment['schema_valid'])
        self.assertEqual(assessment['status'], 'BLOCKED')
        self.assertFalse(assessment['runtime_ready'])
        self.assertFalse(assessment['terminal_tested'])
        self.assertFalse(assessment['broker_certified'])
        self.assertEqual(assessment['signal'], 'WAIT')
        self.assertIs(assessment['execution_allowed'], False)

    def test_missing_holiday_info_is_unknown_not_invented_closures(self):
        _, config, _, review = read_profile()
        self.assertEqual(config['holidays'], [])
        self.assertEqual(config['exceptions'], {})
        self.assertEqual(config['closures'], [])
        self.assertIn('HOLIDAY_COVERAGE_UNKNOWN', review['unresolved_codes'])
        self.assertIn('HOLIDAY_COVERAGE_UNKNOWN', inspect_profile(now=NOW)['reason_codes'])

    def test_published_close_only_seconds_are_not_rounded_into_v1(self):
        _, config, _, review = read_profile()
        phases = review['published_winter_phases_utc']
        self.assertEqual(phases['sunday']['close_only'], ['23:01:30', '23:05:00'])
        self.assertEqual(phases['mon_thu']['close_only'], ['23:00:30', '23:02:00'])
        self.assertIn('CALENDAR_PHASES_UNREPRESENTABLE', inspect_profile(now=NOW)['reason_codes'])
        config['weekdays']['sun'][0]['open'] = '23:01:30'
        with self.assertRaises(ValueError):
            compile_session_config(config)

    def test_utc_offset_does_not_change_with_us_dst(self):
        utc_zone = ZoneInfo('UTC')
        ny = ZoneInfo('America/New_York')
        before = datetime(2026, 10, 30, 12, tzinfo=utc_zone)
        after = datetime(2026, 11, 2, 12, tzinfo=utc_zone)
        self.assertEqual(before.utcoffset(), timedelta(0))
        self.assertEqual(after.utcoffset(), timedelta(0))
        self.assertNotEqual(before.astimezone(ny).utcoffset(), after.astimezone(ny).utcoffset())
        _, _, _, review = read_profile()
        self.assertEqual(review['published_summer_reference_utc']['friday_close'], '20:58:00')
        self.assertEqual(review['published_winter_phases_utc']['friday']['close'], '21:58:00')

    def test_expiry_and_insufficient_prior_coverage_are_explicit(self):
        for now in (datetime(2026, 11, 16, tzinfo=timezone.utc), datetime(2027, 3, 14, tzinfo=timezone.utc)):
            with self.subTest(now=now):
                assessment = inspect_profile(now=now)
                self.assertIn('SESSION_COVERAGE_UNKNOWN', assessment['reason_codes'])
                self.assertFalse(assessment['runtime_ready'])
        early = inspect_profile(now=datetime(2026, 11, 6, 0, 5, tzinfo=timezone.utc))
        self.assertIn('HISTORY_INCOMPLETE', early['reason_codes'])

    def test_provider_fails_before_mt5_access_for_both_timeframes(self):
        calendar = load_session_config(self.candidate())
        for timeframe in ('M1', 'M5'):
            with self.subTest(timeframe=timeframe), self.assertRaises(MarketDataError) as raised:
                get_closed_candles(mt5=ForbiddenMT5(), session_calendar=calendar,
                                   timeframe=timeframe, count=100, now=NOW)
            self.assertEqual(raised.exception.code, EXNESS_HOLDS[0])

    def test_demo_preflight_emits_all_holds_without_import_or_initialization(self):
        report = mt5_readonly_check.validate_demo(self.candidate(), mt5=ForbiddenMT5(), clock=lambda: NOW)
        self.assertEqual(report['status'], 'FAIL')
        self.assertFalse(report['safety']['binding_initialization_attempted'])
        codes = [item['code'] for item in report['diagnostics']]
        self.assertTrue(set(EXNESS_HOLDS) <= set(codes))
        self.assertIn('SESSION_ALIGNMENT_INVALID', report['timeframes']['M5']['codes'])
        self.assertIsNone(report['timeframes']['M1']['validated_closed_count'])
        self.assertIsNone(report['timeframes']['M5']['unexpected_gap_count'])
        mt5_readonly_check.validate_report(report)

    def test_read_only_http_api_fails_closed_with_wait(self):
        app = create_app(session_config_path=self.candidate(), mt5=ForbiddenMT5(), clock=lambda: NOW)
        for timeframe in ('M1', 'M5'):
            response = app.test_client().get('/analyze?symbol=XAUUSD&timeframe=' + timeframe)
            self.assertEqual(response.status_code, 503)
            body = response.get_json()
            self.assertEqual(body['signal'], 'WAIT')
            self.assertIs(body['execution_allowed'], False)
            self.assertFalse(body['quality']['valid'])
            self.assertEqual(body['quality']['diagnostics'][0]['code'], EXNESS_HOLDS[0])

    def test_unknown_unverified_source_marker_fails_closed(self):
        _, config, _, _ = read_profile()
        config['verification']['source'] = 'IAT_UNVERIFIED:PRIVATE_SERVER_SECRET'
        calendar = compile_session_config(config)
        self.assertEqual(calendar.assurance_codes, ('CALENDAR_ASSURANCE_UNKNOWN',))
        with self.assertRaises(SessionValidationError) as raised:
            calendar.validate_request('XAUUSD', NOW, timedelta(minutes=1))
        self.assertNotIn('PRIVATE_SERVER_SECRET', str(raised.exception))

    def test_new_install_is_byte_reproducible_and_runtime_blocked(self):
        raw, _, _, _ = read_profile()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'config with spaces' / 'candidate.json'
            result = install_profile(target, now=NOW)
            self.assertTrue(result['installed'])
            self.assertEqual(target.read_bytes(), raw)
            self.assertEqual(load_session_config(target).assurance_codes, EXNESS_HOLDS)
            self.assertFalse(result['runtime_ready'])

    def test_existing_configuration_requires_confirmation_and_matching_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'existing.json'
            target.write_bytes(b'original user content')
            with self.assertRaises(FileExistsError):
                install_profile(target, now=NOW)
            self.assertEqual(target.read_bytes(), b'original user content')
            with self.assertRaises(ValueError):
                install_profile(target, now=NOW, replace_confirmed=True)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            result = install_profile(target, now=NOW, replace_confirmed=True, expected_current_sha256=digest)
            self.assertTrue(result['installed'])
            self.assertEqual(load_session_config(target).assurance_codes, EXNESS_HOLDS)

    def test_concurrently_created_destination_is_not_overwritten_without_confirmation(self):
        from iat.exness_profile import publish_new
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'candidate.json'
            def concurrent(temporary, destination):
                target.write_bytes(b'concurrent user configuration')
                return publish_new(temporary, destination)
            with patch('iat.exness_profile.publish_new', side_effect=concurrent), self.assertRaises(FileExistsError):
                install_profile(target, now=NOW)
            self.assertEqual(target.read_bytes(), b'concurrent user configuration')
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_configuration_changed_since_confirmation_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'existing.json'
            target.write_bytes(b'original')
            old = hashlib.sha256(target.read_bytes()).hexdigest()
            target.write_bytes(b'new user changes')
            with self.assertRaises(ValueError):
                install_profile(target, replace_confirmed=True, expected_current_sha256=old, now=NOW)
            self.assertEqual(target.read_bytes(), b'new user changes')

    def test_tampered_bundle_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in BUNDLED_DIRECTORY.glob(PROFILE + '*.json'):
                (root / path.name).write_bytes(path.read_bytes())
            path = root / (PROFILE + '.json')
            path.write_bytes(path.read_bytes().replace(b'21:58', b'22:00'))
            with self.assertRaises(ValueError):
                read_profile(root)

    def test_source_and_review_files_cannot_be_overwritten(self):
        for path in (self.candidate(), BUNDLED_DIRECTORY / (PROFILE + '.review.json')):
            with self.assertRaises(ValueError):
                install_profile(path, now=NOW)

    def test_failed_publish_does_not_turn_existing_user_config_into_success(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'existing.json'
            target.write_bytes(b'preserve this')
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            with patch('iat.exness_profile.os.replace', side_effect=OSError('PRIVATE_SERVER_SECRET')), self.assertRaises(OSError):
                install_profile(target, replace_confirmed=True, expected_current_sha256=digest, now=NOW)
            self.assertEqual(target.read_bytes(), b'preserve this')
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_install_cli_reports_blocked_not_pass_and_does_not_echo_private_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'PRIVATE_SERVER_SECRET.json'
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = install_exness_calendar.main(['--destination', str(target)])
            self.assertEqual(code, 2)
            self.assertNotIn('PRIVATE_SERVER_SECRET', output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['status'], 'BLOCKED')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(install_exness_calendar.main(['--destination', str(target)]), 1)
