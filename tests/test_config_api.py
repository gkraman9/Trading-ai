"""File-to-HTTP integration using explicitly synthetic schedules and raw rates."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import create_app
from test_api import NOW, ReadOnlyMT5, rates
from test_session_config import fixture


class ConfigAPITests(unittest.TestCase):
    def test_backward_clock_across_http_requests_is_rejected_before_fetch(self):
        from unittest.mock import Mock
        from datetime import timedelta
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calendar.json'
            path.write_text(json.dumps(fixture()))
            fake = ReadOnlyMT5(rates([100] * 100))
            app = create_app(mt5=fake, clock=Mock(side_effect=[NOW, NOW, NOW - timedelta(minutes=1)]),
                             session_config_path=path)
            client = app.test_client()
            self.assertEqual(client.get('/analyze?symbol=XAUUSD&timeframe=M1').status_code, 200)
            response = client.get('/analyze?symbol=XAUUSD&timeframe=M1')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()['quality']['diagnostics'][0]['code'], 'CLOCK_MOVED_BACKWARD')
            self.assertEqual(len(fake.calls), 1)

    def test_valid_file_quality_and_compatibility_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calendar.json'
            path.write_text(json.dumps(fixture()))
            fake = ReadOnlyMT5(rates([100] * 100))
            app = create_app(mt5=fake, clock=lambda: NOW, session_config_path=path)
            response = app.test_client().get('/analyze?symbol=XAUUSD&timeframe=1m')
            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertEqual(body['signal'], 'WAIT')
            self.assertIs(body['execution_allowed'], False)
            self.assertEqual(body['timeframe'], '1m')
            self.assertTrue(body['quality']['valid'])
            self.assertIn('DATA_VALID', [d['code'] for d in body['quality']['diagnostics']])

    def test_invalid_file_is_safe_and_never_contacts_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calendar.json'
            path.write_text('{"private-input":"not a valid calendar"}')
            fake = ReadOnlyMT5([])
            app = create_app(mt5=fake, clock=lambda: NOW, session_config_path=path)
            response = app.test_client().get('/analyze?symbol=XAUUSD&timeframe=M1')
            self.assertEqual(response.status_code, 503)
            body = response.get_json()
            self.assertIs(body['execution_allowed'], False)
            self.assertEqual(body['quality']['diagnostics'][0]['code'], 'SESSION_CONFIG_INVALID')
            self.assertNotIn('private-input', response.get_data(as_text=True))
            self.assertEqual(fake.calls, [])

    def test_environment_config_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calendar.json'
            path.write_text(json.dumps(fixture()))
            with patch.dict(os.environ, {'IAT_SESSION_CONFIG': str(path)}):
                app = create_app(mt5=ReadOnlyMT5(rates([100] * 100)), clock=lambda: NOW)
            self.assertEqual(app.test_client().get('/analyze?symbol=XAUUSD&timeframe=M1').status_code, 200)

    def test_missing_file_and_conflicting_sources_fail_closed(self):
        for options in ({'session_config_path': '/no-such-iat-calendar.json'},
                        {'session_config_path': '/no-such-iat-calendar.json', 'session_calendars': {}}):
            fake = ReadOnlyMT5([])
            app = create_app(mt5=fake, clock=lambda: NOW, **options)
            response = app.test_client().get('/analyze?symbol=XAUUSD&timeframe=M1')
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.get_json()['quality']['valid'])
            self.assertEqual(fake.calls, [])

    def test_malformed_market_data_has_specific_public_reason_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calendar.json'
            path.write_text(json.dumps(fixture()))
            data = rates([100] * 100)
            data[1]['time'] = data[0]['time']
            app = create_app(mt5=ReadOnlyMT5(data), clock=lambda: NOW, session_config_path=path)
            response = app.test_client().get('/analyze?symbol=XAUUSD&timeframe=M1')
            body = response.get_json()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(body['error'], 'MARKET_DATA_UNAVAILABLE')
            self.assertEqual(body['quality']['diagnostics'][0]['code'], 'TIMESTAMP_DUPLICATE')
            self.assertEqual(body['signal'], 'WAIT')
            self.assertIs(body['execution_allowed'], False)
