"""Atomic publication and privacy regressions; all terminal APIs are mocked."""
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diagnostics import mt5_readonly_check as diagnostic
from iat.evidence import AtomicEvidence, diagnostic as note, validate_report
from test_api import NOW
from test_diagnostic import DemoAdapter, SECRET, demo_config


class EvidenceTests(unittest.TestCase):
    def test_initial_file_is_explicit_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'evidence.json'
            initial = diagnostic.new_report()
            AtomicEvidence(path, initial)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['status'], 'FAIL')
            self.assertEqual(saved['diagnostics'][0]['code'], 'RUN_INCOMPLETE')
            self.assertEqual(saved['run_id'], initial['run_id'])

    def test_existing_report_is_never_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.json'
            path.write_text('prior-run')
            with self.assertRaises(FileExistsError):
                AtomicEvidence(path, diagnostic.new_report())
            self.assertEqual(path.read_text(), 'prior-run')

    def test_failed_atomic_replace_leaves_failure_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'evidence.json'
            report = diagnostic.new_report()
            writer = AtomicEvidence(path, report)
            with patch('iat.evidence.os.replace', side_effect=OSError(SECRET)), self.assertRaises(OSError):
                writer.publish(report)
            self.assertEqual(json.loads(path.read_text())['status'], 'FAIL')
            self.assertEqual(list(Path(directory).iterdir()), [path])
            self.assertNotIn(SECRET, path.read_text())

    def test_invalid_or_unredacted_report_cannot_replace_placeholder(self):
        for change in ('secret-field', 'secret-explanation', 'unsafe', 'nan', 'premature-pass'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'evidence.json'
                initial = diagnostic.new_report()
                writer = AtomicEvidence(path, initial)
                report = copy.deepcopy(initial)
                if change == 'secret-field':
                    report['account_number'] = SECRET
                elif change == 'secret-explanation':
                    report['diagnostics'][0]['explanation'] = SECRET
                elif change == 'unsafe':
                    report['safety']['execution_allowed'] = True
                elif change == 'nan':
                    report['timeframes']['M1']['age_seconds'] = float('nan')
                else:
                    report['status'] = 'PASS'
                    report['diagnostics'] = [note('CHECKS_PASSED')]
                with self.assertRaises(ValueError):
                    writer.publish(report)
                self.assertEqual(json.loads(path.read_text())['status'], 'FAIL')

    def run_cli(self, directory, extra=None, fail_publish=False):
        config = Path(directory) / 'config.json'
        config.write_text(json.dumps(demo_config()))
        report_path = Path(directory) / 'evidence.json'
        adapter = DemoAdapter()
        real = diagnostic.validate_demo
        output = io.StringIO()
        def frozen(*args, **kwargs):
            return real(*args, mt5=adapter, clock=lambda: NOW, **kwargs)
        with patch.object(diagnostic, 'validate_demo', side_effect=frozen), \
                patch.object(diagnostic, 'package_version', return_value='5.0.5370'), \
                contextlib.redirect_stdout(output):
            if fail_publish:
                with patch('iat.evidence.os.replace', side_effect=OSError(SECRET)):
                    result = diagnostic.main(['--config', str(config), '--report-path', str(report_path)] + (extra or []))
            else:
                result = diagnostic.main(['--config', str(config), '--report-path', str(report_path)] + (extra or []))
        self.assertNotIn(SECRET, output.getvalue())
        self.assertNotIn(SECRET, report_path.read_text())
        return result, json.loads(report_path.read_text()), adapter, output.getvalue()

    def test_cli_success_is_published_only_after_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            result, saved, adapter, output = self.run_cli(directory)
            self.assertEqual(result, 0)
            self.assertEqual(saved['status'], 'PASS')
            self.assertTrue(saved['safety']['shutdown_completed'])
            self.assertTrue(adapter.stopped)
            validate_report(saved)
            self.assertEqual(saved, json.loads(output))

    def test_cli_failed_publication_never_prints_or_leaves_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result, saved, adapter, output = self.run_cli(directory, fail_publish=True)
            self.assertEqual(result, 1)
            self.assertEqual(saved['status'], 'FAIL')
            self.assertEqual(saved['diagnostics'][0]['code'], 'RUN_INCOMPLETE')
            self.assertNotIn('PASS', output)
            self.assertTrue(adapter.stopped)

    def test_local_weekly_export_with_utf8_bom_yields_warn_not_false_broker_pass(self):
        from test_broker_sessions import BrokerSessionTests
        with tempfile.TemporaryDirectory() as directory:
            metadata = Path(directory) / 'metadata.json'
            metadata.write_bytes(json.dumps(BrokerSessionTests().weekly()).encode('utf-8-sig'))
            result, saved, adapter, _ = self.run_cli(directory, ['--broker-metadata', str(metadata)])
            self.assertEqual(result, 2)
            self.assertEqual(saved['status'], 'WARN')
            self.assertIn('BROKER_EXCEPTIONS_UNVERIFIED', saved['calendar']['codes'])
            self.assertTrue(adapter.stopped)

    def test_cli_invalid_metadata_file_writes_failure_before_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = Path(directory) / 'metadata.json'
            metadata.write_text('{"bad-key":"' + SECRET + '"')
            result, saved, adapter, _ = self.run_cli(directory, ['--broker-metadata', str(metadata)])
            self.assertEqual(result, 1)
            self.assertEqual(saved['status'], 'FAIL')
            self.assertFalse(adapter.initialized)

    def test_cli_existing_path_blocks_terminal_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing.json'
            path.write_text('old-run')
            output = io.StringIO()
            with patch.object(diagnostic, 'validate_demo') as run, contextlib.redirect_stdout(output):
                result = diagnostic.main(['--report-path', str(path)])
            self.assertEqual(result, 1)
            run.assert_not_called()
            self.assertNotIn('PASS', output.getvalue())
