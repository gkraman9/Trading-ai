"""Labeled synthetic fixtures only; operator runner has no fixture substitution path."""

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import csv
import json
import subprocess
import unittest

from iat.boundary_reproduction import verify, projection, EXPECTED, Failure
from iat.chart_benchmark import hashed, check_hash
from iat.historical_evidence_manifest import HEADERS, MAPPING
from iat.historical_session_boundaries import inspect_csv_files
from test_historical_session_boundaries import observations
from diagnostics.verify_boundary_evidence import main

START = "2026-11-12T21:50:00Z"
END = "2026-11-12T23:10:00Z"
PROFILE = Path("config/profiles/exness-xauusd-v2.candidate.json")


def fixture(root):
    """18 invented M1/4 invented M5 bars; never recreate the operator's 4,074/816 export."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cal = root / "calendar.json"
    cal.write_bytes(PROFILE.read_bytes())
    rows = observations(json.loads(cal.read_text()), START, END)
    files = {}
    for tf, bars in rows.items():
        p = root / (tf + "-SYNTHETIC.csv")
        files[tf] = p
        with p.open("w", encoding="utf-8", newline="") as h:
            writer = csv.DictWriter(h, fieldnames=HEADERS, lineterminator="\n")
            writer.writeheader()
            for b in bars:
                writer.writerow(
                    dict(
                        timestamp_utc=b["timestamp"],
                        **{k: b[k] for k in ("open", "high", "low", "close")},
                        tick_volume=10,
                        spread=20,
                        real_volume=0
                    )
                )
    report = inspect_csv_files(files["M1"], files["M5"], cal, START, END, MAPPING)
    old = root / "original-SYNTHETIC.json"
    # Match the existing diagnostic's explicit UTF-8/LF writer on every test OS.
    # Operator evidence files are never rewritten; CRLF differences have a separate regression.
    old.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    return files["M1"], files["M5"], old, cal


class BoundaryReproductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="iat SYNTHETIC boundary reproduction ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = fixture(self.root / "inputs")

    def run_case(self, name="out"):
        return verify(*self.inputs, self.root / name, start=START, end=END)

    def change_original(self, fn):
        p = self.inputs[2]
        r = json.loads(p.read_text())
        r.pop("sha256")
        fn(r)
        p.write_text(json.dumps(hashed(r)), encoding="utf-8")

    def assert_safe(self, r):
        self.assertEqual(r["signal"], "WAIT")
        self.assertFalse(r["execution_allowed"])
        self.assertEqual(r["qualification"], "DATA_NOT_QUALIFIED")
        self.assertEqual(r["exness"], "BLOCKED")
        self.assertEqual(r["historical_validation"], "PENDING")
        self.assertEqual(r["historical_comparisons"], "NOT_RUN")
        self.assertTrue(all(c["status"] == "UNRESOLVED" for c in r["conflicts"]))
        check_hash(r)

    def test_actual_file_workflow_reuses_diagnostic_and_records_unchanged_exact_hashes(
        self,
    ):
        before = [p.read_bytes() for p in self.inputs]
        r = self.run_case()
        self.assert_safe(r)
        self.assertEqual(r["diagnostic"]["exit_code"], 3)
        self.assertEqual(r["comparison"]["status"], "MATCH")
        self.assertTrue(r["comparison"]["payload_hash_equal"])
        self.assertTrue(r["comparison"]["exact_report_bytes_equal"])
        self.assertTrue(all(v["unchanged"] for v in r["input_integrity"].values()))
        self.assertEqual(before, [p.read_bytes() for p in self.inputs])
        self.assertEqual(
            r["status"], "DIFFERENCES_FOUND"
        )  # Tiny synthetic fixture does not match operator counts.
        self.assertIn("REPORTED_COUNTS_DIFFER", r["reason_codes"])
        self.assertEqual(len(r["boundaries"]), 6)
        self.assertTrue(
            all(
                b["actual_first_tick_utc"] is None
                and b["trading_permission_proven"] is False
                for b in r["boundaries"]
            )
        )

    def test_repeatability_excludes_private_output_paths(self):
        a = self.run_case("one")
        b = self.run_case("two")
        self.assertEqual(a, b)
        self.assertNotIn(str(self.root), json.dumps(a))

    def test_even_a_complete_mechanical_match_does_not_resolve_any_assurance_gate(self):
        # Small synthetic expectations exercise this branch, not the real expected row counts.
        small = projection(json.loads(self.inputs[2].read_text()))["metrics"]
        with patch("iat.boundary_reproduction.EXPECTED", small):
            r = self.run_case()
        self.assertEqual(r["status"], "LOCAL_MECHANICAL_MATCH")
        self.assert_safe(r)
        self.assertEqual(EXPECTED["M1_observations"], 4074)

    def test_changed_comparison_counts_are_reported_not_silently_accepted(self):
        self.change_original(lambda r: r["comparison_counts"].update(FIVE_M1_MATCH=999))
        r = self.run_case()
        self.assertEqual(r["comparison"]["status"], "DIFFERENT")
        self.assertTrue(
            any(
                "/comparison_counts/FIVE_M1_MATCH" == d["field"]
                for d in r["comparison"]["differences"]
            )
        )
        self.assert_safe(r)

    def test_unprojected_metadata_revision_cannot_pass_as_an_identical_payload(self):
        self.change_original(lambda r: r.update(finality="UNESTABLISHED_BUT_CHANGED"))
        r = self.run_case()
        self.assertEqual(r["comparison"]["status"], "DIFFERENT")
        self.assertFalse(r["comparison"]["payload_hash_equal"])
        self.assertTrue(
            any(
                d["field"] == "/diagnostic_payload_sha256"
                for d in r["comparison"]["differences"]
            )
        )

    def test_original_without_file_bindings_never_becomes_proven_same_input(self):
        self.change_original(lambda r: r.pop("file_observations"))
        r = self.run_case()
        self.assertTrue(
            all(
                v == "UNAVAILABLE"
                for v in r["comparison"]["original_input_bindings"].values()
            )
        )
        self.assertEqual(r["status"], "DIFFERENCES_FOUND")

    def test_original_fingerprints_show_exact_old_vs_current_bytes(self):
        self.change_original(
            lambda r: r["file_observations"]["sources"]["M1"]["fingerprint"].update(
                sha256="a" * 64
            )
        )
        r = self.run_case()
        self.assertEqual(r["comparison"]["original_input_bindings"]["M1"], "DIFFERENT")
        self.assertEqual(
            r["comparison"]["original_declared_input_fingerprints"]["M1"]["sha256"],
            "a" * 64,
        )
        self.assertNotEqual(r["input_integrity"]["M1"]["before"]["sha256"], "a" * 64)

    def test_invalid_checksum_and_rechecksummed_unsafe_report_fail_closed(self):
        original = self.inputs[2].read_bytes()
        self.inputs[2].write_text(
            original.decode().replace('"DATA_NOT_QUALIFIED"', '"DATA_QUALIFIED"')
        )
        r = self.run_case("bad-checksum")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("DIAGNOSTIC_PAYLOAD_CHECKSUM_INVALID", r["reason_codes"])
        self.inputs[2].write_bytes(original)
        self.change_original(lambda r: r["safety"].update(execution_allowed=True))
        r = self.run_case("bad-safety")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("DIAGNOSTIC_SAFETY_INVARIANT_FAILED", r["reason_codes"])
        self.assertEqual(r["diagnostic"]["status"], "NOT_RUN")

    def test_duplicate_and_reversed_timestamps_are_recorded_before_diagnostic(self):
        p = self.inputs[0]
        lines = p.read_text().splitlines()
        lines[2] = lines[1]
        p.write_text("\n".join(lines) + "\n")
        r = self.run_case("duplicate")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(r["scans"]["M1"]["errors"]["TIMESTAMP_DUPLICATE"], 1)
        lines[2], lines[3] = lines[3], lines[2]
        p.write_text("\n".join(lines) + "\n")
        r = self.run_case("reverse")
        self.assertIn("TIMESTAMP_OUT_OF_ORDER", r["scans"]["M1"]["errors"])
        self.assertEqual(r["diagnostic"]["status"], "NOT_RUN")

    def test_naive_nonzero_offset_and_header_guessing_are_rejected(self):
        p = self.inputs[0]
        original = p.read_text()
        for label, content in [
            ("naive", original.replace("+00:00", "")),
            ("offset", original.replace("+00:00", "+01:00")),
            ("header", original.replace("timestamp_utc", "Time")),
        ]:
            p.write_text(content)
            r = self.run_case(label)
            self.assertEqual(r["status"], "BLOCKED")
            self.assertEqual(r["diagnostic"]["status"], "NOT_RUN")

    def test_malformed_ohlc_and_outside_window_rows_are_not_normalized_away(self):
        p = self.inputs[0]
        original = p.read_text()
        p.write_text(
            original.replace("100.0,101.0,99.0,100.0", "100.0,nan,99.0,100.0", 1)
        )
        r = self.run_case("ohlc")
        self.assertIn("OHLC_INVALID", r["reason_codes"])
        p.write_text(original.replace("2026-11-12T21:50:00", "2026-11-12T21:45:00", 1))
        r = self.run_case("scope")
        self.assertIn("OUTSIDE_REQUESTED_WINDOW", r["scans"]["M1"]["errors"])

    def test_missing_input_no_fallback_and_new_output_directory_only(self):
        self.inputs[0].unlink()
        r = self.run_case()
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(r["comparison"]["status"], "NOT_RUN")
        self.assertIn("REQUIRED_INPUT_UNAVAILABLE_M1", r["reason_codes"])
        before = (self.root / "out/evidence-summary.json").read_bytes()
        with self.assertRaises(Failure):
            self.run_case()
        self.assertEqual((self.root / "out/evidence-summary.json").read_bytes(), before)

    def test_input_change_during_child_run_prevents_any_match_claim(self):
        run = subprocess.run

        def changed(*args, **kw):
            child = run(*args, **kw)
            self.inputs[0].write_bytes(self.inputs[0].read_bytes() + b"\n")
            return child

        with patch("iat.boundary_reproduction.subprocess.run", side_effect=changed):
            r = self.run_case()
        self.assertEqual(r["status"], "BLOCKED")
        self.assertFalse(r["input_integrity"]["M1"]["unchanged"])
        self.assertEqual(r["comparison"]["status"], "NOT_ESTABLISHED_INPUT_CHANGED")

    def test_bad_child_exit_and_atomic_publication_failure_never_leave_success(self):
        with patch(
            "iat.boundary_reproduction.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0),
        ):
            r = self.run_case("exit")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("DIAGNOSTIC_EXIT_CODE_UNEXPECTED", r["reason_codes"])
        from iat.chart_benchmark import write_new

        def failed(path, value):
            if Path(path).name == "evidence-summary.json":
                raise OSError("simulated")
            write_new(path, value)

        with patch(
            "iat.boundary_reproduction.write_new", side_effect=failed
        ), redirect_stdout(StringIO()) as output:
            code = main(
                [
                    "--m1",
                    str(self.inputs[0]),
                    "--m5",
                    str(self.inputs[1]),
                    "--original-report",
                    str(self.inputs[2]),
                    "--calendar",
                    str(self.inputs[3]),
                    "--output-directory",
                    str(self.root / "publish"),
                    "--start-utc",
                    START,
                    "--end-utc",
                    END,
                ]
            )
        self.assertEqual(code, 2)
        self.assertFalse((self.root / "publish/evidence-summary.json").exists())
        self.assertNotIn("simulated", output.getvalue())

    def test_paths_inside_repository_or_unc_rejected_without_writing(self):
        from iat.boundary_reproduction import ROOT, safe_path

        with self.assertRaises(Failure):
            verify(*self.inputs, ROOT / "must-not-be-created")
        self.assertFalse((ROOT / "must-not-be-created").exists())
        for name in ("\\\\server\\share\\x.csv", "https://example.invalid/x.csv"):
            with self.assertRaises(ValueError):
                safe_path(name)

    def test_partial_geometry_and_slot_classifications_are_compared_explicitly(self):
        def changed(r):
            bar = next(
                b
                for b in r["m5_intervals"]
                if b["geometry"]["classification"] == "PARTIAL_SESSION_CLOSE"
            )
            bar["geometry"]["market_open_seconds"] = 179
            bar["m1_slots"][-1]["assessment"] = "UNRESOLVED_CHANGED"

        self.change_original(changed)
        r = self.run_case()
        fields = [d["field"] for d in r["comparison"]["differences"]]
        self.assertTrue(any(p.endswith("/nominal_quote_seconds") for p in fields))
        self.assertTrue(any(p.endswith("/assessment") for p in fields))

    def test_report_byte_difference_is_recorded_without_normalizing_evidence(self):
        p = self.inputs[2]
        old = json.loads(p.read_text())
        p.write_bytes((json.dumps(old, indent=1) + "\r\n").encode())
        before = p.read_bytes()
        r = self.run_case()
        self.assertEqual(r["comparison"]["status"], "MATCH")
        self.assertTrue(r["comparison"]["payload_hash_equal"])
        self.assertFalse(r["comparison"]["exact_report_bytes_equal"])
        self.assertEqual(p.read_bytes(), before)

    def test_every_missing_input_is_recorded_and_readable_calendar_is_still_hashed(
        self,
    ):
        for p in self.inputs[:3]:
            p.unlink()
        r = self.run_case()
        self.assertEqual(len(r["input_integrity"]), 4)
        self.assertEqual(r["input_integrity"]["calendar"]["status"], "READABLE")
        self.assertTrue(r["input_integrity"]["calendar"]["unchanged"])
        self.assertTrue(
            all(
                r["input_integrity"][k]["status"] == "UNAVAILABLE_OR_UNSAFE"
                for k in ("M1", "M5", "original_report")
            )
        )

    def test_explicitly_synthetic_original_report_is_not_operator_evidence(self):
        self.change_original(lambda r: r.update(provenance="SYNTHETIC_ONLY"))
        r = self.run_case()
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn(
            "DECLARED_SYNTHETIC_REPORT_NOT_OPERATOR_EVIDENCE", r["reason_codes"]
        )
        self.assertEqual(r["comparison"]["status"], "NOT_RUN")
